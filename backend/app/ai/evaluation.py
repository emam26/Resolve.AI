"""Trusted server-side construction of the isolated synthetic evaluation path.

This module has no FastAPI route and accepts no customer-controlled mode or
experiment identifier.  An owner-run local harness must explicitly enable
evaluation settings, provide a durable PostgreSQL control plane, and pass the
resulting scoped provider to its synthetic fixtures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from backend.app.ai.model_control import (
    AdaptiveModelRouter,
    ModelRegistry,
    QuotaLedger,
    QuotaScopeConfig,
)
from backend.app.ai.provider_adapters import (
    ProviderConfigurationError,
    RoutedPolicyAnswerProvider,
    build_provider_adapter,
)
from backend.app.config import ResolveAISettings


MAX_EVALUATION_REQUESTS = 48
MAX_EVALUATION_TOKENS = 50_000
SYNTHETIC_EVALUATION_MARKER = "RESOLVEAI_SYNTHETIC_EVALUATION"


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def build_trusted_evaluation_provider(
    settings: ResolveAISettings,
    *,
    database_url: str | None = None,
    synthetic_only: bool = False,
) -> RoutedPolicyAnswerProvider:
    """Build a provider usable only by a trusted synthetic evaluation harness."""

    if not settings.evaluation_enabled:
        raise ProviderConfigurationError("synthetic evaluation is disabled")
    if not synthetic_only:
        raise ProviderConfigurationError(
            f"evaluation requires the {SYNTHETIC_EVALUATION_MARKER} marker"
        )
    if not settings.external_inference_enabled or settings.zero_cost_mode:
        raise ProviderConfigurationError("external evaluation is disabled by safety policy")
    if (
        settings.evaluation_request_quota <= 0
        or settings.evaluation_request_quota > MAX_EVALUATION_REQUESTS
        or settings.evaluation_token_quota <= 0
        or settings.evaluation_token_quota > MAX_EVALUATION_TOKENS
    ):
        raise ProviderConfigurationError("evaluation quotas must be positive")
    if settings.provider_request_quota <= 0 or settings.provider_token_quota <= 0:
        raise ProviderConfigurationError("provider quotas must be positive")
    allowed_providers = set(_csv_values(settings.evaluation_allowed_providers))
    if not allowed_providers or not allowed_providers.issubset({"groq", "gemini"}):
        raise ProviderConfigurationError(
            "evaluation providers must be an explicit Groq/Gemini allowlist"
        )
    candidate_keys = _csv_values(settings.evaluation_allowed_model_ids)
    if not candidate_keys:
        raise ProviderConfigurationError("evaluation model allowlist is required")
    if len(set(candidate_keys)) != len(candidate_keys):
        raise ProviderConfigurationError("evaluation model allowlist contains duplicates")
    candidate_providers = [key.split(":", 1)[0] for key in candidate_keys if ":" in key]
    if len(candidate_providers) != len(candidate_keys) or not set(candidate_providers).issubset(
        allowed_providers
    ):
        raise ProviderConfigurationError("evaluation model keys must be provider:model_id entries")
    if any(
        candidate_providers.count(provider) > settings.evaluation_max_models_per_provider
        for provider in allowed_providers
    ):
        raise ProviderConfigurationError("evaluation model limit per provider exceeded")
    candidate_key_set = set(candidate_keys)
    configured_database_url = database_url or settings.database_url
    if not configured_database_url or not configured_database_url.startswith(
        ("postgresql", "postgres")
    ):
        raise ProviderConfigurationError("evaluation requires a PostgreSQL control plane")
    database_host = urlsplit(configured_database_url).hostname
    if settings.environment != "local" or database_host not in {"localhost", "127.0.0.1", "::1"}:
        raise ProviderConfigurationError("synthetic evaluation requires local PostgreSQL")

    registry = ModelRegistry(configured_database_url, initialize_schema=False)
    quota = QuotaLedger(configured_database_url)
    models = tuple(
        model
        for model in registry.list()
        if model.model_key in candidate_key_set
        and model.provider in allowed_providers
        and model.lifecycle in {"QUALIFIED", "ACTIVE"}
        and model.evaluation_version
        and model.available
        and not model.deprecated
        and model.free_eligible is True
        and model.privacy_eligible
        and model.structured_output_supported is True
    )
    if not models:
        raise ProviderConfigurationError("no evaluation-qualified models are available")
    if {model.model_key for model in models} != candidate_key_set:
        raise ProviderConfigurationError(
            "every allowlisted evaluation model must be qualified and available"
        )

    adapters = {}
    for model in models:
        try:
            adapters[model.model_key] = build_provider_adapter(
                model.provider,
                model.model_id,
                settings,
                modelscope_base_url=settings.modelscope_base_url,
            )
        except ProviderConfigurationError:
            continue
    if set(adapters) != candidate_key_set:
        raise ProviderConfigurationError(
            "every allowlisted evaluation model must have a configured adapter"
        )

    reset_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.provider_quota_window_seconds
    )
    scopes: dict[str, QuotaScopeConfig] = {}
    for model in models:
        for scope_key, provider in (
            (model.quota_scope, model.provider),
            (f"account:{model.provider}", model.provider),
        ):
            scopes.setdefault(
                scope_key,
                QuotaScopeConfig(
                    scope_key=scope_key,
                    provider=provider,
                    request_limit=settings.provider_request_quota,
                    token_limit=settings.provider_token_quota,
                    concurrency_limit=settings.provider_max_concurrency,
                    window_seconds=settings.provider_quota_window_seconds,
                    reset_at=reset_at,
                ),
            )
    quota.ensure_scopes(*scopes.values())
    experiment_scope = quota.configure_experiment_from_settings(settings)
    return RoutedPolicyAnswerProvider(
        AdaptiveModelRouter(registry, quota, account_scope_prefix="account:"),
        adapters,
        estimated_tokens=min(settings.provider_max_output_tokens, 256),
        deadline_ms=settings.provider_timeout_seconds * 1000,
        execution_mode="evaluation",
        experiment_scope_key=experiment_scope,
    )


__all__ = [
    "MAX_EVALUATION_REQUESTS",
    "MAX_EVALUATION_TOKENS",
    "SYNTHETIC_EVALUATION_MARKER",
    "build_trusted_evaluation_provider",
]
