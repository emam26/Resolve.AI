"""Deterministic import of the official ecommerce sample subset.

The source database is treated as read-only.  A single transaction replaces
only ResolveAI-owned ``commerce_*`` rows when the verified source archive or
selection changes; an identical completed import is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import Engine, create_engine, select, text

from .models import (
    commerce_addresses,
    commerce_brands,
    commerce_categories,
    commerce_customers,
    commerce_demo_identities,
    commerce_imports,
    commerce_order_items,
    commerce_order_statuses,
    commerce_orders,
    commerce_payment_methods,
    commerce_payments,
    commerce_products,
    commerce_refund_scenarios,
    commerce_return_reasons,
    commerce_returns,
    commerce_shipment_events,
    commerce_shipments,
    commerce_shipping_methods,
    commerce_source_support_messages,
    commerce_source_support_tickets,
    commerce_support_case_messages,
    commerce_support_cases,
)
from .scenarios import (
    DEMO_ACTOR_ID,
    DEMO_SOURCE_USER_ID,
    SCENARIO_CLOCK,
    SCENARIO_PROVENANCE,
    SOURCE_TICKET_PROVENANCE,
    SUPPORT_SCENARIO_BLUEPRINTS,
)


SOURCE_NAME = "ecommerce-sample-database-v2-100k-postgresql"
SOURCE_ARCHIVE_SHA256 = "8CE7F80D9A67C0664CCCB1A8211BB9CFA76E0192F636464E42542257B4BB408B"
SELECTION_MAX_ORDER_ID = 3620
EXPECTED_ORDER_ITEM_COUNT = 10_000
IMPORT_VERSION = "m11a-v1"


@dataclass(frozen=True)
class CommerceImportConfig:
    """Inputs required to reproduce one imported operational subset."""

    source_database_url: str
    target_database_url: str
    source_archive_path: Path
    selection_max_order_id: int = SELECTION_MAX_ORDER_ID


@dataclass(frozen=True)
class CommerceImportResult:
    import_key: str
    reused: bool
    row_counts: dict[str, int]


def verify_source_archive(path: Path) -> str:
    """Verify the official archive before trusting its staged database copy."""

    if not path.is_file():
        raise FileNotFoundError(f"source archive not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest().upper()
    if actual != SOURCE_ARCHIVE_SHA256:
        raise ValueError(
            "source archive checksum mismatch: "
            f"expected {SOURCE_ARCHIVE_SHA256}, received {actual}"
        )
    return actual


def import_subset(config: CommerceImportConfig) -> CommerceImportResult:
    """Import the selected source cohort into pre-migrated commerce tables."""

    if config.selection_max_order_id != SELECTION_MAX_ORDER_ID:
        raise ValueError(
            "M11A is pinned to the verified deterministic selection "
            f"orders.id <= {SELECTION_MAX_ORDER_ID}"
        )
    source_checksum = verify_source_archive(config.source_archive_path)
    source_engine = create_engine(config.source_database_url, future=True)
    target_engine = create_engine(config.target_database_url, future=True)
    try:
        payload = _read_and_validate_source(source_engine, config.selection_max_order_id)
        manifest_checksum = transformation_manifest_sha256(payload["scenarios"])
        import_key = _import_key(
            source_checksum, config.selection_max_order_id, manifest_checksum
        )
        row_counts = _row_counts(payload)
        with target_engine.begin() as target_connection:
            existing = target_connection.execute(
                select(commerce_imports.c.import_key, commerce_imports.c.row_counts_json)
                .where(commerce_imports.c.import_key == import_key)
            ).mappings().first()
            if existing is not None and _target_counts_match(target_connection, row_counts):
                return CommerceImportResult(
                    import_key=import_key,
                    reused=True,
                    row_counts=row_counts,
                )
            _clear_owned_rows(target_connection)
            _insert_payload(target_connection, payload)
            target_connection.execute(
                commerce_imports.insert().values(
                    import_key=import_key,
                    source_name=SOURCE_NAME,
                    source_archive_sha256=source_checksum,
                    transformation_manifest_sha256=manifest_checksum,
                    selection_max_order_id=config.selection_max_order_id,
                    scenario_clock=SCENARIO_CLOCK,
                    row_counts_json=json.dumps(row_counts, sort_keys=True),
                    completed_at=datetime.utcnow(),
                )
            )
            if not _target_counts_match(target_connection, row_counts):
                raise RuntimeError("commerce import count validation failed")
        return CommerceImportResult(import_key=import_key, reused=False, row_counts=row_counts)
    finally:
        source_engine.dispose()
        target_engine.dispose()


def import_from_environment() -> CommerceImportResult:
    """CLI-friendly import configured by explicit local-only environment URLs."""

    source_database_url = os.getenv("RESOLVEAI_DATASET_SOURCE_DATABASE_URL")
    target_database_url = os.getenv("RESOLVEAI_DATABASE_URL")
    archive = os.getenv("RESOLVEAI_DATASET_SOURCE_ARCHIVE")
    if not source_database_url or not target_database_url or not archive:
        raise RuntimeError(
            "RESOLVEAI_DATASET_SOURCE_DATABASE_URL, RESOLVEAI_DATABASE_URL, and "
            "RESOLVEAI_DATASET_SOURCE_ARCHIVE are required"
        )
    if not target_database_url.startswith(("postgresql", "postgres")):
        raise RuntimeError("RESOLVEAI_DATABASE_URL must be PostgreSQL for M11A import")
    return import_subset(
        CommerceImportConfig(
            source_database_url=source_database_url,
            target_database_url=target_database_url,
            source_archive_path=Path(archive),
        )
    )


def _read_and_validate_source(
    source_engine: Engine, selection_max_order_id: int
) -> dict[str, list[dict[str, Any]]]:
    params = {"max_order_id": selection_max_order_id}
    with source_engine.connect() as source_connection:
        query = lambda sql: [dict(row) for row in source_connection.execute(text(sql), params).mappings()]
        payload: dict[str, list[dict[str, Any]]] = {
            "customers": query(
                """
                SELECT DISTINCT u.id AS source_user_id, u.email,
                       concat(u.first_name, ' ', u.last_name) AS display_name,
                       u.created_at
                FROM users u JOIN orders o ON o.user_id = u.id
                WHERE o.id <= :max_order_id ORDER BY u.id
                """
            ),
            "addresses": query(
                """
                SELECT DISTINCT a.id AS source_address_id, a.user_id AS source_user_id,
                       a.street_address, a.extended_address, a.city, a.state_province,
                       a.postal_code, c.code AS country_code, a.is_default_billing,
                       a.is_default_shipping
                FROM addresses a
                JOIN countries c ON c.id = a.country_id
                JOIN orders o ON a.id IN (o.billing_address_id, o.shipping_address_id)
                WHERE o.id <= :max_order_id ORDER BY a.id
                """
            ),
            "brands": query(
                """
                SELECT DISTINCT b.id AS source_brand_id, b.name
                FROM brands b JOIN products p ON p.brand_id = b.id
                JOIN order_items oi ON oi.product_id = p.id
                WHERE oi.order_id <= :max_order_id ORDER BY b.id
                """
            ),
            "categories": query(
                """
                SELECT DISTINCT c.id AS source_category_id, c.name
                FROM categories c JOIN products p ON p.category_id = c.id
                JOIN order_items oi ON oi.product_id = p.id
                WHERE oi.order_id <= :max_order_id ORDER BY c.id
                """
            ),
            "products": query(
                """
                SELECT DISTINCT p.id AS source_product_id, p.brand_id AS source_brand_id,
                       p.category_id AS source_category_id, p.name, p.sku, p.price,
                       p.is_active
                FROM products p JOIN order_items oi ON oi.product_id = p.id
                WHERE oi.order_id <= :max_order_id ORDER BY p.id
                """
            ),
            "order_statuses": query(
                """
                SELECT DISTINCT os.id AS source_order_status_id, os.status_name, os.description
                FROM order_statuses os JOIN orders o ON o.order_status_id = os.id
                WHERE o.id <= :max_order_id ORDER BY os.id
                """
            ),
            "shipping_methods": query(
                """
                SELECT DISTINCT sm.id AS source_shipping_method_id, sm.name, sm.carrier,
                       sm.base_cost, sm.estimated_days
                FROM shipping_methods sm JOIN orders o ON o.shipping_method_id = sm.id
                WHERE o.id <= :max_order_id ORDER BY sm.id
                """
            ),
            "orders": query(
                """
                SELECT o.id AS source_order_id, o.user_id AS source_user_id,
                       o.billing_address_id AS source_billing_address_id,
                       o.shipping_address_id AS source_shipping_address_id,
                       o.order_status_id AS source_order_status_id,
                       o.shipping_method_id AS source_shipping_method_id,
                       o.coupon_id AS source_coupon_id, o.created_at, o.subtotal,
                       o.discount_amount, o.tax_amount, o.shipping_cost, o.total
                FROM orders o WHERE o.id <= :max_order_id ORDER BY o.id
                """
            ),
            "order_items": query(
                """
                SELECT oi.id AS source_order_item_id, oi.order_id AS source_order_id,
                       oi.product_id AS source_product_id, oi.quantity, oi.unit_price,
                       oi.discount_amount, oi.tax_amount
                FROM order_items oi WHERE oi.order_id <= :max_order_id ORDER BY oi.id
                """
            ),
            "payment_methods": query(
                """
                SELECT DISTINCT pm.id AS source_payment_method_id, pm.name
                FROM payment_methods pm JOIN payments p ON p.payment_method_id = pm.id
                WHERE p.order_id <= :max_order_id ORDER BY pm.id
                """
            ),
            "payments": query(
                """
                SELECT p.id AS source_payment_id, p.order_id AS source_order_id,
                       p.payment_method_id AS source_payment_method_id, p.amount, p.status,
                       p.processed_at, p.transaction_reference
                FROM payments p WHERE p.order_id <= :max_order_id ORDER BY p.id
                """
            ),
            "shipments": query(
                """
                SELECT s.id AS source_shipment_id, s.order_id AS source_order_id,
                       s.tracking_number, s.shipped_at, s.delivered_at,
                       sm.estimated_days
                FROM shipments s
                JOIN orders o ON o.id = s.order_id
                JOIN shipping_methods sm ON sm.id = o.shipping_method_id
                WHERE s.order_id <= :max_order_id ORDER BY s.id
                """
            ),
            "return_reasons": query(
                """
                SELECT DISTINCT rr.id AS source_return_reason_id, rr.reason_text
                FROM return_reasons rr JOIN order_returns r ON r.reason_id = rr.id
                JOIN order_items oi ON oi.id = r.order_item_id
                WHERE oi.order_id <= :max_order_id ORDER BY rr.id
                """
            ),
            "returns": query(
                """
                SELECT r.id AS source_return_id, r.order_item_id AS source_order_item_id,
                       r.reason_id AS source_return_reason_id, r.status, r.requested_at,
                       r.processed_at, r.quantity
                FROM order_returns r JOIN order_items oi ON oi.id = r.order_item_id
                WHERE oi.order_id <= :max_order_id ORDER BY r.id
                """
            ),
            "source_tickets": query(
                """
                SELECT st.id AS source_ticket_id, st.user_id AS source_user_id, st.subject,
                       st.priority, st.status, st.created_at
                FROM support_tickets st
                WHERE EXISTS (
                    SELECT 1 FROM orders o
                    WHERE o.id <= :max_order_id AND o.user_id = st.user_id
                )
                ORDER BY st.id
                """
            ),
            "source_messages": query(
                """
                SELECT sm.id AS source_message_id, sm.ticket_id AS source_ticket_id,
                       sm.sender_type, sm.message, sm.sent_at
                FROM support_messages sm
                JOIN support_tickets st ON st.id = sm.ticket_id
                WHERE EXISTS (
                    SELECT 1 FROM orders o
                    WHERE o.id <= :max_order_id AND o.user_id = st.user_id
                )
                ORDER BY sm.id
                """
            ),
        }
    payload["scenarios"] = _build_scenario_payload(payload)
    _validate_payload(payload, selection_max_order_id)
    return payload


def _build_scenario_payload(
    payload: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    orders = {int(row["source_order_id"]): row for row in payload["orders"]}
    shipments = {int(row["source_order_id"]): row for row in payload["shipments"]}
    cases: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    refunds: list[dict[str, Any]] = []
    for blueprint in SUPPORT_SCENARIO_BLUEPRINTS:
        order = orders.get(blueprint.source_order_id)
        if order is None:
            raise ValueError(f"scenario order {blueprint.source_order_id} is not imported")
        shipment = shipments.get(blueprint.source_order_id)
        opened_at = (
            SCENARIO_CLOCK - timedelta(hours=4)
            if blueprint.active_at_scenario_clock
            else _historical_case_time(order, shipment)
        )
        closed_at = None if blueprint.status != "RESOLVED" else opened_at + timedelta(hours=2)
        cases.append(
            {
                "case_id": blueprint.case_id,
                "source_user_id": order["source_user_id"],
                "source_order_id": blueprint.source_order_id,
                "scenario_type": blueprint.scenario_type,
                "status": blueprint.status,
                "permitted_outcome": blueprint.permitted_outcome,
                "opened_at": opened_at,
                "closed_at": closed_at,
                "provenance": SCENARIO_PROVENANCE,
            }
        )
        messages.extend(
            (
                _case_message(blueprint.case_id, 1, "customer", blueprint.customer_message, opened_at),
                _case_message(
                    blueprint.case_id,
                    2,
                    "staff",
                    blueprint.support_message,
                    opened_at + timedelta(minutes=20),
                ),
            )
        )
        if shipment is not None:
            events.extend(_shipment_events(blueprint, shipment))
        if blueprint.refund_state is not None:
            amount_cents = min(_money_to_cents(order["total"]), 2_500)
            if amount_cents <= 0:
                raise ValueError(f"scenario order {blueprint.source_order_id} has no refundable amount")
            refunds.append(
                {
                    "refund_scenario_id": f"refund-{blueprint.case_id}",
                    "case_id": blueprint.case_id,
                    "source_order_id": blueprint.source_order_id,
                    "amount_cents": amount_cents,
                    "state": blueprint.refund_state,
                    "idempotency_key": f"m11a-{blueprint.case_id}",
                    "provenance": SCENARIO_PROVENANCE,
                }
            )
    return {"cases": cases, "messages": messages, "events": events, "refunds": refunds}


def _historical_case_time(
    order: Mapping[str, Any], shipment: Mapping[str, Any] | None
) -> datetime:
    if shipment is not None:
        return shipment["delivered_at"] + timedelta(days=1)
    return order["created_at"] + timedelta(days=2)


def _case_message(
    case_id: str, sequence_number: int, author_type: str, content: str, created_at: datetime
) -> dict[str, Any]:
    return {
        "case_message_id": f"{case_id}-message-{sequence_number}",
        "case_id": case_id,
        "sequence_number": sequence_number,
        "author_type": author_type,
        "content": content,
        "created_at": created_at,
        "provenance": SCENARIO_PROVENANCE,
    }


def _shipment_events(
    blueprint, shipment: Mapping[str, Any]
) -> list[dict[str, Any]]:
    shipped_at = shipment["shipped_at"]
    delivered_at = shipment["delivered_at"]
    midpoint = shipped_at + (delivered_at - shipped_at) / 2
    event_specs: list[tuple[str, str, datetime]] = [
        ("SHIPMENT_CREATED", "Shipment record created for the imported order.", shipped_at),
        ("CARRIER_ACCEPTED", "Carrier accepted the shipment.", shipped_at + timedelta(hours=1)),
        ("IN_TRANSIT", "Shipment is moving through the carrier network.", midpoint),
    ]
    if blueprint.scenario_type == "delayed_delivery":
        exception_at = min(delivered_at - timedelta(hours=6), SCENARIO_CLOCK - timedelta(hours=1))
        event_specs.append(
            ("DELIVERY_EXCEPTION", "Carrier delay recorded for the active support scenario.", exception_at)
        )
    if not blueprint.active_at_scenario_clock:
        event_specs.extend(
            (
                ("OUT_FOR_DELIVERY", "Shipment is out for delivery.", delivered_at - timedelta(hours=2)),
                ("DELIVERED", "Carrier recorded delivery.", delivered_at),
            )
        )
    events: list[dict[str, Any]] = []
    for number, (event_type, detail, occurred_at) in enumerate(
        sorted(event_specs, key=lambda event: event[2]), start=1
    ):
        events.append(
            {
                "event_id": f"{blueprint.case_id}-shipment-event-{number}",
                "source_shipment_id": shipment["source_shipment_id"],
                "event_type": event_type,
                "detail": detail,
                "occurred_at": occurred_at,
                "provenance": SCENARIO_PROVENANCE,
            }
        )
    return events


def _validate_payload(payload: Mapping[str, Sequence[Mapping[str, Any]]], max_order_id: int) -> None:
    orders = payload["orders"]
    items = payload["order_items"]
    if max_order_id != SELECTION_MAX_ORDER_ID or len(items) != EXPECTED_ORDER_ITEM_COUNT:
        raise ValueError(
            "selected source cohort must contain exactly "
            f"{EXPECTED_ORDER_ITEM_COUNT} order items; received {len(items)}"
        )
    order_by_id = {int(order["source_order_id"]): order for order in orders}
    customer_ids = {int(customer["source_user_id"]) for customer in payload["customers"]}
    if DEMO_SOURCE_USER_ID not in customer_ids:
        raise ValueError("configured demo source customer is not in the selected cohort")
    items_by_order: dict[int, list[Mapping[str, Any]]] = {}
    for item in items:
        items_by_order.setdefault(int(item["source_order_id"]), []).append(item)
    for order_id, order in order_by_id.items():
        order_items = items_by_order.get(order_id, [])
        subtotal = sum(
            (Decimal(str(item["unit_price"])) * int(item["quantity"]) for item in order_items),
            Decimal("0"),
        )
        line_discount = sum(
            (Decimal(str(item["discount_amount"])) for item in order_items), Decimal("0")
        )
        tax = sum((Decimal(str(item["tax_amount"])) for item in order_items), Decimal("0"))
        order_discount = Decimal(str(order["discount_amount"]))
        expected_total = subtotal - order_discount + tax + Decimal(str(order["shipping_cost"]))
        if _money_difference(subtotal, Decimal(str(order["subtotal"]))) > Decimal("0.01"):
            raise ValueError(f"order {order_id} subtotal does not match its lines")
        # The official source represents coupon discounts at the order level;
        # line discounts are independent per-line adjustments and must not be
        # aggregated as the coupon amount.
        if order_discount < 0 or order_discount > subtotal:
            raise ValueError(f"order {order_id} has an invalid coupon discount")
        if line_discount < 0 or any(
            Decimal(str(item["discount_amount"]))
            > Decimal(str(item["unit_price"])) * int(item["quantity"])
            for item in order_items
        ):
            raise ValueError(f"order {order_id} has an invalid line discount")
        if _money_difference(tax, Decimal(str(order["tax_amount"]))) > Decimal("0.01"):
            raise ValueError(f"order {order_id} tax does not match its lines")
        if _money_difference(expected_total, Decimal(str(order["total"]))) > Decimal("0.01"):
            raise ValueError(f"order {order_id} total does not match its lines")
    for payment in payload["payments"]:
        order = order_by_id[int(payment["source_order_id"])]
        if _money_difference(Decimal(str(payment["amount"])), Decimal(str(order["total"]))) > Decimal("0.01"):
            raise ValueError(f"payment {payment['source_payment_id']} does not match its order")
    item_by_id = {int(item["source_order_item_id"]): item for item in items}
    for shipment in payload["shipments"]:
        if shipment["shipped_at"] > shipment["delivered_at"]:
            raise ValueError(f"shipment {shipment['source_shipment_id']} has invalid chronology")
    for return_row in payload["returns"]:
        item = item_by_id[int(return_row["source_order_item_id"])]
        if int(return_row["quantity"]) > int(item["quantity"]):
            raise ValueError(f"return {return_row['source_return_id']} exceeds its order line")
    for scenario in payload["scenarios"]["cases"]:  # type: ignore[index]
        order = order_by_id[int(scenario["source_order_id"])]
        if int(order["source_user_id"]) != int(scenario["source_user_id"]):
            raise ValueError(f"scenario {scenario['case_id']} has an unrelated customer/order")


def _insert_payload(target_connection, payload: Mapping[str, Any]) -> None:
    target_connection.execute(commerce_brands.insert(), payload["brands"])
    target_connection.execute(commerce_categories.insert(), payload["categories"])
    target_connection.execute(commerce_order_statuses.insert(), payload["order_statuses"])
    target_connection.execute(commerce_payment_methods.insert(), payload["payment_methods"])
    target_connection.execute(commerce_shipping_methods.insert(), payload["shipping_methods"])
    target_connection.execute(commerce_return_reasons.insert(), payload["return_reasons"])
    customers = [
        {
            **customer,
            "public_customer_id": f"commerce_customer_{customer['source_user_id']}",
        }
        for customer in payload["customers"]
    ]
    target_connection.execute(commerce_customers.insert(), customers)
    target_connection.execute(commerce_addresses.insert(), payload["addresses"])
    target_connection.execute(commerce_products.insert(), payload["products"])
    orders = [
        {**order, "public_order_id": f"commerce_order_{order['source_order_id']}"}
        for order in payload["orders"]
    ]
    target_connection.execute(commerce_orders.insert(), orders)
    target_connection.execute(commerce_order_items.insert(), payload["order_items"])
    target_connection.execute(commerce_payments.insert(), payload["payments"])
    shipments = [
        {
            key: value
            for key, value in shipment.items()
            if key != "estimated_days"
        }
        | {
            "promised_delivery_at": shipment["shipped_at"]
            + timedelta(days=int(shipment["estimated_days"]))
        }
        for shipment in payload["shipments"]
    ]
    target_connection.execute(commerce_shipments.insert(), shipments)
    target_connection.execute(commerce_returns.insert(), payload["returns"])
    target_connection.execute(
        commerce_source_support_tickets.insert(),
        [{**ticket, "provenance": SOURCE_TICKET_PROVENANCE} for ticket in payload["source_tickets"]],
    )
    target_connection.execute(
        commerce_source_support_messages.insert(),
        [{**message, "provenance": SOURCE_TICKET_PROVENANCE} for message in payload["source_messages"]],
    )
    target_connection.execute(
        commerce_demo_identities.insert(),
        [{"actor_id": DEMO_ACTOR_ID, "source_user_id": DEMO_SOURCE_USER_ID}],
    )
    scenarios = payload["scenarios"]
    target_connection.execute(commerce_support_cases.insert(), scenarios["cases"])
    target_connection.execute(commerce_support_case_messages.insert(), scenarios["messages"])
    target_connection.execute(commerce_shipment_events.insert(), scenarios["events"])
    target_connection.execute(commerce_refund_scenarios.insert(), scenarios["refunds"])


def _clear_owned_rows(target_connection) -> None:
    for table in (
        commerce_imports,
        commerce_refund_scenarios,
        commerce_shipment_events,
        commerce_support_case_messages,
        commerce_support_cases,
        commerce_demo_identities,
        commerce_source_support_messages,
        commerce_source_support_tickets,
        commerce_returns,
        commerce_shipments,
        commerce_payments,
        commerce_order_items,
        commerce_orders,
        commerce_products,
        commerce_addresses,
        commerce_customers,
        commerce_return_reasons,
        commerce_shipping_methods,
        commerce_payment_methods,
        commerce_order_statuses,
        commerce_categories,
        commerce_brands,
    ):
        target_connection.execute(table.delete())


def _row_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    return {
        "addresses": len(payload["addresses"]),
        "customers": len(payload["customers"]),
        "order_items": len(payload["order_items"]),
        "orders": len(payload["orders"]),
        "payments": len(payload["payments"]),
        "products": len(payload["products"]),
        "returns": len(payload["returns"]),
        "shipments": len(payload["shipments"]),
        "source_support_messages": len(payload["source_messages"]),
        "source_support_tickets": len(payload["source_tickets"]),
        "support_cases": len(payload["scenarios"]["cases"]),
        "support_case_messages": len(payload["scenarios"]["messages"]),
        "shipment_events": len(payload["scenarios"]["events"]),
        "refund_scenarios": len(payload["scenarios"]["refunds"]),
    }


def _target_counts_match(target_connection, row_counts: Mapping[str, int]) -> bool:
    table_by_key = {
        "addresses": commerce_addresses,
        "customers": commerce_customers,
        "order_items": commerce_order_items,
        "orders": commerce_orders,
        "payments": commerce_payments,
        "products": commerce_products,
        "returns": commerce_returns,
        "shipments": commerce_shipments,
        "source_support_messages": commerce_source_support_messages,
        "source_support_tickets": commerce_source_support_tickets,
        "support_cases": commerce_support_cases,
        "support_case_messages": commerce_support_case_messages,
        "shipment_events": commerce_shipment_events,
        "refund_scenarios": commerce_refund_scenarios,
    }
    for key, table in table_by_key.items():
        actual = target_connection.execute(select(text("count(*)")).select_from(table)).scalar_one()
        if int(actual) != row_counts[key]:
            return False
    return True


def _money_difference(left: Decimal, right: Decimal) -> Decimal:
    return abs(left.quantize(Decimal("0.01")) - right.quantize(Decimal("0.01")))


def _money_to_cents(value: Any) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def transformation_manifest_sha256(
    scenarios: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> str:
    """Fingerprint generated scenario output, not just source rows or counts."""

    manifest = {
        "import_version": IMPORT_VERSION,
        "scenario_clock": SCENARIO_CLOCK.isoformat(),
        "demo_actor_id": DEMO_ACTOR_ID,
        "demo_source_user_id": DEMO_SOURCE_USER_ID,
        "scenario_provenance": SCENARIO_PROVENANCE,
        "source_ticket_provenance": SOURCE_TICKET_PROVENANCE,
        "support_scenarios": [asdict(blueprint) for blueprint in SUPPORT_SCENARIO_BLUEPRINTS],
        "generated_scenarios": _json_manifest_value(scenarios or {}),
    }
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _json_manifest_value(value: Any) -> Any:
    """Serialize generated rows deterministically, including their timestamps."""

    if isinstance(value, Mapping):
        return {str(key): _json_manifest_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_manifest_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _import_key(
    source_checksum: str, selection_max_order_id: int, manifest_checksum: str
) -> str:
    return (
        f"{IMPORT_VERSION}:{source_checksum.lower()}:{manifest_checksum.lower()}:"
        f"orders<={selection_max_order_id}"
    )


if __name__ == "__main__":
    result = import_from_environment()
    print(
        json.dumps(
            {
                "import_key": result.import_key,
                "reused": result.reused,
                "row_counts": result.row_counts,
            },
            sort_keys=True,
        )
    )


__all__ = [
    "CommerceImportConfig",
    "CommerceImportResult",
    "EXPECTED_ORDER_ITEM_COUNT",
    "SELECTION_MAX_ORDER_ID",
    "SOURCE_ARCHIVE_SHA256",
    "SOURCE_NAME",
    "import_from_environment",
    "import_subset",
    "transformation_manifest_sha256",
    "verify_source_archive",
]
