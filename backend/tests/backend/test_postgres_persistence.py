"""Authoritative PostgreSQL persistence and concurrency checks.

These tests are opt-in because the normal developer suite remains dependency
free.  They assume Alembic has already upgraded the configured test database.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert
from sqlalchemy.exc import IntegrityError

from backend.app.api import create_app
from backend.app.db import ConversationRepository, RefundRepository
from backend.app.db.conversations import ConversationRow, MessageRow


@pytest.fixture()
def postgres_url() -> str:
    value = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("set RESOLVEAI_TEST_POSTGRES_URL to an Alembic-migrated PostgreSQL database")
    return value


def _login(client: TestClient, actor_id: str) -> str:
    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": actor_id}
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def _headers(session_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


def _conversation(client: TestClient, customer: str, order_id: str | None = None) -> str:
    response = client.post(
        "/api/v1/conversations",
        headers=_headers(customer),
        json={"channel": "widget", "order_id": order_id},
    )
    assert response.status_code == 201
    return response.json()["conversation_id"]


def test_postgres_conversation_persists_across_service_restart(postgres_url: str) -> None:
    first = TestClient(create_app(database_url=postgres_url))
    first_customer = _login(first, "customer_001")
    conversation_id = _conversation(first, first_customer)
    message = first.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(first_customer),
        json={"content": "moon cheese logistics"},
    )
    assert message.status_code == 201
    assert message.json()["assistant_reply"] is None

    second = TestClient(create_app(database_url=postgres_url))
    second_customer = _login(second, "customer_001")
    restored = second.get(
        f"/api/v1/conversations/{conversation_id}",
        headers=_headers(second_customer),
    )

    assert restored.status_code == 200
    assert restored.json()["messages"][0]["content"] == "moon cheese logistics"


def test_postgres_customer_append_is_rejected_when_resolution_wins(
    postgres_url: str, monkeypatch
) -> None:
    client = TestClient(create_app(database_url=postgres_url))
    customer = _login(client, "customer_001")
    conversation_id = _conversation(client, customer)
    repository = client.app.state.service._repository
    append_unless_resolved = repository.append_message_unless_state

    def resolve_before_append(*args, **kwargs):
        assert repository.transition(
            conversation_id,
            expected_state="AI_ACTIVE",
            new_state="RESOLVED",
        ) is not None
        return append_unless_resolved(*args, **kwargs)

    monkeypatch.setattr(
        repository, "append_message_unless_state", resolve_before_append
    )
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(customer),
        json={"content": "must not persist"},
    )

    assert response.status_code == 409
    restored = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=_headers(customer)
    )
    assert restored.status_code == 200
    assert restored.json()["state"] == "RESOLVED"
    assert restored.json()["messages"] == []


def test_postgres_concurrent_handoffs_allow_one_winner(postgres_url: str) -> None:
    repository = ConversationRepository(postgres_url)
    conversation = repository.create_conversation(
        owner_customer_id="customer_001",
        channel="widget",
        state="AI_ACTIVE",
        order_id=None,
        created_at=datetime.now(),
    )
    barrier = Barrier(2)

    def handoff():
        barrier.wait()
        return repository.transition(
            conversation.conversation_id,
            expected_state="AI_ACTIVE",
            new_state="HANDOFF_QUEUED",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: handoff(), (1, 2)))

    assert sum(result is not None for result in results) == 1
    restored = repository.get(conversation.conversation_id)
    assert restored is not None
    assert restored.state == "HANDOFF_QUEUED"


def test_postgres_constraints_reject_invalid_state_and_orphan_message(
    postgres_url: str,
) -> None:
    engine = create_engine(postgres_url, future=True)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    insert(ConversationRow).values(
                        conversation_id="constraint-invalid-state",
                        owner_customer_id="customer_001",
                        channel="widget",
                        state="INVALID",
                        order_id=None,
                        assigned_staff_id=None,
                        created_at=datetime.now(),
                    )
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    insert(MessageRow).values(
                        message_id="constraint-orphan-message",
                        conversation_id="constraint-missing-conversation",
                        sequence_number=1,
                        author_type="customer",
                        content="orphan",
                        created_at=datetime.now(),
                    )
                )
    finally:
        engine.dispose()


def test_postgres_message_insert_rolls_back_after_constraint_failure(
    postgres_url: str,
) -> None:
    repository = ConversationRepository(postgres_url)
    conversation = repository.create_conversation(
        owner_customer_id="customer_001",
        channel="widget",
        state="AI_ACTIVE",
        order_id=None,
        created_at=datetime.now(),
    )

    with pytest.raises(IntegrityError):
        repository.append_message(
            conversation.conversation_id,
            author_type="untrusted_author",
            content="must roll back",
            created_at=datetime.now(),
        )

    restored = repository.get(conversation.conversation_id)
    assert restored is not None
    assert restored.messages == ()

    appended = repository.append_message(
        conversation.conversation_id,
        author_type="customer",
        content="valid after rollback",
        created_at=datetime.now(),
    )
    assert appended is not None
    assert [message.content for message in appended.messages] == [
        "valid after rollback"
    ]


def test_postgres_resolution_serializes_against_customer_append(
    postgres_url: str,
) -> None:
    repository = ConversationRepository(postgres_url)
    conversation = repository.create_conversation(
        owner_customer_id="customer_001",
        channel="widget",
        state="AI_ACTIVE",
        order_id=None,
        created_at=datetime.now(),
    )
    barrier = Barrier(2)

    def append_customer_message():
        barrier.wait()
        return repository.append_message_unless_state(
            conversation.conversation_id,
            excluded_state="RESOLVED",
            author_type="customer",
            content="one serialized message",
            created_at=datetime.now(),
        )

    def resolve_conversation():
        barrier.wait()
        return repository.transition(
            conversation.conversation_id,
            expected_state="AI_ACTIVE",
            new_state="RESOLVED",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        operations = (append_customer_message, resolve_conversation)
        append_result, resolution_result = list(
            executor.map(lambda operation: operation(), operations)
        )

    assert append_result is not None or resolution_result is not None
    restored = repository.get(conversation.conversation_id)
    assert restored is not None
    assert restored.state == "RESOLVED"
    assert len(restored.messages) <= 1
    if append_result is None:
        assert restored.messages == ()
    else:
        assert [message.content for message in restored.messages] == [
            "one serialized message"
        ]


def test_postgres_refund_idempotency_is_race_safe(postgres_url: str) -> None:
    conversation_repository = ConversationRepository(postgres_url)
    conversation = conversation_repository.create_conversation(
        owner_customer_id="customer_001",
        channel="widget",
        state="AI_ACTIVE",
        order_id="order_1001",
        created_at=datetime.now(),
    )
    assert conversation_repository.transition(
        conversation.conversation_id,
        expected_state="AI_ACTIVE",
        new_state="HUMAN_ACTIVE",
        assigned_staff_id="support_001",
    ) is not None

    refund_repository = RefundRepository(postgres_url)
    barrier = Barrier(2)

    def create_refund():
        barrier.wait()
        return refund_repository.create(
            conversation_id=conversation.conversation_id,
            order_id="order_1001",
            amount_cents=2500,
            reason="Concurrent review",
            idempotency_key=f"pg-race-{conversation.conversation_id}",
            requested_by="support_001",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create_refund(), (1, 2)))

    assert all(result is not None for result in results)
    assert len({result.refund_id for result in results if result is not None}) == 1
    matching_refunds = [
        refund
        for refund in refund_repository.list_all()
        if refund.conversation_id == conversation.conversation_id
    ]
    assert len(matching_refunds) == 1


def test_postgres_refund_idempotency_and_review_persist(postgres_url: str) -> None:
    client = TestClient(create_app(database_url=postgres_url))
    customer = _login(client, "customer_001")
    support = _login(client, "support_001")
    conversation_id = _conversation(client, customer, order_id="order_1001")
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/handoff",
        headers=_headers(customer),
    ).status_code == 200
    assert client.post(
        f"/api/v1/support/conversations/{conversation_id}/claim",
        headers=_headers(support),
    ).status_code == 200

    payload = {
        "amount_cents": 2500,
        "reason": "PostgreSQL persistence review",
        "idempotency_key": f"pg-refund-{conversation_id}",
    }
    path = f"/api/v1/support/conversations/{conversation_id}/refunds"
    first = client.post(path, headers=_headers(support), json=payload)
    repeated = client.post(path, headers=_headers(support), json=payload)
    assert first.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json() == first.json()

    approver = _login(client, "refund_approver_001")
    refund_id = first.json()["refund_id"]
    approved = client.post(
        f"/api/v1/refunds/{refund_id}/approve",
        headers=_headers(approver),
        json={"note": "External action remains required."},
    )
    assert approved.status_code == 200
    assert approved.json()["state"] == "APPROVED_EXTERNAL_ACTION_REQUIRED"
