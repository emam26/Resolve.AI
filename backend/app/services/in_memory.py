"""Deterministic synthetic services for the first API milestone."""

from dataclasses import dataclass
from datetime import date, datetime, timezone

from backend.app.contracts import (
    ActorSummary,
    AppendMessageResponse,
    ConversationSummary,
    CreateConversationRequest,
    DemoLoginResponse,
    Message,
    OrderSummary,
)


DEMO_ACTOR_ID = "customer_001"
DEMO_SESSION_ID = "demo-session-customer_001"
MESSAGE_TIMESTAMP = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _OrderRecord:
    owner_customer_id: str
    summary: OrderSummary


@dataclass
class _ConversationRecord:
    owner_customer_id: str
    summary: ConversationSummary


class InMemoryResolveService:
    """A per-application synthetic store with no persistence or I/O."""

    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}
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
        self._conversations: dict[str, _ConversationRecord] = {}
        foreign_summary = ConversationSummary(
            conversation_id="conv_foreign_001",
            channel="widget",
            state="AI_ACTIVE",
            order_id="order_1002",
            messages=[],
        )
        self._conversations[foreign_summary.conversation_id] = _ConversationRecord(
            owner_customer_id="customer_002",
            summary=foreign_summary,
        )
        self._next_conversation_number = 1001
        self._next_message_number = 1001

    @staticmethod
    def actor_summary() -> ActorSummary:
        return ActorSummary(
            actor_id=DEMO_ACTOR_ID,
            display_name="Demo Customer",
            role="customer",
            customer_id=DEMO_ACTOR_ID,
            permissions=["orders:read:self"],
        )

    def demo_login(self, demo_actor_id: str) -> DemoLoginResponse | None:
        if demo_actor_id != DEMO_ACTOR_ID:
            return None
        self._sessions[DEMO_SESSION_ID] = DEMO_ACTOR_ID
        return DemoLoginResponse(session_id=DEMO_SESSION_ID, actor=self.actor_summary())

    def actor_for_session(self, session_id: str | None) -> ActorSummary | None:
        if session_id is None or self._sessions.get(session_id) != DEMO_ACTOR_ID:
            return None
        return self.actor_summary()

    def order_for_actor(self, order_id: str, actor: ActorSummary) -> OrderSummary | None:
        record = self._orders.get(order_id)
        if record is None or record.owner_customer_id != actor.customer_id:
            return None
        return record.summary

    def create_conversation(
        self, request: CreateConversationRequest, actor: ActorSummary
    ) -> ConversationSummary | None:
        if request.order_id is not None and self.order_for_actor(request.order_id, actor) is None:
            return None

        conversation_id = f"conv_{self._next_conversation_number}"
        self._next_conversation_number += 1
        summary = ConversationSummary(
            conversation_id=conversation_id,
            channel=request.channel,
            state="AI_ACTIVE",
            order_id=request.order_id,
            messages=[],
        )
        self._conversations[conversation_id] = _ConversationRecord(
            owner_customer_id=actor.customer_id or "",
            summary=summary,
        )
        return summary

    def conversation_for_actor(
        self, conversation_id: str, actor: ActorSummary
    ) -> ConversationSummary | None:
        record = self._conversations.get(conversation_id)
        if record is None or record.owner_customer_id != actor.customer_id:
            return None
        return record.summary

    def append_message(
        self, conversation_id: str, content: str, actor: ActorSummary
    ) -> AppendMessageResponse | None:
        record = self._conversations.get(conversation_id)
        if record is None or record.owner_customer_id != actor.customer_id:
            return None

        message = Message(
            message_id=f"msg_{self._next_message_number}",
            author_type="customer",
            content=content,
            created_at=MESSAGE_TIMESTAMP,
        )
        self._next_message_number += 1
        record.summary.messages.append(message)
        return AppendMessageResponse(
            conversation_id=record.summary.conversation_id,
            state=record.summary.state,
            message=message,
            assistant_reply=None,
            evidence=[],
            handoff_reason=None,
        )
