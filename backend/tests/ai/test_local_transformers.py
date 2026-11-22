from __future__ import annotations

import json
import time

import pytest

from backend.app.ai.answer import answer_from_published_policy
from backend.app.ai.generation import (
    AuthorizedPolicyEvidence,
    InvalidGeneratedAnswer,
    PolicyAnswerPrompt,
)
from backend.app.ai.local_transformers import LocalTransformersPolicyAnswerProvider
from backend.app.rag.models import PolicyEvidence


def _prompt() -> PolicyAnswerPrompt:
    evidence = PolicyEvidence(
        document_id="delivery-policy",
        document_version="v2",
        section="Delayed shipments",
        release_id="release_2026_11_01",
        visibility="public",
        score=0.91,
        text="If a shipment is delayed, customers may contact support for an updated estimate.",
    )
    return PolicyAnswerPrompt(
        query="Where is my delayed order?",
        evidence=[
            AuthorizedPolicyEvidence(
                citation_id="evidence-1",
                evidence=evidence,
                answer_text="If a shipment is delayed, contact support for an updated estimate.",
            )
        ],
    )


def test_local_transformers_provider_uses_structured_local_output() -> None:
    seen: list[str] = []
    provider = LocalTransformersPolicyAnswerProvider(
        "local-model",
        text_generator=lambda rendered: (
            seen.append(rendered)
            or json.dumps(
                {
                    "answer": "If a shipment is delayed, contact support for an updated estimate.",
                    "citation_ids": ["evidence-1"],
                }
            )
        ),
    )

    response = provider.generate(_prompt())

    assert response["citation_ids"] == ["evidence-1"]
    assert "Where is my delayed order?" in seen[0]
    assert "delivery-policy" not in seen[0]
    assert "server_answer_text" in seen[0]
    assert "Return exactly one JSON object" in seen[0]


def test_local_transformers_provider_rejects_non_json_output() -> None:
    provider = LocalTransformersPolicyAnswerProvider(
        "local-model",
        text_generator=lambda rendered: "Here is your answer: not JSON",
    )

    with pytest.raises(InvalidGeneratedAnswer, match="JSON object"):
        provider.generate(_prompt())


def test_local_transformers_provider_integrates_through_grounding_boundary() -> None:
    provider = LocalTransformersPolicyAnswerProvider(
        "local-model",
        text_generator=lambda rendered: json.dumps(
            {
                "answer": "If a shipment is delayed, contact support for an updated estimate.",
                "citation_ids": ["evidence-1"],
            }
        ),
    )

    response = answer_from_published_policy("shipment delayed", response_provider=provider)

    assert response.grounded is True
    assert response.generation_mode == "model"
    assert response.citation_ids == ["evidence-1"]


def test_local_transformers_provider_closes_after_timeout() -> None:
    def slow_generator(rendered: str) -> str:
        del rendered
        time.sleep(0.05)
        return "{}"

    provider = LocalTransformersPolicyAnswerProvider(
        "local-model",
        timeout_seconds=0.001,
        text_generator=slow_generator,
    )

    with pytest.raises(TimeoutError, match="timed out"):
        provider.generate(_prompt())
    with pytest.raises(RuntimeError, match="unavailable"):
        provider.generate(_prompt())


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, float("nan"), float("inf")])
def test_local_transformers_provider_rejects_invalid_timeout(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        LocalTransformersPolicyAnswerProvider(
            "local-model",
            timeout_seconds=timeout_seconds,
        )
