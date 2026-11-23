from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.commerce.repository import CommerceRepository
from backend.app.rag.models import PolicyEvidence


class _PublishedPolicyRetriever:
    def retrieve_published_policy(self, query: str, audience: str = "customer", top_k: int = 3):
        return [
            PolicyEvidence(
                document_id="returns-policy",
                document_version="v1",
                section="Return window",
                release_id="eval-release",
                visibility="public",
                score=0.95,
                text="Published policy: returns are reviewed within 30 days after delivery.",
                status="published",
                is_active=True,
            )
        ]


def _database_url() -> str:
    value = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("set RESOLVEAI_TEST_POSTGRES_URL for structured PostgreSQL checks")
    return value


def _login(client: TestClient, actor_id: str) -> str:
    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": actor_id}
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def test_structured_projection_is_exact_and_owner_scoped_in_postgres() -> None:
    repository = CommerceRepository(_database_url())

    owned = repository.order_for_customer("eval_order_001", "customer_001")
    foreign = repository.order_for_customer("eval_order_001", "customer_002")
    incomplete = repository.order_for_customer("eval_order_003", "customer_002")

    assert owned is not None
    assert owned.total_cents == 8600
    assert owned.payment_amount_cents == 8600
    assert owned.payment_status == "completed"
    assert owned.payment_method == "card"
    assert owned.tracking_number == "TRK-EVAL-001"
    assert owned.promised_delivery_at.isoformat() == "2026-01-08T00:00:00"
    assert owned.refund_state == "PENDING_REVIEW"
    assert foreign is None
    assert incomplete is not None
    assert incomplete.total_cents == 4999
    assert incomplete.payment_amount_cents is None
    assert incomplete.payment_status is None
    assert incomplete.tracking_number is None


def test_customer_api_uses_postgres_facts_for_exact_payment_answer() -> None:
    repository = CommerceRepository(_database_url())
    client = TestClient(create_app(commerce_repository=repository))
    headers = {"Authorization": f"Bearer {_login(client, 'customer_001')}"}

    conversation = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"channel": "widget", "order_id": "eval_order_001"},
    )
    assert conversation.status_code == 201
    message = client.post(
        f"/api/v1/conversations/{conversation.json()['conversation_id']}/messages",
        headers=headers,
        json={"content": "What exact amount is recorded for payment?"},
    )

    assert message.status_code == 201
    body = message.json()
    assert body["assistant_reply"]["content"] == (
        "The total for order eval_order_001 is $86.00. "
        "Recorded payment: $86.00. Payment status: paid. Payment method: card."
    )
    assert body["evidence"] == []
    assert body["handoff_reason"] is None


def test_customer_api_hands_off_missing_postgres_fields_and_composes_policy() -> None:
    repository = CommerceRepository(_database_url())
    client = TestClient(
        create_app(
            commerce_repository=repository,
            policy_retriever=_PublishedPolicyRetriever(),
        )
    )
    owner_headers = {"Authorization": f"Bearer {_login(client, 'customer_001')}"}
    assert client.get("/api/v1/orders/eval_order_003", headers=owner_headers).status_code == 404
    combined_conversation = client.post(
        "/api/v1/conversations",
        headers=owner_headers,
        json={"channel": "widget", "order_id": "eval_order_001"},
    )
    combined_message = client.post(
        f"/api/v1/conversations/{combined_conversation.json()['conversation_id']}/messages",
        headers=owner_headers,
        json={
            "content": "According to the published policy, is this delayed order eligible for a return?"
        },
    )
    assert combined_message.status_code == 201
    combined_body = combined_message.json()
    assert "eval_order_001 is delayed" in combined_body["assistant_reply"]["content"]
    assert combined_body["retrieval_mode"] == "semantic"
    assert combined_body["evidence"][0]["document_id"] == "returns-policy"
