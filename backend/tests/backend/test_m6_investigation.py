from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.rag.models import PolicyEvidence


DELIVERY_EVIDENCE = PolicyEvidence(
    document_id="delivery-policy",
    document_version="v2",
    section="Delayed shipments",
    release_id="release_2026_11_01",
    visibility="public",
    score=0.91,
    text=(
        "If a shipment is delayed, customers may contact support for an "
        "updated estimate."
    ),
)


class RecordingRetriever:
    def __init__(self, evidence: list[PolicyEvidence] | None = None) -> None:
        self.evidence = evidence if evidence is not None else [DELIVERY_EVIDENCE]
        self.calls: list[tuple[str, str, int]] = []

    def retrieve_published_policy(
        self, query: str, audience: str = "customer", top_k: int = 3
    ) -> list[PolicyEvidence]:
        self.calls.append((query, audience, top_k))
        return self.evidence[:top_k]


class FailingRetriever:
    def retrieve_published_policy(
        self, query: str, audience: str = "customer", top_k: int = 3
    ) -> list[PolicyEvidence]:
        raise RuntimeError("semantic database unavailable")


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": "customer_001"}
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def _new_public_conversation(client: TestClient, session_id: str) -> tuple[str, dict[str, str]]:
    headers = {"Authorization": f"Bearer {session_id}"}
    response = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"channel": "widget", "order_id": None},
    )
    assert response.status_code == 201
    return response.json()["conversation_id"], headers


def test_customer_api_uses_injected_semantic_retriever_in_langgraph_path() -> None:
    retriever = RecordingRetriever()
    client = TestClient(create_app(policy_retriever=retriever))
    conversation_id, headers = _new_public_conversation(client, _login(client))

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "What should I do about a shipment delay?"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["assistant_reply"]["content"] == (
        "If a shipment is delayed, contact support for an updated estimate."
    )
    assert body["evidence"][0]["document_version"] == "v2"
    assert body["retrieval_mode"] == "semantic"
    assert retriever.calls == [
        ("What should I do about a shipment delay?", "customer", 3)
    ]


def test_semantic_backend_failure_falls_back_to_lexical_answer() -> None:
    client = TestClient(create_app(policy_retriever=FailingRetriever()))
    conversation_id, headers = _new_public_conversation(client, _login(client))

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "shipment delayed"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["assistant_reply"]["content"] == (
        "If a shipment is delayed, contact support for an updated estimate."
    )
    assert body["evidence"][0]["document_version"] == "v2"
    assert body["retrieval_mode"] == "lexical_fallback"


def test_irrelevant_customer_question_hands_off_without_evidence() -> None:
    client = TestClient(create_app(policy_retriever=RecordingRetriever([])))
    conversation_id, headers = _new_public_conversation(client, _login(client))

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "Explain moon cheese logistics"},
    )

    assert response.status_code == 201
    assert response.json()["assistant_reply"] is None
    assert response.json()["evidence"] == []
    assert response.json()["handoff_reason"] == "insufficient_published_policy"
    assert response.json()["retrieval_mode"] == "semantic"
