from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.services import in_memory as in_memory_module
from backend.app.services.in_memory import InMemoryResolveService


def _login(client: TestClient, actor_id: str) -> str:
    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": actor_id}
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def _headers(session_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


def _assert_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert body["error"]["code"] == code
    assert set(body["error"]) == {"code", "message", "details"}


def _create_conversation(
    client: TestClient, customer_session: str, *, order_id: str | None = "order_1001"
) -> str:
    response = client.post(
        "/api/v1/conversations",
        headers=_headers(customer_session),
        json={"channel": "widget", "order_id": order_id},
    )
    assert response.status_code == 201
    return response.json()["conversation_id"]


def _human_active_conversation(
    client: TestClient,
) -> tuple[str, str, str]:
    customer = _login(client, "customer_001")
    support = _login(client, "support_001")
    conversation_id = _create_conversation(client, customer)
    handoff = client.post(
        f"/api/v1/conversations/{conversation_id}/handoff",
        headers=_headers(customer),
    )
    assert handoff.status_code == 200
    claim = client.post(
        f"/api/v1/support/conversations/{conversation_id}/claim",
        headers=_headers(support),
    )
    assert claim.status_code == 200
    return conversation_id, customer, support


def _refund_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "amount_cents": 2500,
        "reason": "Delay compensation",
        "idempotency_key": "security-matrix-refund-1",
    }
    payload.update(overrides)
    return payload


def test_protected_routes_reject_missing_empty_malformed_and_unknown_bearers() -> None:
    protected_requests: tuple[tuple[str, str, dict[str, object] | None], ...] = (
        ("GET", "/api/v1/me", None),
        ("GET", "/api/v1/orders/order_1001", None),
        ("POST", "/api/v1/conversations", {"channel": "widget", "order_id": None}),
        (
            "POST",
            "/api/v1/conversations/conv_missing/messages",
            {"content": "unauthorized"},
        ),
        ("GET", "/api/v1/conversations/conv_missing", None),
        ("POST", "/api/v1/conversations/conv_missing/handoff", None),
        ("GET", "/api/v1/support/inbox", None),
        ("POST", "/api/v1/support/conversations/conv_missing/claim", None),
        (
            "POST",
            "/api/v1/support/conversations/conv_missing/messages",
            {"content": "unauthorized"},
        ),
        ("POST", "/api/v1/support/conversations/conv_missing/resolve", None),
        (
            "POST",
            "/api/v1/support/conversations/conv_missing/refunds",
            _refund_payload(),
        ),
        ("GET", "/api/v1/refunds", None),
        ("POST", "/api/v1/refunds/refund_missing/approve", None),
        ("POST", "/api/v1/refunds/refund_missing/reject", None),
    )
    invalid_authorizations = (
        None,
        "",
        "Bearer",
        "Bearer ",
        "Basic demo-session-customer_001",
        "Bearer unknown-session",
        "Bearer demo-session-customer_001 extra",
    )

    for authorization in invalid_authorizations:
        client = TestClient(create_app())
        for method, path, payload in protected_requests:
            headers = {} if authorization is None else {"Authorization": authorization}
            response = client.request(method, path, headers=headers, json=payload)
            _assert_error(response, 401, "unauthenticated")


def test_logout_invalidates_the_authenticated_demo_session() -> None:
    client = TestClient(create_app())
    session = _login(client, "customer_001")
    headers = _headers(session)

    logged_out = client.post("/api/v1/auth/logout", headers=headers)

    assert logged_out.status_code == 204
    assert logged_out.text == ""
    _assert_error(client.get("/api/v1/me", headers=headers), 401, "unauthenticated")
    _assert_error(client.post("/api/v1/auth/logout", headers=headers), 401, "unauthenticated")


def test_demo_login_respects_the_existing_disable_switch(monkeypatch) -> None:
    monkeypatch.setenv("RESOLVEAI_DEMO_AUTH_ENABLED", "false")
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": "customer_001"}
    )

    _assert_error(response, 404, "not_found")


