from fastapi.testclient import TestClient

from backend.app.api import create_app


def _login(client: TestClient, actor_id: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": actor_id}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['session_id']}"}


def test_staff_surfaces_enforce_role_boundaries() -> None:
    client = TestClient(create_app())
    paths = (
        "/api/v1/ops/summary",
        "/api/v1/knowledge/policies",
        "/api/v1/workspace/team",
        "/api/v1/workspace/settings",
    )

    for path in paths:
        assert client.get(path).status_code == 401
        assert client.get(path, headers=_login(client, "customer_001")).status_code == 403

    support = _login(client, "support_001")
    assert client.get("/api/v1/ops/summary", headers=support).status_code == 200
    assert client.get("/api/v1/knowledge/policies", headers=support).status_code == 200
    assert client.get("/api/v1/workspace/team", headers=support).status_code == 403
    assert client.get("/api/v1/workspace/settings", headers=support).status_code == 403

    approver = _login(client, "refund_approver_001")
    assert client.get("/api/v1/ops/summary", headers=approver).status_code == 200
    assert client.get("/api/v1/knowledge/policies", headers=approver).status_code == 200
    assert client.get("/api/v1/workspace/team", headers=approver).status_code == 403

    admin = _login(client, "merchant_admin_001")
    assert client.get("/api/v1/ops/summary", headers=admin).status_code == 200
    assert client.get("/api/v1/knowledge/policies", headers=admin).status_code == 200
    assert client.get("/api/v1/workspace/team", headers=admin).status_code == 200
    assert client.get("/api/v1/workspace/settings", headers=admin).status_code == 200


def test_operations_summary_uses_persisted_conversations_and_refunds() -> None:
    client = TestClient(create_app())
    customer = _login(client, "customer_001")
    support = _login(client, "support_001")
    approver = _login(client, "refund_approver_001")

    initial = client.get("/api/v1/ops/summary", headers=support)
    assert initial.status_code == 200
    assert initial.json()["total_conversations"] == 1
    assert initial.json()["active_conversations"] == 1
    assert initial.json()["waiting_conversations"] == 0
    assert initial.json()["resolved_conversations"] == 0
    assert initial.json()["pending_refund_reviews"] == 0

    first = client.post(
        "/api/v1/conversations",
        headers=customer,
        json={"channel": "widget", "order_id": "order_1001"},
    )
    assert first.status_code == 201
    first_id = first.json()["conversation_id"]
    assert client.post(
        f"/api/v1/conversations/{first_id}/handoff", headers=customer
    ).status_code == 200
    assert client.post(
        f"/api/v1/support/conversations/{first_id}/claim", headers=support
    ).status_code == 200
    refund = client.post(
        f"/api/v1/support/conversations/{first_id}/refunds",
        headers=support,
        json={
            "amount_cents": 1200,
            "reason": "Synthetic damaged item review",
            "idempotency_key": "m13-summary-refund",
        },
    )
    assert refund.status_code == 201

    second = client.post(
        "/api/v1/conversations",
        headers=customer,
        json={"channel": "widget", "order_id": None},
    )
    assert second.status_code == 201
    second_id = second.json()["conversation_id"]
    assert client.post(
        f"/api/v1/conversations/{second_id}/handoff", headers=customer
    ).status_code == 200
    assert client.post(
        f"/api/v1/support/conversations/{second_id}/claim", headers=support
    ).status_code == 200
    assert client.post(
        f"/api/v1/support/conversations/{second_id}/resolve", headers=support
    ).status_code == 200

    for headers in (support, approver, _login(client, "merchant_admin_001")):
        response = client.get("/api/v1/ops/summary", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["total_conversations"] == 3
        assert body["active_conversations"] == 2
        assert body["waiting_conversations"] == 0
        assert body["resolved_conversations"] == 1
        assert body["pending_refund_reviews"] == 1
        assert len(body["recent_activity"]) == 3
        assert {item["conversation_id"] for item in body["recent_activity"]} == {
            "conv_foreign_001",
            first_id,
            second_id,
        }


def test_knowledge_filters_and_document_versions_are_read_only_staff_views() -> None:
    client = TestClient(create_app())
    staff = _login(client, "support_001")

    all_policies = client.get("/api/v1/knowledge/policies", headers=staff)
    assert all_policies.status_code == 200
    policies = all_policies.json()["policies"]
    assert policies
    assert {policy["status"] for policy in policies} >= {"published", "unpublished"}
    assert {policy["visibility"] for policy in policies} >= {"public", "internal"}

    public_published = client.get(
        "/api/v1/knowledge/policies",
        headers=staff,
        params={"q": "delayed", "status": "published", "visibility": "public"},
    )
    assert public_published.status_code == 200
    filtered = public_published.json()["policies"]
    assert filtered
    assert all(
        policy["status"] == "published"
        and policy["visibility"] == "public"
        and "delayed" in (
            policy["document_id"]
            + policy["section"]
            + policy["text"]
        ).casefold()
        for policy in filtered
    )

    empty = client.get(
        "/api/v1/knowledge/policies",
        headers=staff,
        params={"q": "does-not-exist-in-policy-corpus"},
    )
    assert empty.status_code == 200
    assert empty.json() == {"policies": []}

    document = client.get(
        "/api/v1/knowledge/policies/delivery-policy", headers=staff
    )
    assert document.status_code == 200
    assert {item["document_version"] for item in document.json()["policies"]} == {
        "v1",
        "v2",
    }
    version = client.get(
        "/api/v1/knowledge/policies/delivery-policy",
        headers=staff,
        params={"version": "v1"},
    )
    assert version.status_code == 200
    assert {item["document_version"] for item in version.json()["policies"]} == {"v1"}
    assert version.json()["policies"][0]["status"] == "unpublished"

    missing = client.get(
        "/api/v1/knowledge/policies/missing-policy", headers=staff
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "policy_not_found"


def test_workspace_team_and_settings_expose_only_safe_synthetic_state() -> None:
    client = TestClient(create_app())
    admin = _login(client, "merchant_admin_001")

    team = client.get("/api/v1/workspace/team", headers=admin)
    assert team.status_code == 200
    members = team.json()["team"]
    assert {member["actor_id"] for member in members} == {
        "support_001",
        "refund_approver_001",
        "merchant_admin_001",
    }
    assert all(member["role"] != "customer" for member in members)

    settings = client.get("/api/v1/workspace/settings", headers=admin)
    assert settings.status_code == 200
    body = settings.json()
    assert body["merchant_name"] == "ResolveAI Demo Merchant"
    assert body["policy_source"] == "POLICY_CORPUS"
    assert body["policy_retrieval_mode"] == "lexical"
    assert body["response_generation_mode"] == "deterministic"
    assert body["database_ready"] is True
    assert "RESOLVEAI_DATABASE_URL" not in settings.text
    assert "sqlite" not in settings.text.lower()
