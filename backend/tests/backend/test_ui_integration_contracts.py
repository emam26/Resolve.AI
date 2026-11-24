"""Narrow authorization checks for the reconstructed UI contracts."""
from fastapi.testclient import TestClient
from backend.app.api import create_app
from backend.app.config import ResolveAISettings
from backend.tests.backend.test_m21_auth_boundary import _settings


def local_client():
    return TestClient(create_app(database_url="sqlite+pysqlite:///:memory:", settings=ResolveAISettings(_env_file=None)))


def login(client, actor):
    r = client.post("/api/v1/auth/demo-login", json={"demo_actor_id": actor})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['session_id']}"}


def test_case_order_requires_case_scope_and_staff_role():
    client = local_client()
    customer = login(client, "customer_001")
    support = login(client, "support_001")
    admin = login(client, "merchant_admin_001")
    created = client.post("/api/v1/conversations", headers=customer, json={"channel": "widget", "order_id": "order_1001"})
    assert created.status_code == 201
    cid = created.json()["conversation_id"]
    path = f"/api/v1/support/conversations/{cid}/order"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=customer).status_code == 403
    assert client.get(path, headers=admin).status_code == 403
    assert client.get(path, headers=support).status_code == 404
    assert client.get("/api/v1/orders/order_1001", headers=support).status_code == 404
    assert client.post(f"/api/v1/conversations/{cid}/handoff", headers=customer).status_code == 200
    r = client.get(path, headers=support)
    assert r.status_code == 200
    assert r.json()["order_id"] == "order_1001"
    assert client.post(f"/api/v1/support/conversations/{cid}/claim", headers=support).status_code == 200
    assert client.get(path, headers=support).status_code == 200
    assert client.get("/api/v1/support/conversations/nonexistent/order", headers=support).status_code == 404


def test_policy_audit_requires_admin_and_is_bounded():
    client = local_client()
    admin = login(client, "merchant_admin_001")
    support = login(client, "support_001")
    path = "/api/v1/workspace/policy-audit"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=support).status_code == 403
    assert client.get(path+"?limit=101", headers=admin).status_code == 422
    created = client.post("/api/v1/knowledge/policies", headers=admin, json={"document_id":"ui-audit-test","title":"UI audit test","visibility":"public","sections":[{"section":"Window","text":"Synthetic test policy."}]})
    assert created.status_code in (200, 201)
    r = client.get(path+"?limit=1", headers=admin)
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 1
    assert events[0]["document_id"] == "ui-audit-test"


def test_missing_csrf_cookie_and_header_do_not_pass():
    client = TestClient(create_app(database_url="sqlite+pysqlite:///:memory:", settings=_settings()))
    login_response = client.post("/api/v1/auth/login", json={"username":"alice","password":"correct horse battery staple"})
    assert login_response.status_code == 200
    client.cookies.delete("resolveai_csrf")
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.get("/api/v1/me").status_code == 200
