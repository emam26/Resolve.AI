"""Typed, backend-only configuration for local ResolveAI development.

The settings object is intentionally small and fail-closed.  Provider secrets
are represented as ``SecretStr`` values and are never serialized by the API.
External providers remain disabled unless an owner explicitly changes the
local configuration and supplies credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ProviderName = Literal[
    "groq",
    "gemini",
    "openrouter",
    "cloudflare",
    "modelscope",
    "agnes",
    "chutes",
]


class ResolveAISettings(BaseSettings):
    """Environment-backed settings consumed by the backend only.

    A zero quota means that no external request may be made.  This is the
    default together with ``zero_cost_mode=True`` and
    ``external_inference_enabled=False``.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    environment: str = Field(
        default="local",
        validation_alias=AliasChoices("RESOLVEAI_ENVIRONMENT", "ENVIRONMENT"),
    )

    # Credentials are backend-only and intentionally absent by default.
    groq_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GROQ_API_KEY", "RESOLVEAI_GROQ_API_KEY"),
    )
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "RESOLVEAI_GEMINI_API_KEY"),
    )
    cloudflare_account_id: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CLOUDFLARE_ACCOUNT_ID", "RESOLVEAI_CLOUDFLARE_ACCOUNT_ID"
        ),
    )
    cloudflare_api_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CLOUDFLARE_API_TOKEN", "RESOLVEAI_CLOUDFLARE_API_TOKEN"
        ),
    )
    openrouter_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "RESOLVEAI_OPENROUTER_API_KEY"),
    )
    modelscope_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("MODELSCOPE_API_KEY", "RESOLVEAI_MODELSCOPE_API_KEY"),
    )
    agnes_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("AGNES_API_KEY", "RESOLVEAI_AGNES_API_KEY"),
    )
    chutes_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CHUTES_API_KEY", "RESOLVEAI_CHUTES_API_KEY"),
    )

    # Provider selection is explicit.  Model identifiers are inert until the
    # corresponding provider is enabled and the global gates allow requests.
    groq_model: str = Field(
        default="",
        validation_alias=AliasChoices("RESOLVEAI_GROQ_MODEL", "GROQ_MODEL"),
    )
    gemini_model: str = Field(
        default="",
        validation_alias=AliasChoices("RESOLVEAI_GEMINI_MODEL", "GEMINI_MODEL"),
    )
    openrouter_model: str = Field(
        default="",
        validation_alias=AliasChoices("RESOLVEAI_OPENROUTER_MODEL", "OPENROUTER_MODEL"),
    )
    cloudflare_model: str = Field(
        default="",
        validation_alias=AliasChoices("RESOLVEAI_CLOUDFLARE_MODEL", "CLOUDFLARE_MODEL"),
    )
    modelscope_model: str = Field(
        default="",
        validation_alias=AliasChoices("RESOLVEAI_MODELSCOPE_MODEL", "MODELSCOPE_MODEL"),
    )
    modelscope_base_url: str | None = Field(
        default=None, validation_alias="RESOLVEAI_MODELSCOPE_BASE_URL"
    )
    agnes_model: str = Field(
        default="",
        validation_alias=AliasChoices("RESOLVEAI_AGNES_MODEL", "AGNES_MODEL"),
    )
    chutes_model: str = Field(
        default="",
        validation_alias=AliasChoices("RESOLVEAI_CHUTES_MODEL", "CHUTES_MODEL"),
    )
    groq_enabled: bool = Field(default=False, validation_alias="RESOLVEAI_GROQ_ENABLED")
    gemini_enabled: bool = Field(default=False, validation_alias="RESOLVEAI_GEMINI_ENABLED")
    openrouter_enabled: bool = Field(
        default=False, validation_alias="RESOLVEAI_OPENROUTER_ENABLED"
    )
    cloudflare_enabled: bool = Field(
        default=False, validation_alias="RESOLVEAI_CLOUDFLARE_ENABLED"
    )
    modelscope_enabled: bool = Field(
        default=False, validation_alias="RESOLVEAI_MODELSCOPE_ENABLED"
    )
    agnes_enabled: bool = Field(default=False, validation_alias="RESOLVEAI_AGNES_ENABLED")
    chutes_enabled: bool = Field(default=False, validation_alias="RESOLVEAI_CHUTES_ENABLED")
    external_inference_enabled: bool = Field(
        default=False, validation_alias="RESOLVEAI_EXTERNAL_INFERENCE_ENABLED"
    )
    model_discovery_enabled: bool = Field(
        default=False, validation_alias="RESOLVEAI_MODEL_DISCOVERY_ENABLED"
    )
    model_catalog_ttl_seconds: int = Field(
        default=21_600,
        gt=0,
        validation_alias="RESOLVEAI_MODEL_CATALOG_TTL_SECONDS",
    )
    zero_cost_mode: bool = Field(default=True, validation_alias="RESOLVEAI_ZERO_COST_MODE")
    provider_request_quota: int = Field(
        default=0,
        ge=0,
        validation_alias="RESOLVEAI_PROVIDER_REQUEST_QUOTA",
    )
    provider_token_quota: int = Field(
        default=0,
        ge=0,
        validation_alias="RESOLVEAI_PROVIDER_TOKEN_QUOTA",
    )
    provider_quota_window_seconds: int = Field(
        default=86_400,
        gt=0,
        validation_alias="RESOLVEAI_PROVIDER_QUOTA_WINDOW_SECONDS",
    )
    provider_timeout_seconds: float = Field(
        default=8.0,
        gt=0,
        le=300,
        validation_alias="RESOLVEAI_PROVIDER_TIMEOUT_SECONDS",
    )
    provider_max_concurrency: int = Field(
        default=1,
        ge=1,
        le=64,
        validation_alias="RESOLVEAI_PROVIDER_MAX_CONCURRENCY",
    )
    provider_max_output_tokens: int = Field(
        default=256,
        gt=0,
        le=256,
        validation_alias="RESOLVEAI_PROVIDER_MAX_OUTPUT_TOKENS",
    )

    # Evaluation budgets are separate from customer-serving provider quotas.
    # They remain disabled until a trusted server-side evaluation harness
    # supplies an explicit experiment identifier and non-zero limits.
    evaluation_enabled: bool = Field(
        default=False, validation_alias="RESOLVEAI_EVALUATION_ENABLED"
    )
    evaluation_experiment_id: str | None = Field(
        default=None, validation_alias="RESOLVEAI_EVALUATION_EXPERIMENT_ID"
    )
    evaluation_allowed_providers: str = Field(
        default="", validation_alias="RESOLVEAI_EVALUATION_ALLOWED_PROVIDERS"
    )
    evaluation_allowed_model_ids: str = Field(
        default="", validation_alias="RESOLVEAI_EVALUATION_ALLOWED_MODEL_IDS"
    )
    evaluation_max_models_per_provider: int = Field(
        default=2,
        ge=1,
        le=2,
        validation_alias="RESOLVEAI_EVALUATION_MAX_MODELS_PER_PROVIDER",
    )
    evaluation_request_quota: int = Field(
        default=0,
        ge=0,
        le=48,
        validation_alias="RESOLVEAI_EVALUATION_REQUEST_QUOTA",
    )
    evaluation_token_quota: int = Field(
        default=0,
        ge=0,
        le=50_000,
        validation_alias="RESOLVEAI_EVALUATION_TOKEN_QUOTA",
    )
    evaluation_max_concurrency: int = Field(
        default=1,
        ge=1,
        le=64,
        validation_alias="RESOLVEAI_EVALUATION_MAX_CONCURRENCY",
    )
    evaluation_quota_window_seconds: int = Field(
        default=86_400,
        gt=0,
        validation_alias="RESOLVEAI_EVALUATION_QUOTA_WINDOW_SECONDS",
    )

    # Existing local policy and application configuration.
    policy_retrieval: str = Field(
        default="lexical", validation_alias="RESOLVEAI_POLICY_RETRIEVAL"
    )
    sentence_transformer_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        validation_alias="RESOLVEAI_SENTENCE_TRANSFORMER_MODEL",
    )
    local_policy_model: str = Field(
        default="", validation_alias="RESOLVEAI_LOCAL_POLICY_MODEL"
    )
    local_policy_timeout_seconds: float = Field(
        default=8.0,
        gt=0,
        le=300,
        validation_alias="RESOLVEAI_LOCAL_POLICY_TIMEOUT_SECONDS",
    )
    local_policy_max_new_tokens: int = Field(
        default=256,
        gt=0,
        le=4096,
        validation_alias="RESOLVEAI_LOCAL_POLICY_MAX_NEW_TOKENS",
    )
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("RESOLVEAI_DATABASE_URL", "DATABASE_URL"),
    )
    commerce_database_url: str | None = Field(
        default=None,
        validation_alias="RESOLVEAI_COMMERCE_DATABASE_URL",
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="RESOLVEAI_CORS_ORIGINS",
    )
    auth_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("RESOLVEAI_AUTH_SECRET_KEY", "AUTH_SECRET_KEY"),
    )
    demo_auth_enabled: bool = Field(default=True, validation_alias="RESOLVEAI_DEMO_AUTH_ENABLED")

    @field_validator(
        "groq_api_key",
        "gemini_api_key",
        "cloudflare_account_id",
        "cloudflare_api_token",
        "openrouter_api_key",
        "modelscope_api_key",
        "modelscope_base_url",
        "agnes_api_key",
        "chutes_api_key",
        "evaluation_experiment_id",
        "database_url",
        "commerce_database_url",
        "auth_secret_key",
        mode="before",
    )
    @classmethod
    def _blank_optional_values_are_missing(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("local_policy_timeout_seconds", mode="before")
    @classmethod
    def _parse_local_timeout(cls, value):
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError as error:
                raise ValueError("must be numeric") from error
        return value

    def external_provider_allowed(self, provider: ProviderName) -> bool:
        """Return whether a provider could be called under current local gates.

        This is a policy check only; it performs no network operation and does
        not return the underlying secret.
        """

        if (
            not self.external_inference_enabled
            or self.zero_cost_mode
            or self.evaluation_enabled
            or self.provider_request_quota <= 0
            or self.provider_token_quota <= 0
        ):
            return False
        if not getattr(self, f"{provider}_enabled"):
            return False
        model = getattr(self, f"{provider}_model").strip()
        if not model:
            return False
        if provider == "cloudflare":
            return bool(self.cloudflare_account_id and self.cloudflare_api_token)
        return bool(getattr(self, f"{provider}_api_key"))


def get_settings() -> ResolveAISettings:
    """Load current process settings without caching secrets or configuration."""

    return ResolveAISettings()