def test_demo_session_expires_without_revealing_or_reusing_the_actor(
    monkeypatch,
) -> None:
    now = [1_000.0]
    monkeypatch.setattr(in_memory_module.time, "monotonic", lambda: now[0])
    service = InMemoryResolveService(session_ttl_seconds=30)
    login = service.demo_login("customer_001")
    assert login is not None
    assert service.actor_for_session(login.session_id) is not None

    now[0] = 1_030.0

    assert service.actor_for_session(login.session_id) is None
    assert service.logout(login.session_id) is False


def test_invalid_bearers_cannot_create_or_append_persistent_state() -> None:
    client = TestClient(create_app())
    customer = _login(client, "customer_001")
    conversation_id = _create_conversation(client, customer, order_id=None)

    for headers in ({}, {"Authorization": ""}, {"Authorization": "Bearer unknown"}):
        response = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=headers,
            json={"content": "must not persist"},
        )
        _assert_error(response, 401, "unauthenticated")

    transcript = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=_headers(customer)
    )
    assert transcript.status_code == 200
    assert transcript.json()["messages"] == []


def test_role_matrix_preserves_customer_support_and_approver_boundaries() -> None:
    client = TestClient(create_app())
    sessions = {
        actor: _login(client, actor)
        for actor in (
            "customer_001",
            "support_001",
            "refund_approver_001",
            "merchant_admin_001",
        )
    }

    assert client.get(
        "/api/v1/orders/order_1001", headers=_headers(sessions["customer_001"])
    ).status_code == 200
    for actor in ("support_001", "refund_approver_001", "merchant_admin_001"):
        response = client.get(
            "/api/v1/orders/order_1001", headers=_headers(sessions[actor])
        )
        _assert_error(response, 404, "order_not_found")

    for actor in ("customer_001", "refund_approver_001", "merchant_admin_001"):
        response = client.get(
            "/api/v1/support/inbox", headers=_headers(sessions[actor])
        )
        _assert_error(response, 403, "forbidden")
    assert client.get(
        "/api/v1/support/inbox", headers=_headers(sessions["support_001"])
    ).status_code == 200

    for actor in ("customer_001", "support_001", "merchant_admin_001"):
        response = client.get(
            "/api/v1/refunds", headers=_headers(sessions[actor])
        )
        _assert_error(response, 403, "forbidden")
    assert client.get(
        "/api/v1/refunds", headers=_headers(sessions["refund_approver_001"])
    ).status_code == 200

    for actor in ("customer_001", "refund_approver_001", "merchant_admin_001"):
        response = client.post(
            "/api/v1/support/conversations/conv_missing/claim",
            headers=_headers(sessions[actor]),
        )
        _assert_error(response, 403, "forbidden")
    response = client.post(
        "/api/v1/support/conversations/conv_missing/claim",
        headers=_headers(sessions["support_001"]),
    )
    _assert_error(response, 404, "conversation_not_found")

    for actor in ("customer_001", "support_001", "merchant_admin_001"):
        response = client.post(
            "/api/v1/refunds/refund_missing/approve",
            headers=_headers(sessions[actor]),
        )
        _assert_error(response, 403, "forbidden")
    response = client.post(
        "/api/v1/refunds/refund_missing/approve",
        headers=_headers(sessions["refund_approver_001"]),
    )
    _assert_error(response, 404, "refund_not_found")


