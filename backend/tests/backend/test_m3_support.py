from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.db import ConversationRepository


def _login(client: TestClient, actor_id: str) -> str:
    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": actor_id}
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def _create_and_handoff(client: TestClient, customer_session: str) -> str:
    headers = {"Authorization": f"Bearer {customer_session}"}
    created = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"channel": "widget", "order_id": "order_1001"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["conversation_id"]
    handoff = client.post(
        f"/api/v1/conversations/{conversation_id}/handoff", headers=headers
    )
    assert handoff.status_code == 200
    assert handoff.json()["state"] == "HANDOFF_QUEUED"
    return conversation_id


def test_handoff_inbox_claim_reply_resolve_and_ai_stop() -> None:
    client = TestClient(create_app())
    customer = _login(client, "customer_001")
    support = _login(client, "support_001")
    customer_headers = {"Authorization": f"Bearer {customer}"}
    support_headers = {"Authorization": f"Bearer {support}"}
    conversation_id = _create_and_handoff(client, customer)

    customer_inbox = client.get("/api/v1/support/inbox", headers=customer_headers)
    assert customer_inbox.status_code == 403
    inbox = client.get("/api/v1/support/inbox", headers=support_headers)
    assert inbox.status_code == 200
    assert inbox.json()["conversations"][0]["state"] == "HANDOFF_QUEUED"

    claimed = client.post(
        f"/api/v1/support/conversations/{conversation_id}/claim",
        headers=support_headers,
    )
    assert claimed.status_code == 200
    assert claimed.json()["state"] == "HUMAN_ACTIVE"
    assert claimed.json()["assigned_staff_id"] == "support_001"

    second_claim = client.post(
        f"/api/v1/support/conversations/{conversation_id}/claim",
        headers=support_headers,
    )
    assert second_claim.status_code == 409

    reply = client.post(
        f"/api/v1/support/conversations/{conversation_id}/messages",
        headers=support_headers,
        json={"content": "A support agent is reviewing this now."},
    )
    assert reply.status_code == 201
    assert reply.json()["message"]["author_type"] == "staff"
    assert reply.json()["assistant_reply"] is None

    transcript = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=customer_headers
    )
    assert transcript.status_code == 200
    assert transcript.json()["messages"][-1]["author_type"] == "staff"

    resolved = client.post(
        f"/api/v1/support/conversations/{conversation_id}/resolve",
        headers=support_headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["state"] == "RESOLVED"

    blocked_customer_message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_headers,
        json={"content": "Can I add another question?"},
    )
    assert blocked_customer_message.status_code == 409
    assert blocked_customer_message.json()["error"]["code"] == (
        "conversation_state_conflict"
    )


def test_staff_reply_cannot_append_after_concurrent_resolution(monkeypatch) -> None:
    client = TestClient(create_app())
    customer = _login(client, "customer_001")
    support = _login(client, "support_001")
    conversation_id = _create_and_handoff(client, customer)
    support_headers = {"Authorization": f"Bearer {support}"}
    claimed = client.post(
        f"/api/v1/support/conversations/{conversation_id}/claim",
        headers=support_headers,
    )
    assert claimed.status_code == 200

    repository = client.app.state.service._repository
    append_if_active = repository.append_message_if_state

    def resolve_before_append(*args, **kwargs):
        transitioned = repository.transition(
            conversation_id,
            expected_state="HUMAN_ACTIVE",
            new_state="RESOLVED",
        )
        assert transitioned is not None
        return append_if_active(*args, **kwargs)

    monkeypatch.setattr(repository, "append_message_if_state", resolve_before_append)
    response = client.post(
        f"/api/v1/support/conversations/{conversation_id}/messages",
        headers=support_headers,
        json={"content": "This reply must not be appended after resolution."},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conversation_state_conflict"
    transcript = client.get(
        f"/api/v1/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert transcript.status_code == 200
    assert transcript.json()["state"] == "RESOLVED"
    assert all(
        message["content"] != "This reply must not be appended after resolution."
        for message in transcript.json()["messages"]
    )


def test_conversations_persist_across_app_instances(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'resolveai.db'}"
    first = TestClient(create_app(database_url=database_url))
    customer = _login(first, "customer_001")
    conversation_id = _create_and_handoff(first, customer)

    second = TestClient(create_app(database_url=database_url))
    restored_customer = _login(second, "customer_001")
    restored = second.get(
        f"/api/v1/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {restored_customer}"},
    )
    assert restored.status_code == 200
    assert restored.json()["state"] == "HANDOFF_QUEUED"


def test_staff_cannot_create_widget_conversation() -> None:
    client = TestClient(create_app())
    support = _login(client, "support_001")
    response = client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {support}"},
        json={"channel": "widget", "order_id": "order_1001"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_repository_sequences_preserve_ids_and_message_order(tmp_path: Path) -> None:
    repository = ConversationRepository(
        f"sqlite+pysqlite:///{tmp_path / 'sequence.db'}"
    )
    first = repository.create_conversation(
        owner_customer_id="customer_001",
        channel="widget",
        state="AI_ACTIVE",
        order_id=None,
        created_at=datetime.now(),
    )
    second = repository.create_conversation(
        owner_customer_id="customer_001",
        channel="widget",
        state="AI_ACTIVE",
        order_id=None,
        created_at=datetime.now(),
    )
    assert (first.conversation_id, second.conversation_id) == ("conv_1001", "conv_1002")

    repository.append_message(
        first.conversation_id,
        author_type="customer",
        content="first",
        created_at=datetime.now(),
    )
    repository.append_message(
        first.conversation_id,
        author_type="customer",
        content="second",
        created_at=datetime.now(),
    )
    restored = repository.get(first.conversation_id)
    assert restored is not None
    assert [message.message_id for message in restored.messages] == [
        "msg_1001",
        "msg_1002",
    ]


def test_assistant_append_requires_ai_active_state(tmp_path: Path) -> None:
    repository = ConversationRepository(
        f"sqlite+pysqlite:///{tmp_path / 'state-guard.db'}"
    )
    repository.create_conversation(
        owner_customer_id="customer_001",
        channel="widget",
        state="AI_ACTIVE",
        order_id=None,
        created_at=datetime.now(),
    )
    transitioned = repository.transition(
        "conv_1001",
        expected_state="AI_ACTIVE",
        new_state="HANDOFF_QUEUED",
    )
    assert transitioned is not None

    blocked = repository.append_message_if_state(
        "conv_1001",
        expected_state="AI_ACTIVE",
        author_type="assistant",
        content="This reply must not be persisted after takeover.",
        created_at=datetime.now(),
    )

    assert blocked is None
    restored = repository.get("conv_1001")
    assert restored is not None
    assert restored.messages == ()
