"""Opt-in integration checks against the isolated M11A source and target DBs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text

from backend.app.api import create_app
from backend.app.commerce.repository import CommerceRepository
from backend.app.commerce import importer as commerce_importer
from backend.app.commerce.evaluation import validate_evaluation_cases
from backend.app.commerce.importer import CommerceImportConfig, import_subset
from backend.app.commerce.models import (
    commerce_imports,
    commerce_order_items,
    commerce_orders,
    commerce_payments,
    commerce_refund_scenarios,
    commerce_returns,
    commerce_shipments,
    commerce_support_cases,
)


def _integration_config() -> CommerceImportConfig:
    source_url = os.getenv("RESOLVEAI_TEST_COMMERCE_SOURCE_URL")
    target_url = os.getenv("RESOLVEAI_TEST_COMMERCE_TARGET_URL")
    archive = os.getenv("RESOLVEAI_TEST_COMMERCE_SOURCE_ARCHIVE")
    if not source_url or not target_url or not archive:
        pytest.skip("M11A source, target, and archive integration inputs are not configured")
    return CommerceImportConfig(source_url, target_url, Path(archive))


def _scalar(connection, statement) -> int:
    return int(connection.execute(statement).scalar_one())


def test_postgres_import_is_consistent_repeatable_and_rollback_safe(monkeypatch) -> None:
    config = _integration_config()
    target = create_engine(config.target_database_url, future=True)
    try:
        first = import_subset(config)
        assert first.row_counts == {
            "addresses": 4402,
            "customers": 2512,
            "order_items": 10_000,
            "orders": 3620,
            "payments": 3523,
            "products": 400,
            "refund_scenarios": 3,
            "returns": 212,
            "shipment_events": 49,
            "shipments": 3435,
            "source_support_messages": 1630,
            "source_support_tickets": 486,
            "support_case_messages": 20,
            "support_cases": 10,
        }
        repeated = import_subset(config)
        assert repeated.reused is True
        with target.connect() as connection:
            assert _scalar(connection, select(func.count()).select_from(commerce_orders)) == 3620
            assert _scalar(connection, select(func.count()).select_from(commerce_order_items)) == 10_000
            assert _scalar(connection, select(func.count()).select_from(commerce_payments)) == 3523
            assert _scalar(connection, select(func.count()).select_from(commerce_shipments)) == 3435
            assert _scalar(connection, select(func.count()).select_from(commerce_returns)) == 212
            assert _scalar(connection, select(func.count()).select_from(commerce_support_cases)) == 10
            assert _scalar(connection, select(func.count()).select_from(commerce_refund_scenarios)) == 3
            stored_manifest = connection.execute(
                select(commerce_imports.c.transformation_manifest_sha256)
            ).scalar_one()
            assert stored_manifest == first.import_key.split(":")[2].upper()
            assert _scalar(
                connection,
                text(
                    "SELECT count(*) FROM commerce_orders o "
                    "LEFT JOIN commerce_customers c ON c.source_user_id = o.source_user_id "
                    "WHERE c.source_user_id IS NULL"
                ),
            ) == 0
            assert _scalar(
                connection,
                text(
                    "SELECT count(*) FROM commerce_order_items oi "
                    "LEFT JOIN commerce_orders o ON o.source_order_id = oi.source_order_id "
                    "WHERE o.source_order_id IS NULL"
                ),
            ) == 0
            assert _scalar(
                connection,
                text(
                    "SELECT count(*) FROM commerce_orders "
                    "WHERE abs((subtotal - discount_amount + tax_amount + shipping_cost) - total) > 0.01"
                ),
            ) == 0
            assert _scalar(
                connection,
                text(
                    "SELECT count(*) FROM commerce_payments p JOIN commerce_orders o "
                    "ON o.source_order_id = p.source_order_id WHERE abs(p.amount - o.total) > 0.01"
                ),
            ) == 0
            assert _scalar(
                connection,
                text("SELECT count(*) FROM commerce_shipments WHERE shipped_at > delivered_at"),
            ) == 0
            assert _scalar(
                connection,
                text(
                    "SELECT count(*) FROM commerce_returns r JOIN commerce_order_items oi "
                    "ON oi.source_order_item_id = r.source_order_item_id WHERE r.quantity > oi.quantity"
                ),
            ) == 0
            assert _scalar(
                connection,
                text(
                    "SELECT count(*) FROM commerce_support_cases sc JOIN commerce_orders o "
                    "ON o.source_order_id = sc.source_order_id "
                    "WHERE sc.source_user_id <> o.source_user_id"
                ),
            ) == 0
            assert _scalar(
                connection,
                text(
                    "SELECT count(*) FROM commerce_refund_scenarios rs JOIN commerce_orders o "
                    "ON o.source_order_id = rs.source_order_id WHERE rs.amount_cents > round(o.total * 100)"
                ),
            ) == 0
        validate_evaluation_cases(target)

        # This uses the normal HTTP routes and the migrated PostgreSQL rows,
        # not a direct SQL projection or an in-memory order fixture.
        client = TestClient(
            create_app(
                config.target_database_url,
                commerce_repository=CommerceRepository(config.target_database_url),
            )
        )
        login = client.post("/api/v1/auth/demo-login", json={"demo_actor_id": "customer_001"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['session_id']}"}
        owned = client.get("/api/v1/orders/commerce_order_92", headers=headers)
        foreign = client.get("/api/v1/orders/commerce_order_1877", headers=headers)
        assert owned.status_code == 200
        assert owned.json()["status"] == "delayed"
        assert owned.json()["shipment_status"] == "delayed"
        assert foreign.status_code == 404
        conversation = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"channel": "widget", "order_id": "commerce_order_92"},
        )
        assert conversation.status_code == 201
        investigation = client.post(
            f"/api/v1/conversations/{conversation.json()['conversation_id']}/messages",
            headers=headers,
            json={"content": "Where is my order?"},
        )
        assert investigation.status_code == 201
        assert "commerce_order_92 is delayed" in investigation.json()["assistant_reply"]["content"]

        # A generated-row change, even with identical aggregate counts, must
        # produce a new manifest and replace the owned dataset rather than
        # incorrectly returning the prior import as reusable.
        original_builder = commerce_importer._build_scenario_payload

        def revised_scenarios(payload):
            scenarios = original_builder(payload)
            scenarios["cases"][0]["scenario_type"] = "delayed_delivery_revised"
            return scenarios

        monkeypatch.setattr(commerce_importer, "_build_scenario_payload", revised_scenarios)
        changed = import_subset(config)
        assert changed.reused is False
        assert changed.import_key != first.import_key
        with target.connect() as connection:
            assert connection.execute(
                select(commerce_support_cases.c.scenario_type).where(
                    commerce_support_cases.c.case_id == "case-delayed-delivery-001"
                )
            ).scalar_one() == "delayed_delivery_revised"
        monkeypatch.undo()
        restored_original = import_subset(config)
        assert restored_original.reused is False
        assert import_subset(config).reused is True

        # A failing replacement must roll back, leaving the previous owned
        # dataset intact.  Removing only the completion row forces the import
        # path without altering the established records.
        with target.begin() as connection:
            connection.execute(commerce_imports.delete())
        with target.connect() as connection:
            before_failure = connection.execute(
                select(func.count()).select_from(commerce_order_items)
            ).scalar_one()

        def fail_after_clear(*_args, **_kwargs):
            raise RuntimeError("forced import insertion failure")

        monkeypatch.setattr(commerce_importer, "_insert_payload", fail_after_clear)
        with pytest.raises(RuntimeError, match="forced import insertion failure"):
            import_subset(config)
        with target.connect() as connection:
            assert _scalar(connection, select(func.count()).select_from(commerce_order_items)) == before_failure

        monkeypatch.undo()
        restored = import_subset(config)
        assert restored.reused is False
        assert import_subset(config).reused is True
    finally:
        target.dispose()