def test_customer_ownership_and_cross_conversation_access_are_hidden() -> None:
    client = TestClient(create_app())
    customer = _login(client, "customer_001")
    support = _login(client, "support_001")
    approver = _login(client, "refund_approver_001")
    customer_headers = _headers(customer)

    for path in (
        "/api/v1/orders/order_1002",
        "/api/v1/orders/order_missing",
        "/api/v1/conversations/conv_foreign_001",
    ):
        response = client.get(path, headers=customer_headers)
        _assert_error(response, 404, "order_not_found" if "/orders/" in path else "conversation_not_found")

    for path, payload in (
        ("/api/v1/conversations/conv_foreign_001/messages", {"content": "foreign"}),
        ("/api/v1/conversations/conv_foreign_001/handoff", None),
    ):
        response = client.post(path, headers=customer_headers, json=payload)
        _assert_error(response, 404, "conversation_not_found")

    conversation_id = _create_conversation(client, customer, order_id=None)
    for path in (
        f"/api/v1/conversations/{conversation_id}",
        f"/api/v1/conversations/{conversation_id}/messages",
        f"/api/v1/conversations/{conversation_id}/handoff",
    ):
        response = client.get(path, headers=_headers(support)) if path.endswith(conversation_id) else client.post(
            path,
            headers=_headers(support),
            json={"content": "staff cannot use customer route"} if path.endswith("messages") else None,
        )
        _assert_error(response, 404, "conversation_not_found")

    refund_attempt = client.post(
        f"/api/v1/support/conversations/{conversation_id}/refunds",
        headers=_headers(approver),
        json=_refund_payload(),
    )
    _assert_error(refund_attempt, 403, "forbidden")
    transcript = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=customer_headers
    )
    assert transcript.status_code == 200
    assert transcript.json()["messages"] == []


def test_only_assigned_support_agent_can_change_human_active_conversation() -> None:
    client = TestClient(create_app())
    conversation_id, _, support = _human_active_conversation(client)
    repository = client.app.state.service._repository
    reassigned = repository.transition(
        conversation_id,
        expected_state="HUMAN_ACTIVE",
        new_state="HUMAN_ACTIVE",
        assigned_staff_id="support_other_001",
    )
    assert reassigned is not None

    reply = client.post(
        f"/api/v1/support/conversations/{conversation_id}/messages",
        headers=_headers(support),
        json={"content": "must not be appended"},
    )
    _assert_error(reply, 403, "forbidden")
    resolve = client.post(
        f"/api/v1/support/conversations/{conversation_id}/resolve",
        headers=_headers(support),
    )
    _assert_error(resolve, 403, "forbidden")
    refund = client.post(
        f"/api/v1/support/conversations/{conversation_id}/refunds",
        headers=_headers(support),
        json=_refund_payload(),
    )
    _assert_error(refund, 403, "forbidden")

    restored = client.app.state.service._repository.get(conversation_id)
    assert restored is not None
    assert restored.state == "HUMAN_ACTIVE"
    assert restored.assigned_staff_id == "support_other_001"
    assert restored.messages == ()


def test_repeated_state_transitions_are_conflict_safe() -> None:
    client = TestClient(create_app())
    customer = _login(client, "customer_001")
    support = _login(client, "support_001")
    conversation_id = _create_conversation(client, customer)
    customer_headers = _headers(customer)
    support_headers = _headers(support)

    first_handoff = client.post(
        f"/api/v1/conversations/{conversation_id}/handoff",
        headers=customer_headers,
    )
    assert first_handoff.status_code == 200
    repeated_handoff = client.post(
        f"/api/v1/conversations/{conversation_id}/handoff",
        headers=customer_headers,
    )
    _assert_error(repeated_handoff, 409, "conversation_state_conflict")

    first_claim = client.post(
        f"/api/v1/support/conversations/{conversation_id}/claim",
        headers=support_headers,
    )
    assert first_claim.status_code == 200
    repeated_claim = client.post(
        f"/api/v1/support/conversations/{conversation_id}/claim",
        headers=support_headers,
    )
    _assert_error(repeated_claim, 409, "conversation_state_conflict")

    first_resolve = client.post(
        f"/api/v1/support/conversations/{conversation_id}/resolve",
        headers=support_headers,
    )
    assert first_resolve.status_code == 200
    repeated_resolve = client.post(
        f"/api/v1/support/conversations/{conversation_id}/resolve",
        headers=support_headers,
    )
    _assert_error(repeated_resolve, 409, "conversation_state_conflict")

    blocked_message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_headers,
        json={"content": "must not append after resolve"},
    )
    _assert_error(blocked_message, 409, "conversation_state_conflict")
    transcript = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=customer_headers
    )
    assert transcript.status_code == 200
    assert transcript.json()["state"] == "RESOLVED"
    assert transcript.json()["messages"] == []


