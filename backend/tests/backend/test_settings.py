from __future__ import annotations

from pydantic import ValidationError
import pytest

from backend.app.config import ResolveAISettings


def test_settings_are_safe_and_external_inference_is_disabled_by_default() -> None:
    settings = ResolveAISettings(_env_file=None)

    assert settings.external_inference_enabled is False
    assert settings.zero_cost_mode is True
    assert settings.provider_request_quota == 0
    assert settings.provider_token_quota == 0
    assert settings.provider_max_output_tokens == 256
    assert settings.demo_session_ttl_seconds == 3_600
    assert settings.evaluation_enabled is False
    assert settings.evaluation_request_quota == 0
    assert settings.evaluation_token_quota == 0
    assert settings.groq_api_key is None
    assert settings.gemini_api_key is None
    assert settings.openrouter_api_key is None
    assert settings.cloudflare_api_token is None
    assert settings.modelscope_api_key is None
    assert settings.agnes_api_key is None
    assert settings.chutes_api_key is None
    assert settings.external_provider_allowed("groq") is False


def test_provider_credentials_are_loaded_as_masked_backend_secrets(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-secret-that-must-not-be-logged")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account-that-must-not-be-logged")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token-that-must-not-be-logged")
    monkeypatch.setenv("CHUTES_API_KEY", "test-chutes-token-that-must-not-be-logged")
    monkeypatch.setenv("RESOLVEAI_GROQ_MODEL", "local-test-model")
    monkeypatch.setenv("RESOLVEAI_GROQ_ENABLED", "true")

    settings = ResolveAISettings(_env_file=None)

    assert settings.groq_api_key is not None
    assert settings.cloudflare_account_id is not None
    assert "test-secret-that-must-not-be-logged" not in repr(settings)
    assert "test-secret-that-must-not-be-logged" not in str(settings)
    assert "test-account-that-must-not-be-logged" not in repr(settings)
    assert "test-token-that-must-not-be-logged" not in repr(settings)
    assert "test-chutes-token-that-must-not-be-logged" not in repr(settings)
    assert settings.external_provider_allowed("groq") is False


def test_blank_private_values_are_treated_as_missing(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "")
    monkeypatch.setenv("CHUTES_API_KEY", " ")
    monkeypatch.setenv("RESOLVEAI_DATABASE_URL", "")

    settings = ResolveAISettings(_env_file=None)

    assert settings.gemini_api_key is None
    assert settings.cloudflare_api_token is None
    assert settings.database_url is None
    assert settings.chutes_api_key is None


def test_invalid_provider_limits_fail_closed() -> None:
    try:
        ResolveAISettings(_env_file=None, provider_request_quota=-1)
    except ValidationError as error:
        assert "provider_request_quota" in str(error)
    else:
        raise AssertionError("negative provider quota must be rejected")

    try:
        ResolveAISettings(_env_file=None, provider_max_output_tokens=257)
    except ValidationError as error:
        assert "provider_max_output_tokens" in str(error)
    else:
        raise AssertionError("provider output cap must stay within the approved limit")


def test_evaluation_mode_never_enables_the_customer_provider_gate(monkeypatch) -> None:
    monkeypatch.setenv("RESOLVEAI_EXTERNAL_INFERENCE_ENABLED", "true")
    monkeypatch.setenv("RESOLVEAI_EVALUATION_ENABLED", "true")
    monkeypatch.setenv("RESOLVEAI_PROVIDER_REQUEST_QUOTA", "48")
    monkeypatch.setenv("RESOLVEAI_PROVIDER_TOKEN_QUOTA", "50000")
    monkeypatch.setenv("RESOLVEAI_GROQ_ENABLED", "true")
    monkeypatch.setenv("RESOLVEAI_GROQ_MODEL", "qualified-model")
    monkeypatch.setenv("GROQ_API_KEY", "secret-value")
    settings = ResolveAISettings(_env_file=None)
    assert settings.external_provider_allowed("groq") is False


def test_evaluation_budget_cannot_exceed_authorized_tranche() -> None:
    with pytest.raises(ValidationError):
        ResolveAISettings(_env_file=None, evaluation_request_quota=49)
    with pytest.raises(ValidationError):
        ResolveAISettings(_env_file=None, evaluation_token_quota=50_001)


def test_demo_session_ttl_must_be_bounded_and_positive() -> None:
    with pytest.raises(ValidationError):
        ResolveAISettings(_env_file=None, demo_session_ttl_seconds=0)
    with pytest.raises(ValidationError):
        ResolveAISettings(_env_file=None, demo_session_ttl_seconds=86_401)


def test_production_rejects_predictable_demo_authentication() -> None:
    with pytest.raises(ValidationError, match="demo authentication"):
        ResolveAISettings(
            _env_file=None,
            environment="production",
            demo_auth_enabled=True,
        )

    with pytest.raises(ValidationError, match="PRODUCTION_AUTH_ENABLED"):
        ResolveAISettings(
            _env_file=None,
            environment="production",
            demo_auth_enabled=False,
        )


def test_production_requires_the_code_supported_migration_head() -> None:
    with pytest.raises(ValidationError, match="code-supported head"):
        ResolveAISettings(_env_file=None, supported_alembic_head="20261124_08")
