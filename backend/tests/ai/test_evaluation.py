from __future__ import annotations

import pytest

from backend.app.ai.evaluation import build_trusted_evaluation_provider
from backend.app.ai.provider_adapters import ProviderConfigurationError, RoutedPolicyAnswerProvider
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
