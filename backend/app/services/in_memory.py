"""Synthetic domain services with local SQLAlchemy conversation persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from backend.app.ai.answer import PolicyRetriever
from backend.app.ai.investigation import (
    InvestigationModel,
    ModelDecision,
    OrderFacts,
    run_investigation,
)
from backend.app.ai.generation import PolicyAnswerProvider
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
from backend.app.db import ConversationRepository, RefundRepository, StoredConversation, StoredRefund


class _DemoInvestigationModel:
    """Deterministic local classifier used until a model SDK is authorized."""

    def classify(self, query: str) -> ModelDecision:
        normalized = query.casefold()
        if "refund" in normalized:
            return ModelDecision(intent="refund_request")
        if any(
            phrase in normalized
            for phrase in (
                "where is",
                "order status",
                "track my",
                "tracking",
                "delivery status",
                "shipment status",
            )
        ):
            return ModelDecision(intent="order_status")
        # Policy retrieval is the safe default for non-transactional
        # questions.  The grounded-answer layer hands off when evidence is
        # insufficient rather than inventing a response.
        return ModelDecision(intent="policy_question")


class _AuthorizedOrderFactsTool:
    """Typed order-facts boundary scoped to the authenticated customer."""

    def __init__(self, service: "InMemoryResolveService", customer_id: str | None) -> None:
        self._service = service
        self._customer_id = customer_id

    def get_order_facts(self, order_id: str) -> OrderFacts | None:
        record = self._service._orders.get(order_id)
        if record is None or record.owner_customer_id != self._customer_id:
            return None
        summary = record.summary
        return OrderFacts(
            order_id=summary.order_id,
            status=summary.status,
            shipment_status=summary.shipment_status,
            estimated_delivery=(
                None
                if summary.estimated_delivery_date is None
                else summary.estimated_delivery_date.isoformat()
            ),
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


class InMemoryResolveService:
    """Per-application synthetic data with configurable conversation storage."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        policy_retriever: PolicyRetriever | None = None,
        response_provider: PolicyAnswerProvider | None = None,
        investigation_model: InvestigationModel | None = None,
    ) -> None:
        self._sessions: dict[str, str] = {}
        self._policy_retriever = policy_retriever
        self._response_provider = response_provider
        self._investigation_model = investigation_model or _DemoInvestigationModel()
        configured_database_url = database_url or "sqlite+pysqlite:///:memory:"
        self._repository = ConversationRepository(configured_database_url)
        self._refund_repository = RefundRepository(configured_database_url)
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
        self._sessions[session_id] = demo_actor_id
        return DemoLoginResponse(
            session_id=session_id,
            actor=self.actor_summary(demo_actor_id),
        )

    def actor_for_session(self, session_id: str | None) -> ActorSummary | None:
        actor_id = None if session_id is None else self._sessions.get(session_id)
        if actor_id is None:
            return None
        return self.actor_summary(actor_id)

    def order_for_actor(self, order_id: str, actor: ActorSummary) -> OrderSummary | None:
        record = self._orders.get(order_id)
        if record is None or record.owner_customer_id != actor.customer_id:
            return None
        return record.summary

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
        if record.state == "RESOLVED":
            raise ConversationStateConflict("resolved conversations are read-only")
        updated = self._repository.append_message(
            conversation_id,
            author_type="customer",
            content=content,
            created_at=MESSAGE_TIMESTAMP,
        )
        if updated is None:
            return None
        message = updated.messages[-1]
        investigation = run_investigation(
            content,
            model=self._investigation_model,
            facts_tool=_AuthorizedOrderFactsTool(self, actor.customer_id),
            audience="customer",
            conversation_state=updated.state,  # type: ignore[arg-type]
            order_id=updated.order_id,
            policy_retriever=self._policy_retriever,
            response_provider=self._response_provider,
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
        updated = self._repository.append_message(
            conversation_id,
            author_type="staff",
            content=content,
            created_at=MESSAGE_TIMESTAMP,
        )
        if updated is None:
            return None
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
        order = self._orders.get(record.order_id)
        if order is None or order.owner_customer_id != record.owner_customer_id:
            return None
        reason = request.reason.strip()
        idempotency_key = request.idempotency_key.strip()
        if not reason or not idempotency_key:
            raise RefundValidationError("reason and idempotency_key are required")
        if request.amount_cents > REFUNDABLE_LIMIT_CENTS:
            raise RefundValidationError(
                f"refund amount cannot exceed {REFUNDABLE_LIMIT_CENTS} cents"
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
