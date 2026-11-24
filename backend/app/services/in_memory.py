"""Synthetic domain services with local SQLAlchemy conversation persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import time

from sqlalchemy.exc import SQLAlchemyError

from backend.app.ai.answer import PolicyRetriever
from backend.app.ai.investigation import (
    InvestigationModel,
    ModelDecision,
    OrderFacts,
    run_investigation,
)
from backend.app.ai.generation import PolicyAnswerProvider, UntrustedCustomerMemory
from backend.app.contracts import (
    ActorSummary,
    AppendMessageResponse,
    ConversationSummary,
    CreateConversationRequest,
    CreateRefundRequest,
    DemoLoginResponse,
    Message,
    OrderSummary,
    RefundListResponse,
    RefundSummary,
    SupportConversationSummary,
    SupportInboxResponse,
)
from backend.app.db import (
    ConversationRepository,
    CustomerMemoryLimitError,
    CustomerMemoryRepository,
    CustomerMemoryValidationError,
    PolicyConflict,
    PolicyIndexUpdater,
    PolicyRepository,
    PolicySection,
    PolicyValidationError,
    RefundRepository,
    StoredConversation,
    StoredRefund,
    StoredPolicyAudit,
    StoredPolicyVersion,
)
from backend.app.db.conversations import create_database_engine
from backend.app.commerce import CommerceRepository
from backend.app.diagnostics import log_event


class _DemoInvestigationModel:
    """Deterministic local classifier used until a model SDK is authorized."""

    def classify(self, query: str) -> ModelDecision:
        normalized = query.casefold()
        has_policy_context = any(
            term in normalized
            for term in ("policy", "eligible", "eligibility", "return window", "published")
        )
        has_order_context = any(
            term in normalized
            for term in (
                "order", "shipment", "delivery", "paid", "payment", "refund",
                "return", "status", "total",
            )
        )
        if any(
            phrase in normalized
            for phrase in (
                "change the order", "override the recorded", "execute the payment",
                "issue money", "approve the refund", "refund this order immediately",
                "create a refund", "cancel the order and",
            )
        ):
            return ModelDecision(
                intent="refund_request" if "refund" in normalized else "unknown"
            )
        if has_policy_context and has_order_context:
            return ModelDecision(intent="database_policy_question")
        if "refund" in normalized and any(
            term in normalized
            for term in ("status", "review", "approved", "pending", "decision", "state", "happened")
        ):
            return ModelDecision(intent="refund_status")
        if "order" in normalized and any(
            term in normalized
            for term in (
                "status", "delayed", "processing", "delivered", "cancelled",
                "in transit", "happened", "still show",
            )
        ) and not any(
            term in normalized for term in ("payment", "paid", "pay", "amount", "total")
        ):
            return ModelDecision(intent="order_status")
        if any(
            term in normalized
            for term in ("authoritative", "outdated", "older", "conflict", "conflicting", "stale", "latest", "stored")
        ) and any(term in normalized for term in ("order", "status", "state", "carrier", "message", "timestamp", "estimate", "tracking", "shipment")):
            return ModelDecision(intent="order_status")
        if "refund" in normalized:
            return ModelDecision(intent="refund_request")
        if "status" in normalized and any(
            term in normalized for term in ("order", "shipment", "delivery")
        ):
            return ModelDecision(intent="order_status")
        if any(
            term in normalized
            for term in ("total", "payment", "paid", "pay", "charged", "amount")
        ):
            return ModelDecision(intent="payment_total")
        if any(
            term in normalized
            for term in (
                "tracking", "carrier", "shipped", "sent", "delivered", "arrive", "promised", "expected", "estimate", "delivery information", "delivery details", "delivery date", "delivery state", "shipment details", "shipment reference",
            )
        ):
            # A guarantee question asks for the published delivery policy,
            # not an order-specific tracking fact.  Keep this before the
            # shipment-facts branch so the basic local demo order can answer
            # it without pretending that tracking data is available.
            if any(term in normalized for term in ("guarantee", "guaranteed")):
                return ModelDecision(intent="policy_question")
            return ModelDecision(intent="shipment_tracking")
        if any(
            phrase in normalized
            for phrase in (
                "where is",
                "order status",
                "track my",
                "tracking",
                "delivery status",
                "shipment status",
                "current status",
                "order details",
                "order facts",
                "foreign order",
            )
        ):
            return ModelDecision(intent="order_status")
        if any(
            term in normalized
            for term in (
                "where", "stands", "happening", "current", "latest",
                "other order", "second order", "order two",
            )
        ) and "order" in normalized:
            return ModelDecision(intent="order_status")
        # Policy retrieval is the safe default for non-transactional
        # questions.  The grounded-answer layer hands off when evidence is
        # insufficient rather than inventing a response.
        return ModelDecision(intent="policy_question")


# Public only for deterministic local evaluation; production model selection
# remains dependency-injected through ``InMemoryResolveService``.
DemoInvestigationModel = _DemoInvestigationModel


class _AuthorizedOrderFactsTool:
    """Typed order-facts boundary scoped to the authenticated customer."""

    def __init__(self, service: "InMemoryResolveService", customer_id: str | None) -> None:
        self._service = service
        self._customer_id = customer_id

    def get_order_facts(self, order_id: str) -> OrderFacts | None:
        order = self._service._order_for_customer(order_id, self._customer_id)
        if order is None:
            return None
        summary = order.summary
        refund_state = order.refund_state
        if refund_state is None:
            refund_state = next(
                (
                    refund.state
                    for refund in self._service._refund_repository.list_all()
                    if refund.order_id == summary.order_id
                ),
                None,
            )
        return OrderFacts(
            order_id=summary.order_id,
            status=summary.status,
            shipment_status=summary.shipment_status,
            estimated_delivery=(
                None
                if summary.estimated_delivery_date is None
                else summary.estimated_delivery_date.isoformat()
            ),
            total_cents=order.total_cents,
            payment_amount_cents=order.payment_amount_cents,
            payment_status=(
                None
                if order.payment_status is None
                else {"completed": "paid", "failed": "failed"}.get(
                    order.payment_status, summary.payment_status
                )
            ),
            payment_method=order.payment_method,
            tracking_number=order.tracking_number,
            shipped_at=(None if order.shipped_at is None else order.shipped_at.isoformat()),
            delivered_at=(None if order.delivered_at is None else order.delivered_at.isoformat()),
            refund_state=refund_state,
        )


DEMO_ACTOR_ID = "customer_001"
SUPPORT_ACTOR_ID = "support_001"
REFUND_APPROVER_ACTOR_ID = "refund_approver_001"
MERCHANT_ADMIN_ACTOR_ID = "merchant_admin_001"
DEMO_SESSION_ID = "demo-session-customer_001"
SUPPORT_SESSION_ID = "demo-session-support_001"
REFUND_APPROVER_SESSION_ID = "demo-session-refund-approver_001"
MERCHANT_ADMIN_SESSION_ID = "demo-session-merchant-admin_001"
MESSAGE_TIMESTAMP = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
REFUNDABLE_LIMIT_CENTS = 5000


class ConversationStateConflict(RuntimeError):
    """Raised when a requested transition is not valid for the current state."""


class ForbiddenOperation(RuntimeError):
    """Raised when an authenticated actor lacks the required assignment/role."""


class RefundValidationError(ValueError):
    """Raised when a refund request fails deterministic business validation."""


class IdempotencyConflict(RuntimeError):
    """Raised when an idempotency key is reused for different request data."""


@dataclass(frozen=True)
class _OrderRecord:
    owner_customer_id: str
    summary: OrderSummary
    max_refundable_cents: int = REFUNDABLE_LIMIT_CENTS


@dataclass(frozen=True)
class _AuthorizedOrder:
    summary: OrderSummary
    max_refundable_cents: int
    total_cents: int | None = None
    payment_amount_cents: int | None = None
    payment_status: str | None = None
    payment_method: str | None = None
    tracking_number: str | None = None
    shipped_at: datetime | None = None
    promised_delivery_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime | None = None
    refund_state: str | None = None


class InMemoryResolveService:
    """Per-application synthetic data with configurable conversation storage."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        policy_retriever: PolicyRetriever | None = None,
        response_provider: PolicyAnswerProvider | None = None,
        investigation_model: InvestigationModel | None = None,
        commerce_repository: CommerceRepository | None = None,
        policy_index_updater: PolicyIndexUpdater | None = None,
        session_ttl_seconds: int = 3_600,
    ) -> None:
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        self._session_ttl_seconds = session_ttl_seconds
        self._sessions: dict[str, tuple[str, float]] = {}
        self._policy_retriever = policy_retriever
        self._response_provider = response_provider
        self._investigation_model = investigation_model or _DemoInvestigationModel()
        self._commerce_repository = commerce_repository
        configured_database_url = database_url or "sqlite+pysqlite:///:memory:"
        database_engine = create_database_engine(configured_database_url)
        self._repository = ConversationRepository(
            configured_database_url, engine=database_engine
        )
        self._memory_repository = CustomerMemoryRepository(
            configured_database_url, engine=database_engine, initialize_schema=False
        )
        self._refund_repository = RefundRepository(
            configured_database_url, engine=database_engine
        )
        self._policy_repository = PolicyRepository(
            configured_database_url,
            engine=database_engine,
            index_updater=policy_index_updater,
        )
        self._orders = {
            "order_1001": _OrderRecord(
                owner_customer_id=DEMO_ACTOR_ID,
                summary=OrderSummary(
                    order_id="order_1001",
                    status="delayed",
                    payment_status="paid",
                    shipment_status="delayed",
                    estimated_delivery_date=date(2026, 11, 8),
                ),
            ),
            "order_1002": _OrderRecord(
                owner_customer_id="customer_002",
                summary=OrderSummary(
                    order_id="order_1002",
                    status="processing",
                    payment_status="pending",
                    shipment_status="not_shipped",
                    estimated_delivery_date=None,
                ),
            ),
        }
        self._repository.ensure_conversation(
            "conv_foreign_001",
            owner_customer_id="customer_002",
            channel="widget",
            state="AI_ACTIVE",
            order_id="order_1002",
            created_at=MESSAGE_TIMESTAMP,
        )

    @staticmethod
    def actor_summary(actor_id: str = DEMO_ACTOR_ID) -> ActorSummary:
        if actor_id == SUPPORT_ACTOR_ID:
            return ActorSummary(
                actor_id=SUPPORT_ACTOR_ID,
                display_name="Demo Support Agent",
                role="support_agent",
                customer_id=None,
                permissions=["support:inbox", "support:conversations"],
            )
        if actor_id == REFUND_APPROVER_ACTOR_ID:
            return ActorSummary(
                actor_id=REFUND_APPROVER_ACTOR_ID,
                display_name="Demo Refund Approver",
                role="refund_approver",
                customer_id=None,
                permissions=["refunds:review"],
            )
        if actor_id == MERCHANT_ADMIN_ACTOR_ID:
            return ActorSummary(
                actor_id=MERCHANT_ADMIN_ACTOR_ID,
                display_name="Demo Merchant Admin",
                role="merchant_admin",
                customer_id=None,
                permissions=["workspace:admin"],
            )
        if actor_id == DEMO_ACTOR_ID:
            return ActorSummary(
                actor_id=DEMO_ACTOR_ID,
                display_name="Demo Customer",
                role="customer",
                customer_id=DEMO_ACTOR_ID,
                permissions=["orders:read:self"],
            )
        raise ValueError(f"unknown demo actor: {actor_id}")

    def demo_login(self, demo_actor_id: str) -> DemoLoginResponse | None:
        session_by_actor = {
            DEMO_ACTOR_ID: DEMO_SESSION_ID,
            SUPPORT_ACTOR_ID: SUPPORT_SESSION_ID,
            REFUND_APPROVER_ACTOR_ID: REFUND_APPROVER_SESSION_ID,
            MERCHANT_ADMIN_ACTOR_ID: MERCHANT_ADMIN_SESSION_ID,
        }
        session_id = session_by_actor.get(demo_actor_id)
        if session_id is None:
            return None
        self._sessions[session_id] = (
            demo_actor_id,
            time.monotonic() + self._session_ttl_seconds,
        )
        return DemoLoginResponse(
            session_id=session_id,
            actor=self.actor_summary(demo_actor_id),
        )

    def actor_for_session(self, session_id: str | None) -> ActorSummary | None:
        if session_id is None:
            return None
        session = self._sessions.get(session_id)
        if session is None:
            return None
        actor_id, expires_at = session
        if time.monotonic() >= expires_at:
            self._sessions.pop(session_id, None)
            return None
        return self.actor_summary(actor_id)

    def logout(self, session_id: str | None) -> bool:
        """Invalidate one active demo session without exposing its actor."""

        if session_id is None:
            return False
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        _, expires_at = session
        return time.monotonic() < expires_at

    def database_ready(self) -> bool:
        """Expose only a boolean dependency check to the HTTP readiness route."""

        conversation_ready = self._repository.database_ready()
        commerce_ready = (
            self._commerce_repository is None
            or self._commerce_repository.database_ready()
        )
        return conversation_ready and commerce_ready

    @property
    def policy_repository(self) -> PolicyRepository:
        """Expose the policy repository to authorized API handlers only."""

        return self._policy_repository

    def create_policy(
        self,
        *,
        actor: ActorSummary,
        document_id: str,
        title: str,
        document_version: str | None,
        visibility: str,
        sections: list[dict[str, str]],
    ) -> StoredPolicyVersion:
        if actor.role != "merchant_admin":
            raise ForbiddenOperation("policy mutations require merchant_admin")
        return self._policy_repository.create(
            actor_id=actor.actor_id,
            actor_role=actor.role,
            document_id=document_id,
            title=title,
            document_version=document_version,
            release_id=None,
            visibility=visibility,
            sections=[
                PolicySection(section=item.get("section", ""), text=item.get("text") or item.get("content") or "")
                for item in sections
            ],
        )

    def edit_policy(
        self,
        version_id: str,
        *,
        actor: ActorSummary,
        expected_revision: int,
        title: str | None,
        release_id: str | None,
        visibility: str | None,
        sections: list[dict[str, str]] | None,
    ) -> StoredPolicyVersion:
        if actor.role != "merchant_admin":
            raise ForbiddenOperation("policy mutations require merchant_admin")
        current = self._policy_repository.get_by_id(version_id)
        if current is None:
            raise KeyError(version_id)
        return self._policy_repository.update_draft(
            current.document_id,
            current.document_version,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            expected_revision=expected_revision,
            release_id=release_id or current.release_id,
            visibility=visibility or current.visibility,
            sections=(
                current.sections
                if sections is None
                else [
                    PolicySection(section=item.get("section", ""), text=item.get("text") or item.get("content") or "")
                    for item in sections
                ]
            ),
            title=title,
        )

    def validate_policy(self, version_id: str, *, actor: ActorSummary) -> tuple[StoredPolicyVersion, list[str]]:
        if actor.role != "merchant_admin":
            raise ForbiddenOperation("policy validation requires merchant_admin")
        version = self._policy_repository.get_by_id(version_id)
        if version is None:
            raise KeyError(version_id)
        return version, self._policy_repository.validate(version_id)

    def index_policy(
        self,
        version_id: str,
        *,
        actor: ActorSummary,
        fail_reason: str | None = None,
        expected_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> StoredPolicyVersion:
        if actor.role != "merchant_admin":
            raise ForbiddenOperation("policy indexing requires merchant_admin")
        return self._policy_repository.index(
            version_id,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            fail_reason=fail_reason,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    def publish_policy(self, version_id: str, *, actor: ActorSummary, expected_revision: int | None = None, idempotency_key: str | None = None) -> StoredPolicyVersion:
        if actor.role != "merchant_admin":
            raise ForbiddenOperation("policy publishing requires merchant_admin")
        current = self._policy_repository.get_by_id(version_id)
        if current is None:
            raise KeyError(version_id)
        return self._policy_repository.publish(
            current.document_id,
            current.document_version,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            expected_revision=current.revision if expected_revision is None else expected_revision,
            idempotency_key=idempotency_key,
        )

    def rollback_policy(self, document_id: str, document_version: str, *, actor: ActorSummary, expected_revision: int | None = None) -> StoredPolicyVersion:
        if actor.role != "merchant_admin":
            raise ForbiddenOperation("policy rollback requires merchant_admin")
        active = next(
            (item for item in self._policy_repository.list(document_id=document_id) if item.is_active),
            None,
        )
        if active is None:
            raise KeyError(document_id)
        return self._policy_repository.rollback(
            document_id,
            active.document_version,
            target_version=document_version,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            expected_revision=active.revision if expected_revision is None else expected_revision,
        )

    def policy_versions(self, document_id: str, *, actor: ActorSummary) -> list[StoredPolicyVersion]:
        if actor.role not in {"support_agent", "refund_approver", "merchant_admin"}:
            raise ForbiddenOperation("knowledge access requires a staff role")
        return self._policy_repository.list(document_id=document_id)

    def policy_audit(self, *, actor: ActorSummary, document_id: str | None = None, version_id: str | None = None) -> list[StoredPolicyAudit]:
        if actor.role != "merchant_admin":
            raise ForbiddenOperation("policy audit requires merchant_admin")
        if version_id is not None:
            record = self._policy_repository.get_by_id(version_id)
            if record is None:
                return []
            return self._policy_repository.audits(
                document_id=record.document_id,
                document_version=record.document_version,
            )
        if document_id is None:
            return []
        records = self._policy_repository.list(document_id=document_id)
        events: list[StoredPolicyAudit] = []
        for record in records:
            events.extend(
                self._policy_repository.audits(
                    document_id=record.document_id,
                    document_version=record.document_version,
                )
            )
        return sorted(events, key=lambda item: item.created_at, reverse=True)

    def order_for_actor(self, order_id: str, actor: ActorSummary) -> OrderSummary | None:
        if actor.role != "customer":
            return None
        order = self._order_for_customer(order_id, actor.customer_id)
        return None if order is None else order.summary

    def _order_for_customer(
        self, order_id: str, customer_id: str | None
    ) -> _AuthorizedOrder | None:
        """Prefer the configured import, then preserve the V1 local fixtures."""

        if self._commerce_repository is not None:
            imported = self._commerce_repository.order_for_customer(order_id, customer_id)
            if imported is not None:
                return _AuthorizedOrder(
                    summary=imported.summary,
                    max_refundable_cents=imported.max_refundable_cents,
                    total_cents=imported.total_cents,
                    payment_amount_cents=imported.payment_amount_cents,
                    payment_status=imported.payment_status,
                    payment_method=imported.payment_method,
                    tracking_number=imported.tracking_number,
                    shipped_at=imported.shipped_at,
                    promised_delivery_at=imported.promised_delivery_at,
                    delivered_at=imported.delivered_at,
                    created_at=imported.created_at,
                    refund_state=imported.refund_state,
                )
        record = self._orders.get(order_id)
        if record is None or record.owner_customer_id != customer_id:
            return None
        return _AuthorizedOrder(
            summary=record.summary,
            max_refundable_cents=record.max_refundable_cents,
        )

    def create_conversation(
        self, request: CreateConversationRequest, actor: ActorSummary
    ) -> ConversationSummary | None:
        if actor.role != "customer":
            raise ForbiddenOperation("customer identity required")
        if request.order_id is not None and self.order_for_actor(request.order_id, actor) is None:
            return None
        record = self._repository.create_conversation(
            owner_customer_id=actor.customer_id or "",
            channel=request.channel,
            state="AI_ACTIVE",
            order_id=request.order_id,
            created_at=MESSAGE_TIMESTAMP,
        )
        return self._customer_summary(record)

    def conversation_for_actor(
        self, conversation_id: str, actor: ActorSummary
    ) -> ConversationSummary | None:
        record = self._repository.get(conversation_id)
        if (
            record is None
            or actor.role != "customer"
            or record.owner_customer_id != actor.customer_id
        ):
            return None
        return self._customer_summary(record)

    def append_message(
        self, conversation_id: str, content: str, actor: ActorSummary
    ) -> AppendMessageResponse | None:
        record = self._repository.get(conversation_id)
        if (
            record is None
            or actor.role != "customer"
            or record.owner_customer_id != actor.customer_id
        ):
            return None
        updated = self._repository.append_message_unless_state(
            conversation_id,
            excluded_state="RESOLVED",
            author_type="customer",
            content=content,
            created_at=MESSAGE_TIMESTAMP,
        )
        if updated is None:
            raise ConversationStateConflict("resolved conversations are read-only")
        message = updated.messages[-1]
        try:
            prior_memory = self._memory_repository.select_for_context(
                actor.customer_id or "", content, limit=5
            )
        except (CustomerMemoryValidationError, SQLAlchemyError, OSError) as error:
            # Memory is optional continuity context. A database/read outage must
            # not block the authorized customer investigation or reveal details.
            log_event(
                "customer_memory_unavailable",
                error_category="optional_context_unavailable",
                error_type=type(error).__name__,
            )
            prior_memory = []
        # Raw customer text is optional, bounded, and explicitly untrusted. It
        # is persisted for continuity only; it is never an authorization source
        # and is not sent to external providers as policy evidence.
        if len(content.strip()) <= 512:
            try:
                self._memory_repository.add(
                    customer_id=actor.customer_id or "",
                    content=content,
                    provenance="customer_reported",
                    created_at=MESSAGE_TIMESTAMP,
                )
            except (
                CustomerMemoryLimitError,
                CustomerMemoryValidationError,
                SQLAlchemyError,
                OSError,
            ) as error:
                # A valid conversation message must not fail because optional
                # memory capture rejects malformed text or reaches its bound.
                log_event(
                    "customer_memory_unavailable",
                    error_category="optional_context_unavailable",
                    error_type=type(error).__name__,
                )
        memory_context = tuple(
            UntrustedCustomerMemory(content=item.content, provenance=item.provenance)
            for item in prior_memory[-5:]
        )
        investigation = run_investigation(
            content,
            model=self._investigation_model,
            facts_tool=_AuthorizedOrderFactsTool(self, actor.customer_id),
            audience="customer",
            conversation_state=updated.state,  # type: ignore[arg-type]
            order_id=updated.order_id,
            policy_retriever=self._policy_retriever,
            response_provider=self._response_provider,
            memory=memory_context,
        )
        assistant_reply = None
        if investigation.outcome == "ANSWER" and investigation.answer is not None:
            with_assistant = self._repository.append_message_if_state(
                conversation_id,
                expected_state="AI_ACTIVE",
                author_type="assistant",
                content=investigation.answer,
                created_at=MESSAGE_TIMESTAMP,
            )
            if with_assistant is None:
                current = self._repository.get(conversation_id)
                return AppendMessageResponse(
                    conversation_id=conversation_id,
                    state=(
                        updated.state
                        if current is None
                        else current.state  # type: ignore[arg-type]
                    ),
                    message=self._message(message),
                    assistant_reply=None,
                    evidence=[],
                    handoff_reason=(
                        "conversation_not_ai_active"
                        if current is not None and current.state != "AI_ACTIVE"
                        else "assistant_reply_unavailable"
                    ),
                    retrieval_mode=investigation.retrieval_mode,
                    generation_mode=investigation.generation_mode,
                    citation_ids=investigation.citation_ids,
                )
            assistant_reply = self._message(with_assistant.messages[-1])
        return AppendMessageResponse(
            conversation_id=updated.conversation_id,
            state=updated.state,
            message=self._message(message),
            assistant_reply=assistant_reply,
            evidence=[
                evidence.model_dump(mode="json") for evidence in investigation.evidence
            ],
            handoff_reason=investigation.handoff_reason,
            retrieval_mode=investigation.retrieval_mode,
            generation_mode=investigation.generation_mode,
            citation_ids=investigation.citation_ids,
        )

    def customer_memories(self, actor: ActorSummary):
        """Return only the authenticated customer's bounded memory records."""

        if actor.role != "customer" or not actor.customer_id:
            raise ForbiddenOperation("customer identity required")
        return self._memory_repository.list_for_customer(actor.customer_id)

    def handoff(
        self, conversation_id: str, actor: ActorSummary
    ) -> ConversationSummary | None:
        record = self._repository.get(conversation_id)
        if (
            record is None
            or actor.role != "customer"
            or record.owner_customer_id != actor.customer_id
        ):
            return None
        if record.state != "AI_ACTIVE":
            raise ConversationStateConflict("handoff requires AI_ACTIVE")
        updated = self._repository.transition(
            conversation_id,
            expected_state="AI_ACTIVE",
            new_state="HANDOFF_QUEUED",
        )
        if updated is None:
            raise ConversationStateConflict("handoff state changed concurrently")
        return self._customer_summary(updated)

    def support_inbox(self, actor: ActorSummary) -> SupportInboxResponse:
        if actor.role != "support_agent":
            raise ForbiddenOperation("support inbox requires support_agent")
        return SupportInboxResponse(
            conversations=[self._support_summary(record) for record in self._repository.list_support()]
        )

    def operations_summary(self, actor: ActorSummary) -> dict[str, object]:
        """Return persisted operational counts for authorized staff roles."""

        if actor.role not in {"support_agent", "refund_approver", "merchant_admin"}:
            raise ForbiddenOperation("operations summary requires a staff role")
        conversations = self._repository.list_all()
        counts = {
            "total_conversations": len(conversations),
            "active_conversations": sum(
                record.state in {"AI_ACTIVE", "HUMAN_ACTIVE"}
                for record in conversations
            ),
            "waiting_conversations": sum(
                record.state == "HANDOFF_QUEUED" for record in conversations
            ),
            "resolved_conversations": sum(
                record.state == "RESOLVED" for record in conversations
            ),
        }
        recent = sorted(
            conversations,
            key=lambda record: (
                record.messages[-1].created_at if record.messages else datetime.min.replace(tzinfo=timezone.utc),
                record.conversation_id,
            ),
            reverse=True,
        )[:20]
        activity = [
            {
                "conversation_id": record.conversation_id,
                "state": record.state,
                "order_id": record.order_id,
                "customer_id": record.owner_customer_id,
                "assigned_staff_id": record.assigned_staff_id,
                "activity_type": "message" if record.messages else "conversation_created",
                "last_activity_at": (
                    record.messages[-1].created_at if record.messages else None
                ),
            }
            for record in recent
        ]
        pending_refunds = sum(
            refund.state == "PENDING_REVIEW"
            for refund in self._refund_repository.list_all()
        )
        return {
            **counts,
            "pending_refund_reviews": pending_refunds,
            "recent_activity": activity,
        }

    def workspace_team(self, actor: ActorSummary) -> list[ActorSummary]:
        """Expose the fixed synthetic staff roster to the merchant admin only."""

        if actor.role != "merchant_admin":
            raise ForbiddenOperation("workspace team requires merchant_admin")
        return [
            self.actor_summary(SUPPORT_ACTOR_ID),
            self.actor_summary(REFUND_APPROVER_ACTOR_ID),
            self.actor_summary(MERCHANT_ADMIN_ACTOR_ID),
        ]

    def claim(
        self, conversation_id: str, actor: ActorSummary
    ) -> SupportConversationSummary | None:
        if actor.role != "support_agent":
            raise ForbiddenOperation("claim requires support_agent")
        record = self._repository.get(conversation_id)
        if record is None:
            return None
        if record.state != "HANDOFF_QUEUED":
            raise ConversationStateConflict("claim requires HANDOFF_QUEUED")
        updated = self._repository.transition(
            conversation_id,
            expected_state="HANDOFF_QUEUED",
            new_state="HUMAN_ACTIVE",
            assigned_staff_id=actor.actor_id,
        )
        if updated is None:
            raise ConversationStateConflict("conversation was already claimed")
        return self._support_summary(updated)

    def append_staff_message(
        self, conversation_id: str, content: str, actor: ActorSummary
    ) -> AppendMessageResponse | None:
        if actor.role != "support_agent":
            raise ForbiddenOperation("staff reply requires support_agent")
        record = self._repository.get(conversation_id)
        if record is None:
            return None
        if record.state != "HUMAN_ACTIVE":
            raise ConversationStateConflict("staff reply requires HUMAN_ACTIVE")
        if record.assigned_staff_id != actor.actor_id:
            raise ForbiddenOperation("conversation is assigned to another support agent")
        updated = self._repository.append_message_if_state(
            conversation_id,
            expected_state="HUMAN_ACTIVE",
            author_type="staff",
            content=content,
            created_at=MESSAGE_TIMESTAMP,
        )
        if updated is None:
            raise ConversationStateConflict("staff reply state changed concurrently")
        message = updated.messages[-1]
        return AppendMessageResponse(
            conversation_id=updated.conversation_id,
            state=updated.state,
            message=self._message(message),
            assistant_reply=None,
            evidence=[],
            handoff_reason=None,
        )

    def resolve(
        self, conversation_id: str, actor: ActorSummary
    ) -> SupportConversationSummary | None:
        if actor.role != "support_agent":
            raise ForbiddenOperation("resolve requires support_agent")
        record = self._repository.get(conversation_id)
        if record is None:
            return None
        if record.state != "HUMAN_ACTIVE":
            raise ConversationStateConflict("resolve requires HUMAN_ACTIVE")
        if record.assigned_staff_id != actor.actor_id:
            raise ForbiddenOperation("conversation is assigned to another support agent")
        updated = self._repository.transition(
            conversation_id,
            expected_state="HUMAN_ACTIVE",
            new_state="RESOLVED",
        )
        if updated is None:
            raise ConversationStateConflict("conversation state changed concurrently")
        return self._support_summary(updated)

    def create_refund(
        self,
        conversation_id: str,
        request: CreateRefundRequest,
        actor: ActorSummary,
    ) -> tuple[RefundSummary, bool] | None:
        if actor.role != "support_agent":
            raise ForbiddenOperation("refund requests require support_agent")
        record = self._repository.get(conversation_id)
        if record is None:
            return None
        if record.state != "HUMAN_ACTIVE":
            raise ConversationStateConflict("refund requests require HUMAN_ACTIVE")
        if record.assigned_staff_id != actor.actor_id:
            raise ForbiddenOperation("conversation is assigned to another support agent")
        if record.order_id is None:
            raise RefundValidationError("refund requests require a linked order")
        order = self._order_for_customer(record.order_id, record.owner_customer_id)
        if order is None:
            return None
        reason = request.reason.strip()
        idempotency_key = request.idempotency_key.strip()
        if not reason or not idempotency_key:
            raise RefundValidationError("reason and idempotency_key are required")
        refundable_limit = min(REFUNDABLE_LIMIT_CENTS, order.max_refundable_cents)
        if request.amount_cents > refundable_limit:
            raise RefundValidationError(
                f"refund amount cannot exceed {refundable_limit} cents"
            )
        existing = self._refund_repository.get_by_idempotency(
            conversation_id, idempotency_key
        )
        if existing is not None:
            if (
                existing.amount_cents != request.amount_cents
                or existing.reason != reason
                or existing.order_id != record.order_id
            ):
                raise IdempotencyConflict(
                    "idempotency_key was already used for a different refund request"
                )
            return self._refund_summary(existing), False
        stored = self._refund_repository.create(
            conversation_id=conversation_id,
            order_id=record.order_id,
            amount_cents=request.amount_cents,
            reason=reason,
            idempotency_key=idempotency_key,
            requested_by=actor.actor_id,
        )
        if stored is None:
            raise ConversationStateConflict("refund request state changed concurrently")
        if (
            stored.amount_cents != request.amount_cents
            or stored.reason != reason
            or stored.order_id != record.order_id
        ):
            raise IdempotencyConflict(
                "idempotency_key was already used for a different refund request"
            )
        return self._refund_summary(stored), True

    def list_refunds(self, actor: ActorSummary) -> RefundListResponse:
        if actor.role != "refund_approver":
            raise ForbiddenOperation("refund review requires refund_approver")
        return RefundListResponse(
            refunds=[
                self._refund_summary(refund)
                for refund in self._refund_repository.list_all()
            ]
        )

    def decide_refund(
        self,
        refund_id: str,
        *,
        actor: ActorSummary,
        decision: str,
        note: str | None,
    ) -> RefundSummary | None:
        if actor.role != "refund_approver":
            raise ForbiddenOperation("refund decision requires refund_approver")
        stored = self._refund_repository.get(refund_id)
        if stored is None:
            return None
        if stored.requested_by == actor.actor_id:
            raise ForbiddenOperation("refund approver must differ from requester")
        if stored.state != "PENDING_REVIEW":
            raise ConversationStateConflict("refund has already been decided")
        if decision not in {"approve", "reject"}:
            raise RefundValidationError("unsupported refund decision")
        clean_note = (note or "").strip()
        if not clean_note:
            clean_note = (
                "Approved for external follow-up"
                if decision == "approve"
                else "Rejected during refund review"
            )
        updated = self._refund_repository.decide(
            refund_id,
            expected_state="PENDING_REVIEW",
            new_state=(
                "APPROVED_EXTERNAL_ACTION_REQUIRED"
                if decision == "approve"
                else "REJECTED"
            ),
            decided_by=actor.actor_id,
            decision_note=clean_note,
        )
        if updated is None:
            raise ConversationStateConflict("refund state changed concurrently")
        return self._refund_summary(updated)

    @staticmethod
    def _message(message) -> Message:
        return Message(
            message_id=message.message_id,
            author_type=message.author_type,
            content=message.content,
            created_at=message.created_at,
        )

    def _customer_summary(self, record: StoredConversation) -> ConversationSummary:
        return ConversationSummary(
            conversation_id=record.conversation_id,
            channel=record.channel,
            state=record.state,
            order_id=record.order_id,
            messages=[self._message(message) for message in record.messages],
        )

    def _support_summary(self, record: StoredConversation) -> SupportConversationSummary:
        return SupportConversationSummary(
            conversation_id=record.conversation_id,
            channel=record.channel,
            state=record.state,
            order_id=record.order_id,
            customer_id=record.owner_customer_id,
            assigned_staff_id=record.assigned_staff_id,
            messages=[self._message(message) for message in record.messages],
        )

    @staticmethod
    def _refund_summary(refund: StoredRefund) -> RefundSummary:
        return RefundSummary(
            refund_id=refund.refund_id,
            conversation_id=refund.conversation_id,
            order_id=refund.order_id,
            amount_cents=refund.amount_cents,
            reason=refund.reason,
            state=refund.state,
            requested_by=refund.requested_by,
            decided_by=refund.decided_by,
            decision_note=refund.decision_note,
        )
