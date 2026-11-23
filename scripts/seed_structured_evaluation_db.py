"""Seed the disposable PostgreSQL database used by M16-DB evaluation.

The command refuses a database that already contains commerce orders. It is
intentionally limited to an empty local evaluation database and never loads
operational or external customer data.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine, func, select

from backend.app.commerce.models import (
    commerce_addresses,
    commerce_customers,
    commerce_demo_identities,
    commerce_order_statuses,
    commerce_orders,
    commerce_payment_methods,
    commerce_payments,
    commerce_refund_scenarios,
    commerce_shipments,
    commerce_shipping_methods,
    commerce_support_cases,
    create_commerce_schema,
)


def seed(database_url: str) -> None:
    if "resolveai_m16db" not in database_url:
        raise RuntimeError("refusing to seed a database not named resolveai_m16db")
    engine = create_engine(database_url, future=True)
    create_commerce_schema(engine)
    with engine.begin() as connection:
        existing = connection.execute(
            select(func.count()).select_from(commerce_orders)
        ).scalar_one()
        if existing:
            raise RuntimeError("refusing to seed a non-empty structured evaluation database")
        connection.execute(
            commerce_order_statuses.insert(),
            [
                {"source_order_status_id": 1, "status_name": "pending", "description": "Awaiting fulfillment"},
                {"source_order_status_id": 2, "status_name": "shipped", "description": "Accepted by carrier"},
                {"source_order_status_id": 3, "status_name": "delivered", "description": "Delivered"},
                {"source_order_status_id": 4, "status_name": "cancelled", "description": "Cancelled"},
            ],
        )
        connection.execute(
            commerce_payment_methods.insert(),
            [{"source_payment_method_id": 1, "name": "card"}],
        )
        connection.execute(
            commerce_shipping_methods.insert(),
            [{
                "source_shipping_method_id": 1,
                "name": "standard",
                "carrier": "Synthetic Carrier",
                "base_cost": Decimal("5.00"),
                "estimated_days": 5,
            }],
        )
        connection.execute(
            commerce_customers.insert(),
            [
                {"source_user_id": 5001, "public_customer_id": "eval_customer_001", "email": "eval001@example.test", "display_name": "Evaluation Customer 1", "created_at": datetime(2025, 12, 1)},
                {"source_user_id": 5002, "public_customer_id": "eval_customer_002", "email": "eval002@example.test", "display_name": "Evaluation Customer 2", "created_at": datetime(2025, 12, 2)},
            ],
        )
        connection.execute(
            commerce_addresses.insert(),
            [
                {"source_address_id": 6001, "source_user_id": 5001, "street_address": "1 Evaluation Way", "extended_address": None, "city": "Synthetic City", "state_province": "EX", "postal_code": "00001", "country_code": "US", "is_default_billing": True, "is_default_shipping": True},
                {"source_address_id": 6002, "source_user_id": 5002, "street_address": "2 Evaluation Way", "extended_address": None, "city": "Synthetic City", "state_province": "EX", "postal_code": "00002", "country_code": "US", "is_default_billing": True, "is_default_shipping": True},
            ],
        )
        connection.execute(
            commerce_orders.insert(),
            [
                {"source_order_id": 7001, "public_order_id": "eval_order_001", "source_user_id": 5001, "source_billing_address_id": 6001, "source_shipping_address_id": 6001, "source_order_status_id": 2, "source_shipping_method_id": 1, "source_coupon_id": None, "created_at": datetime(2025, 12, 20), "subtotal": Decimal("80.00"), "discount_amount": Decimal("0.00"), "tax_amount": Decimal("1.00"), "shipping_cost": Decimal("5.00"), "total": Decimal("86.00")},
                {"source_order_id": 7002, "public_order_id": "eval_order_002", "source_user_id": 5001, "source_billing_address_id": 6001, "source_shipping_address_id": 6001, "source_order_status_id": 3, "source_shipping_method_id": 1, "source_coupon_id": None, "created_at": datetime(2025, 12, 21), "subtotal": Decimal("115.00"), "discount_amount": Decimal("0.00"), "tax_amount": Decimal("5.00"), "shipping_cost": Decimal("5.00"), "total": Decimal("125.00")},
                {"source_order_id": 7003, "public_order_id": "eval_order_003", "source_user_id": 5002, "source_billing_address_id": 6002, "source_shipping_address_id": 6002, "source_order_status_id": 1, "source_shipping_method_id": 1, "source_coupon_id": None, "created_at": datetime(2025, 12, 22), "subtotal": Decimal("49.99"), "discount_amount": Decimal("0.00"), "tax_amount": Decimal("0.00"), "shipping_cost": Decimal("0.00"), "total": Decimal("49.99")},
                {"source_order_id": 7004, "public_order_id": "eval_order_004", "source_user_id": 5002, "source_billing_address_id": 6002, "source_shipping_address_id": 6002, "source_order_status_id": 4, "source_shipping_method_id": 1, "source_coupon_id": None, "created_at": datetime(2025, 12, 23), "subtotal": Decimal("19.99"), "discount_amount": Decimal("0.00"), "tax_amount": Decimal("0.00"), "shipping_cost": Decimal("0.00"), "total": Decimal("19.99")},
            ],
        )
        connection.execute(
            commerce_payments.insert(),
            [
                {"source_payment_id": 8001, "source_order_id": 7001, "source_payment_method_id": 1, "amount": Decimal("86.00"), "status": "completed", "processed_at": datetime(2025, 12, 20), "transaction_reference": "eval-payment-001"},
                {"source_payment_id": 8002, "source_order_id": 7002, "source_payment_method_id": 1, "amount": Decimal("125.00"), "status": "completed", "processed_at": datetime(2025, 12, 21), "transaction_reference": "eval-payment-002"},
            ],
        )
        connection.execute(
            commerce_shipments.insert(),
            [
                {"source_shipment_id": 9001, "source_order_id": 7001, "tracking_number": "TRK-EVAL-001", "shipped_at": datetime(2026, 1, 2, 9), "promised_delivery_at": datetime(2026, 1, 8), "delivered_at": datetime(2026, 1, 9)},
                {"source_shipment_id": 9002, "source_order_id": 7002, "tracking_number": "TRK-EVAL-002", "shipped_at": datetime(2025, 12, 28, 9), "promised_delivery_at": datetime(2026, 1, 5), "delivered_at": datetime(2026, 1, 4, 14, 30)},
            ],
        )
        connection.execute(
            commerce_demo_identities.insert(),
            [
                {"actor_id": "customer_001", "source_user_id": 5001},
                {"actor_id": "customer_002", "source_user_id": 5002},
            ],
        )
        connection.execute(
            commerce_support_cases.insert(),
            [{
                "case_id": "eval-case-delayed-001",
                "source_user_id": 5001,
                "source_order_id": 7001,
                "scenario_type": "delayed_delivery",
                "status": "HUMAN_ACTIVE",
                "permitted_outcome": "HUMAN_ESCALATION",
                "opened_at": datetime(2026, 1, 3),
                "closed_at": None,
                "provenance": "resolveai_m16db_evaluation",
            }, {
                "case_id": "eval-case-refund-002",
                "source_user_id": 5001,
                "source_order_id": 7002,
                "scenario_type": "refund_status",
                "status": "RESOLVED",
                "permitted_outcome": "REFUND_REVIEW_ONLY",
                "opened_at": datetime(2026, 1, 3),
                "closed_at": datetime(2026, 1, 4),
                "provenance": "resolveai_m16db_evaluation",
            }],
        )
        connection.execute(
            commerce_refund_scenarios.insert(),
            [{
                "refund_scenario_id": "eval-refund-001",
                "case_id": "eval-case-delayed-001",
                "source_order_id": 7001,
                "amount_cents": 8600,
                "state": "PENDING_REVIEW",
                "idempotency_key": "eval-refund-key-001",
                "provenance": "resolveai_m16db_evaluation",
            }, {
                "refund_scenario_id": "eval-refund-002",
                "case_id": "eval-case-refund-002",
                "source_order_id": 7002,
                "amount_cents": 12500,
                "state": "APPROVED_EXTERNAL_ACTION_REQUIRED",
                "idempotency_key": "eval-refund-key-002",
                "provenance": "resolveai_m16db_evaluation",
            }],
        )
    print("seeded 4 orders, 2 payments, 2 shipments, and 2 authorized demo identities")


if __name__ == "__main__":
    url = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not url:
        raise SystemExit("RESOLVEAI_TEST_POSTGRES_URL is required")
    seed(url)
