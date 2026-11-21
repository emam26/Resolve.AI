"""Pydantic models for the first ResolveAI API handshake.

These models deliberately have no web-framework or database dependency. They
freeze the JSON contract before the FastAPI and persistence layers are added.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ActorRole = Literal["customer", "support_agent", "refund_approver", "merchant_admin"]
OrderStatus = Literal["processing", "in_transit", "delayed", "delivered", "cancelled"]
PaymentStatus = Literal["pending", "paid", "failed"]
ShipmentStatus = Literal["not_shipped", "in_transit", "delayed", "delivered"]


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
