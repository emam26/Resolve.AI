"""Narrow, authorization-aware read boundary for imported commerce records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Engine, and_, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.contracts import OrderSummary

from .models import (
    commerce_demo_identities,
    commerce_order_statuses,
    commerce_orders,
    commerce_payments,
    commerce_shipments,
    commerce_support_cases,
)
from .scenarios import SCENARIO_CLOCK


@dataclass(frozen=True)
class CommerceOrder:
    """Stable domain projection used by existing order and refund services."""

    summary: OrderSummary
    max_refundable_cents: int
    source_order_id: int


class CommerceRepository:
    """Read imported records only after a server-established identity mapping."""

    def __init__(self, database_url: str, *, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(database_url, future=True)
        self._owns_engine = engine is None

    def order_for_customer(
        self, public_order_id: str, customer_id: str | None
    ) -> CommerceOrder | None:
        if not public_order_id.strip() or not customer_id:
            return None
        active_case = commerce_support_cases.alias("active_case")
        statement = (
            select(
                commerce_orders.c.source_order_id,
                commerce_orders.c.public_order_id,
                commerce_orders.c.total,
                commerce_order_statuses.c.status_name.label("order_status_name"),
                commerce_payments.c.status.label("payment_status_name"),
                commerce_shipments.c.shipped_at,
                commerce_shipments.c.promised_delivery_at,
                commerce_shipments.c.delivered_at,
                active_case.c.scenario_type.label("active_scenario_type"),
            )
            .select_from(
                commerce_demo_identities.join(
                    commerce_orders,
                    commerce_orders.c.source_user_id
                    == commerce_demo_identities.c.source_user_id,
                )
                .join(
                    commerce_order_statuses,
                    commerce_order_statuses.c.source_order_status_id
                    == commerce_orders.c.source_order_status_id,
                )
                .outerjoin(
                    commerce_payments,
                    commerce_payments.c.source_order_id
                    == commerce_orders.c.source_order_id,
                )
                .outerjoin(
                    commerce_shipments,
                    commerce_shipments.c.source_order_id
                    == commerce_orders.c.source_order_id,
                )
                .outerjoin(
                    active_case,
                    and_(
                        active_case.c.source_order_id
                        == commerce_orders.c.source_order_id,
                        active_case.c.status.in_(("HANDOFF_QUEUED", "HUMAN_ACTIVE")),
                    ),
                )
            )
            .where(
                commerce_demo_identities.c.actor_id == customer_id,
                commerce_orders.c.public_order_id == public_order_id,
            )
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return None if row is None else _commerce_order_from_row(row)

    def database_ready(self) -> bool:
        """Return whether the imported-commerce database accepts a query."""

        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    def close(self) -> None:
        if self._owns_engine:
            self._engine.dispose()


def _commerce_order_from_row(row) -> CommerceOrder:
    active_delay = row["active_scenario_type"] == "delayed_delivery"
    order_status = "delayed" if active_delay else _order_status(row["order_status_name"])
    shipment_status = _shipment_status(row, active_delay=active_delay)
    promised_delivery = row["promised_delivery_at"]
    summary = OrderSummary(
        order_id=row["public_order_id"],
        status=order_status,  # type: ignore[arg-type]
        payment_status=_payment_status(row["payment_status_name"]),  # type: ignore[arg-type]
        shipment_status=shipment_status,  # type: ignore[arg-type]
        estimated_delivery_date=(
            None if promised_delivery is None else _as_date(promised_delivery)
        ),
    )
    total_cents = _money_to_cents(row["total"])
    max_refundable_cents = (
        total_cents if row["payment_status_name"] == "completed" else 0
    )
    return CommerceOrder(
        summary=summary,
        max_refundable_cents=max_refundable_cents,
        source_order_id=int(row["source_order_id"]),
    )


def _order_status(source_status: str) -> str:
    return {
        "pending": "processing",
        "paid": "processing",
        "shipped": "in_transit",
        "delivered": "delivered",
        "cancelled": "cancelled",
    }.get(source_status, "processing")


def _payment_status(source_status: str | None) -> str:
    return {
        "completed": "paid",
        "failed": "failed",
    }.get(source_status or "", "pending")


def _shipment_status(row, *, active_delay: bool) -> str:
    if row["shipped_at"] is None:
        return "not_shipped"
    if active_delay:
        return "delayed"
    delivered_at = row["delivered_at"]
    if delivered_at is not None and delivered_at <= SCENARIO_CLOCK:
        return "delivered"
    return "in_transit"


def _as_date(value) -> date:
    return value.date() if hasattr(value, "date") else value


def _money_to_cents(value) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


__all__ = ["CommerceOrder", "CommerceRepository"]
