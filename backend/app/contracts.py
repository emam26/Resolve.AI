"""Pydantic models for the first ResolveAI API handshake.

These models deliberately have no web-framework or database dependency. They
freeze the JSON contract before the FastAPI and persistence layers are added.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ActorRole = Literal["customer", "support_agent", "refund_approver", "merchant_admin"]
OrderStatus = Literal["processing", "in_transit", "delayed", "delivered", "cancelled"]
PaymentStatus = Literal["pending", "paid", "failed"]
ShipmentStatus = Literal["not_shipped", "in_transit", "delayed", "delivered"]
ConversationChannel = Literal["widget"]
ConversationState = Literal["AI_ACTIVE", "HANDOFF_QUEUED", "HUMAN_ACTIVE", "RESOLVED"]
MessageAuthorType = Literal["customer", "assistant", "staff"]
RefundState = Literal[
    "PENDING_REVIEW",
    "APPROVED_EXTERNAL_ACTION_REQUIRED",
    "REJECTED",
]


class ContractModel(BaseModel):
    """Base model with stable JSON serialization and no extra fields."""

    model_config = ConfigDict(extra="forbid")


class DemoLoginRequest(ContractModel):
    demo_actor_id: str = Field(min_length=1)


class ActorSummary(ContractModel):
    actor_id: str
    display_name: str
    role: ActorRole
    customer_id: str | None
    permissions: list[str]


class DemoLoginResponse(ContractModel):
    session_id: str
    actor: ActorSummary


class Message(ContractModel):
    message_id: str
    author_type: MessageAuthorType
    content: str = Field(min_length=1)
    created_at: datetime


class CreateConversationRequest(ContractModel):
    channel: ConversationChannel
    order_id: str | None


class ConversationSummary(ContractModel):
    conversation_id: str
    channel: ConversationChannel
    state: ConversationState
    order_id: str | None
    messages: list[Message]


class SupportConversationSummary(ContractModel):
    """Staff view adds ownership and assignment without changing the widget shape."""

    conversation_id: str
    channel: ConversationChannel
    state: ConversationState
    order_id: str | None
    customer_id: str
    assigned_staff_id: str | None
    messages: list[Message]


class SupportInboxResponse(ContractModel):
    conversations: list[SupportConversationSummary]


class CreateRefundRequest(ContractModel):
    amount_cents: int = Field(gt=0)
    reason: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class RefundSummary(ContractModel):
    refund_id: str
    conversation_id: str
    order_id: str
    amount_cents: int
    reason: str
    state: RefundState
    requested_by: str
    decided_by: str | None
    decision_note: str | None


class RefundListResponse(ContractModel):
    refunds: list[RefundSummary]


class AppendMessageRequest(ContractModel):
    content: str = Field(min_length=1)


class AppendMessageResponse(ContractModel):
    conversation_id: str
    state: ConversationState
    message: Message
    assistant_reply: Message | None
    evidence: list[dict[str, object]]
    handoff_reason: str | None


class OrderSummary(ContractModel):
    order_id: str
    status: OrderStatus
    payment_status: PaymentStatus
    shipment_status: ShipmentStatus
    estimated_delivery_date: date | None


class ErrorBody(ContractModel):
    code: str
    message: str
    details: dict[str, object]


class ErrorResponse(ContractModel):
    error: ErrorBody
