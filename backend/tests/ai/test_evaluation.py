from __future__ import annotations

import pytest

from backend.app.ai.answer import answer_from_published_policy
from backend.app.ai.evaluation import build_trusted_evaluation_provider
from backend.app.ai.generation import PolicyAnswerPrompt
from backend.app.ai.provider_adapters import (
    ProviderConfigurationError,
    ProviderRequestError,
    RoutedPolicyAnswerProvider,
)
from backend.app.config import ResolveAISettings


def test_trusted_evaluation_factory_is_disabled_by_default() -> None:
    with pytest.raises(ProviderConfigurationError, match="evaluation is disabled"):
        build_trusted_evaluation_provider(
            ResolveAISettings(_env_file=None), synthetic_only=True
        )


def test_trusted_evaluation_requires_explicit_groq_gemini_candidate_scope() -> None:
    base = dict(
        _env_file=None,
        evaluation_enabled=True,
        external_inference_enabled=True,
        zero_cost_mode=False,
        evaluation_request_quota=48,
        evaluation_token_quota=50_000,
        provider_request_quota=48,
        provider_token_quota=50_000,
    )
    with pytest.raises(ProviderConfigurationError, match="allowlist"):
        build_trusted_evaluation_provider(
            ResolveAISettings(**base), synthetic_only=True
        )
    with pytest.raises(ProviderConfigurationError, match="SYNTHETIC_EVALUATION"):
        build_trusted_evaluation_provider(ResolveAISettings(**base))
    with pytest.raises(ProviderConfigurationError, match="Groq/Gemini"):
        build_trusted_evaluation_provider(
            ResolveAISettings(
                **base,
                evaluation_allowed_providers="openrouter",
                evaluation_allowed_model_ids="openrouter:model-a",
            ),
            synthetic_only=True,
        )


def test_routed_customer_provider_cannot_receive_evaluation_scope() -> None:
    with pytest.raises(ProviderConfigurationError, match="customer providers"):
        RoutedPolicyAnswerProvider(
            router=object(),
            adapters={},
            experiment_scope_key="experiment:private",
        )


def test_evaluation_provider_rejects_customer_prompt_before_routing() -> None:
    class UnexpectedRouterCall:
        def select(self, request):  # pragma: no cover - a failed boundary is the assertion
            raise AssertionError(f"router was called for {request}")

    provider = RoutedPolicyAnswerProvider(
        router=UnexpectedRouterCall(),
        adapters={},
        execution_mode="evaluation",
        experiment_scope_key="experiment:synthetic",
    )

    with pytest.raises(ProviderRequestError, match="execution_scope_mismatch"):
        provider.generate(PolicyAnswerPrompt(query="shipment delayed", evidence=[]))


def test_customer_answer_falls_back_without_dispatching_to_evaluation_provider() -> None:
    class UnexpectedRouterCall:
        def select(self, request):  # pragma: no cover - a failed boundary is the assertion
            raise AssertionError(f"router was called for {request}")

    provider = RoutedPolicyAnswerProvider(
        router=UnexpectedRouterCall(),
        adapters={},
        execution_mode="evaluation",
        experiment_scope_key="experiment:synthetic",
    )

    response = answer_from_published_policy(
        "shipment delayed",
        response_provider=provider,
    )

    assert response.generation_mode == "deterministic"
    assert response.answer == (
        "If a shipment is delayed, contact support for an updated estimate."
    )


def test_explicit_synthetic_scope_reaches_only_evaluation_routing() -> None:
    class RecordingRouter:
        def __init__(self) -> None:
            self.requests = []

        def select(self, request):
            self.requests.append(request)
            return None

    router = RecordingRouter()
    provider = RoutedPolicyAnswerProvider(
        router=router,
        adapters={},
        execution_mode="evaluation",
        experiment_scope_key="experiment:synthetic",
    )

    response = answer_from_published_policy(
        "shipment delayed",
        response_provider=provider,
        execution_scope="synthetic_evaluation",
    )

    assert response.generation_mode == "deterministic"
    assert len(router.requests) == 1
    assert router.requests[0].execution_mode == "evaluation"


def test_trusted_factory_blocks_until_historical_provider_usage_is_reconciled() -> None:
    settings = ResolveAISettings(
        _env_file=None,
        evaluation_enabled=True,
        external_inference_enabled=True,
        zero_cost_mode=False,
        evaluation_request_quota=48,
        evaluation_token_quota=50_000,
        provider_request_quota=48,
        provider_token_quota=50_000,
        evaluation_allowed_providers="groq",
        evaluation_allowed_model_ids="groq:gpt-oss-20b",
    )

    with pytest.raises(
        ProviderConfigurationError,
        match="historical provider usage is not reconciled",
    ):
        build_trusted_evaluation_provider(settings, synthetic_only=True)
