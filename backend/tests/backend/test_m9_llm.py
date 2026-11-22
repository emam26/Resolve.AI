from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.ai.investigation import (
    MockInvestigationModel,
    ModelDecision,
    run_investigation,
)
from backend.app.rag.models import PolicyEvidence


class FakeAnswerProvider:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls = []

    def generate(self, prompt):
        self.calls.append(prompt)
        return self.output


class InternalOnlyRetriever:
    def retrieve_published_policy(
        self, query: str, audience: str = "customer", top_k: int = 3
    ) -> list[PolicyEvidence]:
        return [
            PolicyEvidence(
                document_id="refund-review-policy",
                document_version="v1",
                section="Refund approval",
                release_id="release_2026_11_01",
                visibility="internal",
                score=0.99,
                text="Refund approvers may approve a refund after support review.",
            )
        ]


def _login(client: TestClient, actor_id: str = "customer_001") -> str:
    response = client.post("/api/v1/auth/demo-login", json={"demo_actor_id": actor_id})
    assert response.status_code == 200
    return response.json()["session_id"]


def _conversation(client: TestClient, session_id: str) -> tuple[str, dict[str, str]]:
    headers = {"Authorization": f"Bearer {session_id}"}
    response = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"channel": "widget", "order_id": None},
    )
    assert response.status_code == 201
    return response.json()["conversation_id"], headers


def test_customer_api_uses_optional_provider_only_after_grounding() -> None:
    provider = FakeAnswerProvider(
        {
            "answer": "If a shipment is delayed, customers may contact support for an updated estimate.",
            "citation_ids": ["evidence-1"],
        }
    )
    client = TestClient(create_app(response_provider=provider))
    conversation_id, headers = _conversation(client, _login(client))

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "shipment delayed"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["assistant_reply"]["content"] == provider.output["answer"]
    assert body["generation_mode"] == "model"
    assert body["citation_ids"] == ["evidence-1"]
    assert body["evidence"][0]["document_version"] == "v2"
    assert provider.calls[0].query == "shipment delayed"
    assert provider.calls[0].evidence[0].evidence.visibility == "public"


def test_customer_cannot_prompt_provider_into_internal_policy_answer() -> None:
    provider = FakeAnswerProvider(
        {
            "answer": "Refund approvers may approve a refund after support review.",
            "citation_ids": ["evidence-1"],
        }
    )
    client = TestClient(
        create_app(policy_retriever=InternalOnlyRetriever(), response_provider=provider)
    )
    conversation_id, headers = _conversation(client, _login(client))

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "approval authorization"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["assistant_reply"] is None
    assert body["handoff_reason"] == "insufficient_published_policy"
    assert body["evidence"] == []
    assert provider.calls == []


def test_refund_request_never_enters_optional_policy_provider() -> None:
    provider = FakeAnswerProvider(
        {"answer": "The refund was approved and paid.", "citation_ids": ["evidence-1"]}
    )
    client = TestClient(create_app(response_provider=provider))
    conversation_id, headers = _conversation(client, _login(client))

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "Please refund my order"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["assistant_reply"] is None
    assert body["handoff_reason"] == "refund_requires_human_review"
    assert provider.calls == []


def test_human_takeover_blocks_optional_provider_before_workflow_execution() -> None:
    provider = FakeAnswerProvider(
        {"answer": "A shipment is delayed.", "citation_ids": ["evidence-1"]}
    )
    result = run_investigation(
        "shipment delayed",
        model=MockInvestigationModel(
            {"shipment delayed": ModelDecision(intent="policy_question")}
        ),
        facts_tool=object(),
        conversation_state="HUMAN_ACTIVE",
        response_provider=provider,
    )

    assert result.handoff_reason == "conversation_not_ai_active"
    assert provider.calls == []
