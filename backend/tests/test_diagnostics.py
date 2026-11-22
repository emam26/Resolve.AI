from __future__ import annotations

import json
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.diagnostics import log_event


class FailingRetriever:
    def retrieve_published_policy(
        self, query: str, audience: str = "customer", top_k: int = 3
    ):
        raise RuntimeError("semantic database unavailable")


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": "customer_001"}
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def _new_conversation(client: TestClient, session_id: str) -> tuple[str, dict[str, str]]:
    headers = {"Authorization": f"Bearer {session_id}"}
    response = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"channel": "widget", "order_id": None},
    )
    assert response.status_code == 201
    return response.json()["conversation_id"], headers


def _events_for(records, correlation_id: str) -> list[dict[str, object]]:
    events = []
    for record in records:
        if record.name != "resolveai":
            continue
        payload = json.loads(record.getMessage())
        if payload.get("correlation_id") == correlation_id:
            events.append(payload)
    return events


def test_diagnostic_events_reject_unallowlisted_fields() -> None:
    with pytest.raises(ValueError, match="not allowlisted"):
        log_event("investigation_completed", query="customer secret")


def test_customer_request_has_correlation_id_and_safe_investigation_event(caplog) -> None:
    caplog.set_level(logging.INFO, logger="resolveai")
    client = TestClient(create_app())
    conversation_id, headers = _new_conversation(client, _login(client))

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "shipment delayed"},
    )

    assert response.status_code == 201
    correlation_id = response.headers["X-Request-ID"]
    UUID(correlation_id)
    events = _events_for(caplog.records, correlation_id)
    completed = next(
        event for event in events if event["event"] == "investigation_completed"
    )
    assert completed["outcome"] == "ANSWER"
    assert completed["retrieval_mode"] == "lexical"
    assert completed["evidence_count"] == 1
    assert completed["handed_off"] is False
    assert "shipment delayed" not in " ".join(record.getMessage() for record in caplog.records)


def test_semantic_failure_logs_fallback_category_without_customer_content(caplog) -> None:
    caplog.set_level(logging.INFO, logger="resolveai")
    client = TestClient(create_app(policy_retriever=FailingRetriever()))
    conversation_id, headers = _new_conversation(client, _login(client))

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "shipment delayed"},
    )

    assert response.status_code == 201
    correlation_id = response.headers["X-Request-ID"]
    events = _events_for(caplog.records, correlation_id)
    fallback = next(
        event for event in events if event["event"] == "policy_retrieval_fallback"
    )
    assert fallback["retrieval_mode"] == "lexical_fallback"
    assert fallback["error_category"] == "semantic_backend_unavailable"
    completed = next(
        event for event in events if event["event"] == "investigation_completed"
    )
    assert completed["retrieval_mode"] == "lexical_fallback"
    assert "shipment delayed" not in " ".join(record.getMessage() for record in caplog.records)
