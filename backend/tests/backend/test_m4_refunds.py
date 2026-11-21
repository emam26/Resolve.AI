from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.contracts import ActorSummary
from backend.app.services.in_memory import (
    ForbiddenOperation,
    REFUND_APPROVER_ACTOR_ID,
)


def _login(client: TestClient, actor_id: str) -> str:
    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": actor_id}
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def _human_active_conversation(client: TestClient) -> tuple[str, str, str]:
    customer = _login(client, "customer_001")
    support = _login(client, "support_001")
    customer_headers = {"Authorization": f"Bearer {customer}"}
    support_headers = {"Authorization": f"Bearer {support}"}
    created = client.post(
        "/api/v1/conversations",
        headers=customer_headers,
        json={"channel": "widget", "order_id": "order_1001"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["conversation_id"]
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/handoff",
        headers=customer_headers,
    ).status_code == 200
    assert client.post(
        f"/api/v1/support/conversations/{conversation_id}/claim",
        headers=support_headers,
    ).status_code == 200
    return conversation_id, customer, support


def _refund_request(client: TestClient, conversation_id: str, support: str, **overrides):
    payload = {
        "amount_cents": 2500,
        "reason": "Delay compensation",
        "idempotency_key": "refund-case-1",
    }
    payload.update(overrides)
    return client.post(
        f"/api/v1/support/conversations/{conversation_id}/refunds",
        headers={"Authorization": f"Bearer {support}"},
        json=payload,
    )


def test_refund_request_is_authorized_limited_and_idempotent() -> None:
    client = TestClient(create_app())
    conversation_id, customer, support = _human_active_conversation(client)

    denied = _refund_request(client, conversation_id, customer)
    assert denied.status_code == 403

    too_large = _refund_request(
        client, conversation_id, support, amount_cents=5001
    )
    assert too_large.status_code == 422

    created = _refund_request(client, conversation_id, support)
    assert created.status_code == 201
    first = created.json()
    assert first["state"] == "PENDING_REVIEW"
    assert first["requested_by"] == "support_001"
    assert first["order_id"] == "order_1001"

    repeated = _refund_request(client, conversation_id, support)
    assert repeated.status_code == 200
    assert repeated.json() == first

    changed = _refund_request(
        client, conversation_id, support, amount_cents=2400
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "idempotency_conflict"


def test_refund_review_requires_approver_and_separation_of_duties() -> None:
    client = TestClient(create_app())
    conversation_id, _, support = _human_active_conversation(client)
    created = _refund_request(client, conversation_id, support)
    refund_id = created.json()["refund_id"]
    customer = _login(client, "customer_001")
    admin = _login(client, "merchant_admin_001")
    approver = _login(client, REFUND_APPROVER_ACTOR_ID)

    for session in (customer, support, admin):
        response = client.get(
            "/api/v1/refunds",
            headers={"Authorization": f"Bearer {session}"},
        )
        assert response.status_code == 403

    listed = client.get(
        "/api/v1/refunds",
        headers={"Authorization": f"Bearer {approver}"},
    )
    assert listed.status_code == 200
    assert listed.json()["refunds"][0]["refund_id"] == refund_id

    fake_same_actor = ActorSummary(
        actor_id="support_001",
        display_name="Invalid approver fixture",
        role="refund_approver",
        customer_id=None,
        permissions=["refunds:review"],
    )
    try:
        client.app.state.service.decide_refund(
            refund_id,
            actor=fake_same_actor,
            decision="approve",
            note="Should be denied",
        )
    except ForbiddenOperation as exc:
        assert "differ" in str(exc)
    else:
        raise AssertionError("an approver must not approve their own request")


def test_refund_approval_and_rejection_are_terminal_review_states() -> None:
    client = TestClient(create_app())
    conversation_id, _, support = _human_active_conversation(client)
    approver = _login(client, REFUND_APPROVER_ACTOR_ID)
    created = _refund_request(client, conversation_id, support)
    refund_id = created.json()["refund_id"]
    approver_headers = {"Authorization": f"Bearer {approver}"}

    approved = client.post(
        f"/api/v1/refunds/{refund_id}/approve",
        headers=approver_headers,
        json={"note": "Policy review complete; external action remains required."},
    )
    assert approved.status_code == 200
    assert approved.json()["state"] == "APPROVED_EXTERNAL_ACTION_REQUIRED"
    assert approved.json()["decided_by"] == REFUND_APPROVER_ACTOR_ID
    assert "external action" in approved.json()["decision_note"]

    second_decision = client.post(
        f"/api/v1/refunds/{refund_id}/reject", headers=approver_headers
    )
    assert second_decision.status_code == 409

    second = _refund_request(
        client,
        conversation_id,
        support,
        idempotency_key="refund-case-2",
        amount_cents=1000,
    )
    rejected = client.post(
        f"/api/v1/refunds/{second.json()['refund_id']}/reject",
        headers=approver_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["state"] == "REJECTED"
    assert rejected.json()["decided_by"] == REFUND_APPROVER_ACTOR_ID
    assert rejected.json()["decision_note"]
    assert "REFUNDED" not in rejected.text


def test_refund_request_requires_human_active_conversation() -> None:
    client = TestClient(create_app())
    customer = _login(client, "customer_001")
    support = _login(client, "support_001")
    created = client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {customer}"},
        json={"channel": "widget", "order_id": "order_1001"},
    )
    response = _refund_request(client, created.json()["conversation_id"], support)
    assert response.status_code == 409


def test_refund_approver_demo_actor_id_matches_server_contract() -> None:
    client = TestClient(create_app())
    valid = client.post(
        "/api/v1/auth/demo-login",
        json={"demo_actor_id": "refund_approver_001"},
    )
    assert valid.status_code == 200
    assert valid.json()["actor"]["role"] == "refund_approver"

    stale = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": "approver_001"}
    )
    assert stale.status_code == 422
