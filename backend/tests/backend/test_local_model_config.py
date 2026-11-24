from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.ai.local_transformers import LocalTransformersPolicyAnswerProvider
from backend.app.api.app import (
    _configured_external_policy_response_provider,
    _configured_policy_response_provider,
)
from backend.app.config import ResolveAISettings


def test_local_model_provider_is_disabled_without_explicit_configuration(monkeypatch) -> None:
    monkeypatch.delenv("RESOLVEAI_LOCAL_POLICY_MODEL", raising=False)

    assert _configured_policy_response_provider() is None


def test_external_provider_data_plane_is_disabled_by_default() -> None:
    assert _configured_external_policy_response_provider(ResolveAISettings(_env_file=None)) is None


def test_external_startup_initializes_customer_and_account_quota_scopes(monkeypatch) -> None:
    import backend.app.api.app as app_module

    model = SimpleNamespace(
        model_key="groq:qualified",
        provider="groq",
        model_id="qualified",
        quota_scope="groq:qualified",
    )
    captured: dict[str, object] = {}

    class FakeRegistry:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def list(self):
            return (model,)

    class FakeLedger:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def ensure_scopes(self, *configs) -> None:
            captured["configs"] = configs

    monkeypatch.setattr(app_module, "ModelRegistry", FakeRegistry)
    monkeypatch.setattr(app_module, "QuotaLedger", FakeLedger)
    monkeypatch.setattr(app_module, "build_provider_adapter", lambda *_args, **_kwargs: object())
    settings = ResolveAISettings(
        _env_file=None,
        database_url="postgresql://synthetic.invalid/resolveai",
        external_inference_enabled=True,
        zero_cost_mode=False,
        provider_request_quota=48,
        provider_token_quota=50_000,
        provider_max_concurrency=2,
        groq_enabled=True,
        groq_model="qualified",
        groq_api_key="synthetic-key",
    )

    provider = _configured_external_policy_response_provider(settings)

    assert provider is not None
    configs = captured["configs"]
    assert {config.scope_key for config in configs} == {"groq:qualified", "account:groq"}
    assert all(config.request_limit == 48 for config in configs)
    assert all(config.token_limit == 50_000 for config in configs)
    assert all(config.window_seconds == 86_400 for config in configs)


def test_evaluation_mode_keeps_external_customer_provider_disabled() -> None:
    settings = ResolveAISettings(
        _env_file=None,
        external_inference_enabled=True,
        zero_cost_mode=False,
        provider_request_quota=48,
        provider_token_quota=50_000,
        evaluation_enabled=True,
    )
    assert _configured_external_policy_response_provider(settings) is None


def test_local_model_provider_is_local_only_and_lazy(monkeypatch) -> None:
    monkeypatch.setenv("RESOLVEAI_LOCAL_POLICY_MODEL", "C:/models/example")
    monkeypatch.setenv("RESOLVEAI_LOCAL_POLICY_TIMEOUT_SECONDS", "3.5")

    provider = _configured_policy_response_provider()

    assert isinstance(provider, LocalTransformersPolicyAnswerProvider)
    assert provider.model_name == "C:/models/example"
    assert provider.timeout_seconds == 3.5


def test_local_model_provider_rejects_invalid_timeout_configuration(monkeypatch) -> None:
    monkeypatch.setenv("RESOLVEAI_LOCAL_POLICY_MODEL", "C:/models/example")
    monkeypatch.setenv("RESOLVEAI_LOCAL_POLICY_TIMEOUT_SECONDS", "not-a-number")

    with pytest.raises(ValueError, match="must be numeric"):
        _configured_policy_response_provider()
