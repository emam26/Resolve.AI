from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.app.api import create_app
from backend.app.commerce.models import (
    commerce_addresses,
    commerce_brands,
    commerce_categories,
    commerce_customers,
    commerce_demo_identities,
    commerce_order_statuses,
    commerce_orders,
    commerce_payment_methods,
    commerce_payments,
    commerce_products,
    commerce_shipments,
    commerce_shipping_methods,
    commerce_support_cases,
    create_commerce_schema,
)
from backend.app.commerce.repository import CommerceRepository


def _repository_with_imported_order() -> CommerceRepository:
    # TestClient serves requests on another thread.  Keep the SQLite fixture
    # on one shared in-memory connection so the injected repository sees the
    # schema and records created by this helper.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_commerce_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            commerce_brands.insert(), [{"source_brand_id": 1, "name": "Sample brand"}]
        )
        connection.execute(
            commerce_categories.insert(),
            [{"source_category_id": 1, "name": "Sample category"}],
        )
        connection.execute(
            commerce_order_statuses.insert(),
            [{"source_order_status_id": 1, "status_name": "shipped", "description": "With carrier"}],
        )
        connection.execute(
            commerce_payment_methods.insert(),
            [{"source_payment_method_id": 1, "name": "credit_card"}],
        )
        connection.execute(
            commerce_shipping_methods.insert(),
            [{
                "source_shipping_method_id": 1,
                "name": "standard",
                "carrier": "UPS",
                "base_cost": Decimal("5.00"),
                "estimated_days": 4,
            }],
        )
        connection.execute(
            commerce_customers.insert(),
            [
                {
                    "source_user_id": 7001,
                    "public_customer_id": "fixture_customer_7001",
                    "email": "mapped@example.test",
                    "display_name": "Mapped Customer",
                    "created_at": datetime(2025, 12, 31),
                },
                {
                    "source_user_id": 7002,
                    "public_customer_id": "fixture_customer_7002",
                    "email": "foreign@example.test",
                    "display_name": "Foreign Customer",
                    "created_at": datetime(2025, 12, 30),
                },
            ],
        )
        connection.execute(
            commerce_addresses.insert(),
            [
                {
                    "source_address_id": 8001,
                    "source_user_id": 7001,
                    "street_address": "1 Sample Street",
                    "extended_address": None,
                    "city": "Example City",
                    "state_province": "EX",
                    "postal_code": "00000",
                    "country_code": "US",
                    "is_default_billing": True,
                    "is_default_shipping": True,
                },
                {
                    "source_address_id": 8002,
                    "source_user_id": 7002,
                    "street_address": "2 Sample Street",
                    "extended_address": None,
                    "city": "Example City",
                    "state_province": "EX",
                    "postal_code": "00001",
                    "country_code": "US",
                    "is_default_billing": True,
                    "is_default_shipping": True,
                },
            ],
        )
        connection.execute(
            commerce_products.insert(),
            [{
                "source_product_id": 1,
                "source_brand_id": 1,
                "source_category_id": 1,
                "name": "Sample product",
                "sku": "sample-sku",
                "price": Decimal("75.00"),
                "is_active": True,
            }],
        )
        connection.execute(
            commerce_orders.insert(),
            [
                {
                    "source_order_id": 70001,
                    "public_order_id": "fixture_order_70001",
                    "source_user_id": 7001,
                    "source_billing_address_id": 8001,
                    "source_shipping_address_id": 8001,
                    "source_order_status_id": 1,
                    "source_shipping_method_id": 1,
                    "source_coupon_id": None,
                    "created_at": datetime(2025, 12, 31),
                    "subtotal": Decimal("75.00"),
                    "discount_amount": Decimal("0.00"),
                    "tax_amount": Decimal("6.00"),
                    "shipping_cost": Decimal("5.00"),
                    "total": Decimal("86.00"),
                },
                {
                    "source_order_id": 70002,
                    "public_order_id": "fixture_order_70002",
                    "source_user_id": 7002,
                    "source_billing_address_id": 8002,
                    "source_shipping_address_id": 8002,
                    "source_order_status_id": 1,
                    "source_shipping_method_id": 1,
                    "source_coupon_id": None,
                    "created_at": datetime(2025, 12, 30),
                    "subtotal": Decimal("75.00"),
                    "discount_amount": Decimal("0.00"),
                    "tax_amount": Decimal("6.00"),
                    "shipping_cost": Decimal("5.00"),
                    "total": Decimal("86.00"),
                },
            ],
        )
        connection.execute(
            commerce_payments.insert(),
            [{
                "source_payment_id": 9001,
                "source_order_id": 70001,
                "source_payment_method_id": 1,
                "amount": Decimal("86.00"),
                "status": "completed",
                "processed_at": datetime(2026, 1, 1),
                "transaction_reference": "sample-payment-1",
            }],
        )
        connection.execute(
            commerce_shipments.insert(),
            [{
                "source_shipment_id": 9101,
                "source_order_id": 70001,
                "tracking_number": "sample-tracking-1",
                "shipped_at": datetime(2026, 1, 2),
                "promised_delivery_at": datetime(2026, 1, 8),
                "delivered_at": datetime(2026, 1, 9),
            }],
        )
        connection.execute(
            commerce_demo_identities.insert(),
            [{"actor_id": "customer_001", "source_user_id": 7001}],
        )
        connection.execute(
            commerce_support_cases.insert(),
            [{
                "case_id": "case-delayed-delivery-001",
                "source_user_id": 7001,
                "source_order_id": 70001,
                "scenario_type": "delayed_delivery",
                "status": "HANDOFF_QUEUED",
                "permitted_outcome": "HUMAN_ESCALATION",
                "opened_at": datetime(2026, 1, 3),
                "closed_at": None,
                "provenance": "test",
            }],
        )
    return CommerceRepository("sqlite+pysqlite:///:memory:", engine=engine)


