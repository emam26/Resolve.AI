from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api import create_app


def _login(client: TestClient, actor_id: str) -> str:
    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": actor_id}
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def test_synthetic_v1_customer_to_human_to_refund_review_flow() -> None:
    client = TestClient(create_app())
    customer = _login(client, "customer_001")
    customer_headers = {"Authorization": f"Bearer {customer}"}

    conversation = client.post(
        "/api/v1/conversations",
        headers=customer_headers,
        json={"channel": "widget", "order_id": "order_1001"},
    )
    assert conversation.status_code == 201
    conversation_id = conversation.json()["conversation_id"]

    message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_headers,
        json={"content": "Please have a support agent review this order."},
    )
    assert message.status_code == 201
    assert message.json()["assistant_reply"] is None

    handoff = client.post(
        f"/api/v1/conversations/{conversation_id}/handoff",
        headers=customer_headers,
    )
    assert handoff.status_code == 200
    assert handoff.json()["state"] == "HANDOFF_QUEUED"

    support = _login(client, "support_001")
    support_headers = {"Authorization": f"Bearer {support}"}
    claim = client.post(
        f"/api/v1/support/conversations/{conversation_id}/claim",
        headers=support_headers,
    )
    assert claim.status_code == 200
    assert claim.json()["state"] == "HUMAN_ACTIVE"

    refund = client.post(
        f"/api/v1/support/conversations/{conversation_id}/refunds",
        headers=support_headers,
        json={
            "amount_cents": 2500,
            "reason": "Synthetic delay review",
            "idempotency_key": "integration-refund-1",
        },
    )
    assert refund.status_code == 201
    refund_id = refund.json()["refund_id"]
    assert refund.json()["state"] == "PENDING_REVIEW"

    approver = _login(client, "refund_approver_001")
    decision = client.post(
        f"/api/v1/refunds/{refund_id}/approve",
        headers={"Authorization": f"Bearer {approver}"},
        json={"note": "Approved for external follow-up only."},
    )
    assert decision.status_code == 200
    assert decision.json()["state"] == "APPROVED_EXTERNAL_ACTION_REQUIRED"
    assert "REFUNDED" not in decision.text
