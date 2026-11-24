from __future__ import annotations

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