def test_refund_review_separates_roles_and_keeps_terminal_decisions_safe() -> None:
    client = TestClient(create_app())
    conversation_id, customer, support = _human_active_conversation(client)
    approver = _login(client, "refund_approver_001")
    admin = _login(client, "merchant_admin_001")

    create_path = f"/api/v1/support/conversations/{conversation_id}/refunds"
    first = client.post(
        create_path,
        headers=_headers(support),
        json=_refund_payload(),
    )
    assert first.status_code == 201
    refund = first.json()
    repeated = client.post(
        create_path,
        headers=_headers(support),
        json=_refund_payload(),
    )
    assert repeated.status_code == 200
    assert repeated.json() == refund

    for session in (customer, approver, admin):
        response = client.post(
            create_path,
            headers=_headers(session),
            json=_refund_payload(idempotency_key=f"wrong-role-{session}"),
        )
        _assert_error(response, 403, "forbidden")

    support_approval = client.post(
        f"/api/v1/refunds/{refund['refund_id']}/approve",
        headers=_headers(support),
    )
    _assert_error(support_approval, 403, "forbidden")

    approval_path = f"/api/v1/refunds/{refund['refund_id']}/approve"
    approved = client.post(approval_path, headers=_headers(approver))
    assert approved.status_code == 200
    assert approved.json()["state"] == "APPROVED_EXTERNAL_ACTION_REQUIRED"
    repeated_approval = client.post(approval_path, headers=_headers(approver))
    _assert_error(repeated_approval, 409, "refund_state_conflict")
    rejected_after_approval = client.post(
        f"/api/v1/refunds/{refund['refund_id']}/reject",
        headers=_headers(approver),
    )
    _assert_error(rejected_after_approval, 409, "refund_state_conflict")
    assert "REFUNDED" not in approved.text


def test_input_validation_rejects_invalid_shapes_without_side_effects() -> None:
    client = TestClient(create_app())
    customer = _login(client, "customer_001")
    customer_headers = _headers(customer)

    invalid_channel = client.post(
        "/api/v1/conversations",
        headers=customer_headers,
        json={"channel": "email", "order_id": None},
    )
    _assert_error(invalid_channel, 422, "validation_error")

    conversation_id = _create_conversation(client, customer)
    blank_message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_headers,
        json={"content": "   "},
    )
    _assert_error(blank_message, 422, "message_required")
    transcript = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=customer_headers
    )
    assert transcript.status_code == 200
    assert transcript.json()["messages"] == []


def test_refund_validation_rejects_invalid_amount_and_blank_fields() -> None:
    client = TestClient(create_app())
    conversation_id, _, support = _human_active_conversation(client)
    path = f"/api/v1/support/conversations/{conversation_id}/refunds"
    support_headers = _headers(support)

    for invalid_payload, expected_code in (
        (
            {"amount_cents": 0, "reason": "invalid", "idempotency_key": "zero"},
            "validation_error",
        ),
        (
            {"amount_cents": -1, "reason": "invalid", "idempotency_key": "negative"},
            "validation_error",
        ),
        (
            {"amount_cents": 100, "reason": "   ", "idempotency_key": "blank-reason"},
            "refund_validation_error",
        ),
        (
            {"amount_cents": 100, "reason": "invalid", "idempotency_key": "   "},
            "refund_validation_error",
        ),
    ):
        response = client.post(path, headers=support_headers, json=invalid_payload)
        _assert_error(response, 422, expected_code)

    approver = _login(client, "refund_approver_001")
    refunds = client.get("/api/v1/refunds", headers=_headers(approver))
    assert refunds.status_code == 200
    assert refunds.json()["refunds"] == []