def _login(client: TestClient, actor_id: str) -> str:
    response = client.post("/api/v1/auth/demo-login", json={"demo_actor_id": actor_id})
    assert response.status_code == 200
    return response.json()["session_id"]


def test_repository_maps_only_authorized_imported_orders() -> None:
    repository = _repository_with_imported_order()

    owned = repository.order_for_customer("fixture_order_70001", "customer_001")

    assert owned is not None
    assert owned.summary.status == "delayed"
    assert owned.summary.payment_status == "paid"
    assert owned.summary.shipment_status == "delayed"
    assert owned.max_refundable_cents == 8600
    assert repository.order_for_customer("fixture_order_70002", "customer_001") is None


def test_existing_api_workflow_uses_imported_order_without_weakening_refund_guards() -> None:
    repository = _repository_with_imported_order()
    client = TestClient(create_app(commerce_repository=repository))
    customer_headers = {"Authorization": f"Bearer {_login(client, 'customer_001')}"}

    owned = client.get("/api/v1/orders/fixture_order_70001", headers=customer_headers)
    foreign = client.get("/api/v1/orders/fixture_order_70002", headers=customer_headers)
    conversation = client.post(
        "/api/v1/conversations",
        headers=customer_headers,
        json={"channel": "widget", "order_id": "fixture_order_70001"},
    )

    assert owned.status_code == 200
    assert owned.json()["shipment_status"] == "delayed"
    assert foreign.status_code == 404
    assert conversation.status_code == 201
    conversation_id = conversation.json()["conversation_id"]
    investigation = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_headers,
        json={"content": "Where is my order?"},
    )
    assert investigation.status_code == 201
    assert "fixture_order_70001 is delayed" in investigation.json()["assistant_reply"]["content"]

    assert client.post(
        f"/api/v1/conversations/{conversation_id}/handoff", headers=customer_headers
    ).status_code == 200
    support_headers = {"Authorization": f"Bearer {_login(client, 'support_001')}"}
    assert client.post(
        f"/api/v1/support/conversations/{conversation_id}/claim", headers=support_headers
    ).status_code == 200
    refund = client.post(
        f"/api/v1/support/conversations/{conversation_id}/refunds",
        headers=support_headers,
        json={
            "amount_cents": 100,
            "reason": "Imported-order test review",
            "idempotency_key": "imported-order-review-1",
        },
    )
    assert refund.status_code == 201
    refund_id = refund.json()["refund_id"]
    approver_headers = {"Authorization": f"Bearer {_login(client, 'refund_approver_001')}"}
    approval = client.post(f"/api/v1/refunds/{refund_id}/approve", headers=approver_headers)
    assert approval.status_code == 200
    assert approval.json()["state"] == "APPROVED_EXTERNAL_ACTION_REQUIRED"
