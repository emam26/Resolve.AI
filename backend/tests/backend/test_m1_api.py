from fastapi.testclient import TestClient

from backend.app.api import create_app


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": "customer_001"}
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def test_authentication_and_current_actor() -> None:
    client = TestClient(create_app())

    unauthenticated = client.get("/api/v1/me")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json() == {
        "error": {
            "code": "unauthenticated",
            "message": "Authentication is required.",
            "details": {},
        }
    }

    session_id = _login(client)
    current = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {session_id}"}
    )
    assert current.status_code == 200
    assert current.json()["actor_id"] == "customer_001"
    assert current.json()["role"] == "customer"


def test_local_frontend_origin_can_preflight_authorized_requests() -> None:
    client = TestClient(create_app())
    response = client.options(
        "/api/v1/me",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_login_rejects_unknown_actor_without_client_role() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/auth/demo-login",
        json={"demo_actor_id": "customer_001", "role": "merchant_admin"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

    unknown = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": "customer_999"}
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "invalid_demo_actor"


def test_order_ownership_and_missing_order_are_hidden() -> None:
    client = TestClient(create_app())
    session_id = _login(client)
    headers = {"Authorization": f"Bearer {session_id}"}

    owned = client.get("/api/v1/orders/order_1001", headers=headers)
    assert owned.status_code == 200
    assert owned.json() == {
        "order_id": "order_1001",
        "status": "delayed",
        "payment_status": "paid",
        "shipment_status": "delayed",
        "estimated_delivery_date": "2026-11-08",
    }

    for order_id in ("order_1002", "order_missing"):
        denied = client.get(f"/api/v1/orders/{order_id}", headers=headers)
        assert denied.status_code == 404
        assert denied.json()["error"]["code"] == "order_not_found"


def test_conversation_lifecycle_is_server_authored_and_deterministic() -> None:
    client = TestClient(create_app())
    session_id = _login(client)
    headers = {"Authorization": f"Bearer {session_id}"}

    created = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"channel": "widget", "order_id": "order_1001"},
    )
    assert created.status_code == 201
    assert created.json() == {
        "conversation_id": "conv_1001",
        "channel": "widget",
        "state": "AI_ACTIVE",
        "order_id": "order_1001",
        "messages": [],
    }

    conversation_id = created.json()["conversation_id"]
    message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "Where is my order?"},
    )
    assert message.status_code == 201
    assert message.json()["message"] == {
        "message_id": "msg_1001",
        "author_type": "customer",
        "content": "Where is my order?",
        "created_at": "2026-11-21T12:00:00Z",
    }
    assert message.json()["assistant_reply"] == {
        "message_id": "msg_1002",
        "author_type": "assistant",
        "content": (
            "Order order_1001 is delayed; shipment is delayed. "
            "Estimated delivery: 2026-11-08."
        ),
        "created_at": "2026-11-21T12:00:00Z",
    }
    assert message.json()["evidence"] == []
    assert message.json()["handoff_reason"] is None

    transcript = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=headers
    )
    assert transcript.status_code == 200
    assert transcript.json()["messages"] == [
        message.json()["message"],
        message.json()["assistant_reply"],
    ]


def test_conversation_ownership_and_empty_message_errors() -> None:
    client = TestClient(create_app())
    session_id = _login(client)
    headers = {"Authorization": f"Bearer {session_id}"}
    created = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"channel": "widget", "order_id": None},
    )
    conversation_id = created.json()["conversation_id"]

    for path in (
        "/api/v1/conversations/conv_missing",
        "/api/v1/conversations/conv_foreign_001",
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "conversation_not_found"

    empty = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": ""},
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "message_required"

    whitespace = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "   "},
    )
    assert whitespace.status_code == 422
    assert whitespace.json()["error"]["code"] == "message_required"

    spoofed = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "Please help", "author_type": "staff"},
    )
    assert spoofed.status_code == 422
    assert spoofed.json()["error"]["code"] == "validation_error"
