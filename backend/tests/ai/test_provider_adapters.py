from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from backend.app.ai.generation import AuthorizedPolicyEvidence, PolicyAnswerPrompt
from backend.app.ai.model_control import (
    AdaptiveModelRouter,
    ModelDescriptor,
    ModelRegistry,
    QualificationEvidence,
    QuotaLedger,
)
from backend.app.ai.provider_adapters import (
    CloudflareWorkersAIPolicyAnswerProvider,
    GeminiPolicyAnswerProvider,
    ModelScopePolicyAnswerProvider,
    OpenAICompatiblePolicyAnswerProvider,
    ProviderConfigurationError,
    ProviderRequestError,
    ProviderUsage,
    RoutedPolicyAnswerProvider,
    _conservative_prompt_token_bound,
    _prompt_messages,
    _usage_from_mapping,
    build_provider_adapter,
)
from backend.app.config import ResolveAISettings
from backend.app.rag.models import PolicyEvidence


EVIDENCE = PolicyEvidence(
    document_id="delivery-policy",
    document_version="v1",
    section="Delayed shipments",
    release_id="release-1",
    visibility="public",
    score=0.91,
    text="If a shipment is delayed, customers may contact support for an updated estimate.",
)
PROMPT = PolicyAnswerPrompt(
    query="What should I do about a delayed shipment?",
    evidence=[
        AuthorizedPolicyEvidence(
            citation_id="evidence-1",
            evidence=EVIDENCE,
            answer_text="If a shipment is delayed, contact support for an updated estimate.",
        )
    ],
)
EXPECTED = {"answer": "If a shipment is delayed, contact support for an updated estimate.", "citation_ids": ["evidence-1"]}


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_compatible_adapters_cover_groq_openrouter_agnes_chutes_and_modelscope() -> None:
    providers = {
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "openrouter": "https://openrouter.ai/api/v1/chat/completions",
        "agnes": "https://apihub.agnes-ai.com/v1/chat/completions",
        "chutes": "https://llm.chutes.ai/v1/chat/completions",
        "modelscope": "https://models.example.test/v1/chat/completions",
    }
    for provider, expected_url in providers.items():
        seen = []

        def handler(request: httpx.Request, *, expected_url=expected_url, seen=seen):
            seen.append(request)
            assert str(request.url) == expected_url
            assert request.headers["authorization"] == "Bearer secret-value"
            body = request.read()
            payload = json.loads(body)
            assert payload["max_tokens"] == 256
            assert b"customer_id" not in body
            assert b"order_id" not in body
            assert b"secret-value" not in body
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"answer":"If a shipment is delayed, contact support for an updated estimate.","citation_ids":["evidence-1"]}'}},
                    ],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 9, "total_tokens": 17},
                },
                headers={"X-RateLimit-Remaining": "4"},
                request=request,
            )

        if provider == "modelscope":
            adapter = ModelScopePolicyAnswerProvider(
                "model-a",
                "secret-value",
                base_url="https://models.example.test/v1",
                allowed_hosts={"models.example.test"},
                client=_client(handler),
            )
        else:
            adapter = OpenAICompatiblePolicyAnswerProvider(
                provider, "model-a", "secret-value", client=_client(handler)
            )
        assert adapter.generate(PROMPT) == EXPECTED
        assert adapter.last_usage == ProviderUsage(8, 9, 17)
        assert adapter.last_rate_limits is not None
        assert adapter.last_rate_limits.requests_remaining == 4
        assert len(seen) == 1


def test_gemini_adapter_uses_header_key_and_native_response_shape() -> None:
    def handler(request: httpx.Request):
        assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
        assert request.headers["x-goog-api-key"] == "secret-value"
        assert "key=" not in str(request.url)
        body = request.read()
        assert json.loads(body)["generationConfig"]["maxOutputTokens"] == 256
        assert b"customer_id" not in body
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"answer":"If a shipment is delayed, contact support for an updated estimate.","citation_ids":["evidence-1"]}'}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 8, "totalTokenCount": 18},
            },
            request=request,
        )

    adapter = GeminiPolicyAnswerProvider("gemini-test", "secret-value", client=_client(handler))
    assert adapter.generate(PROMPT) == EXPECTED
    assert adapter.last_usage == ProviderUsage(10, 8, 18)


def test_cloudflare_adapter_uses_account_scoped_path_and_parses_result() -> None:
    def handler(request: httpx.Request):
        assert str(request.url) == "https://api.cloudflare.com/client/v4/accounts/account-1/ai/run/@cf/model"
        assert request.headers["authorization"] == "Bearer secret-value"
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "response": '{"answer":"If a shipment is delayed, contact support for an updated estimate.","citation_ids":["evidence-1"]}',
                    "usage": {"total_tokens": 14},
                },
            },
            request=request,
        )

    adapter = CloudflareWorkersAIPolicyAnswerProvider(
        "@cf/model", "account-1", "secret-value", client=_client(handler)
    )
    assert adapter.generate(PROMPT) == EXPECTED
    assert adapter.last_usage == ProviderUsage(None, None, 14)


def test_provider_failures_are_sanitized_and_rate_limits_are_exposed() -> None:
    def handler(request: httpx.Request):
        return httpx.Response(
            429,
            headers={"Retry-After": "3"},
            json={"error": "secret-value should never be exposed"},
            request=request,
        )

    adapter = OpenAICompatiblePolicyAnswerProvider("groq", "model-a", "secret-value", client=_client(handler))
    with pytest.raises(ProviderRequestError) as error:
        adapter.generate(PROMPT)
    assert error.value.kind == "rate_limited"
    assert error.value.retry_after_seconds == 3
    assert "secret-value" not in str(error.value)
    assert "should never be exposed" not in str(error.value)


def test_authentication_failures_are_classified_without_echoing_provider_data() -> None:
    def handler(request: httpx.Request):
        return httpx.Response(401, json={"error": "invalid secret-value"}, request=request)

    adapter = OpenAICompatiblePolicyAnswerProvider("groq", "model-a", "secret-value", client=_client(handler))
    with pytest.raises(ProviderRequestError) as error:
        adapter.generate(PROMPT)
    assert error.value.kind == "auth"
    assert "secret-value" not in str(error.value)


def test_timeout_is_safe_and_invalid_json_is_rejected() -> None:
    def timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("provider timed out", request=request)

    adapter = GeminiPolicyAnswerProvider("gemini-test", "secret-value", client=_client(timeout_handler))
    with pytest.raises(ProviderRequestError, match="timeout"):
        adapter.generate(PROMPT)

    def invalid_handler(request: httpx.Request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}, request=request)

    invalid = OpenAICompatiblePolicyAnswerProvider("groq", "model-a", "secret-value", client=_client(invalid_handler))
    with pytest.raises(ProviderRequestError, match="invalid_response"):
        invalid.generate(PROMPT)


def test_provider_usage_handles_missing_or_incomplete_totals_without_double_counting() -> None:
    nested = _usage_from_mapping(
        {
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "total_tokens": 18,
            "completion_tokens_details": {"reasoning_tokens": 3},
            "prompt_tokens_details": {"cached_tokens": 2},
        }
    )
    assert nested.reasoning_tokens == 3
    assert nested.cached_tokens == 2
    assert nested.accounted_tokens == 18

    missing_total = _usage_from_mapping(
        {"input_tokens": 10, "output_tokens": 8, "reasoning_tokens": 3, "other_tokens": 2}
    )
    assert missing_total.accounted_tokens == 23

    incomplete_total = ProviderUsage(
        input_tokens=10,
        output_tokens=8,
        total_tokens=5,
        reasoning_tokens=3,
        reasoning_tokens_included=True,
    )
    assert incomplete_total.accounted_tokens == 18


def test_prompt_reservation_uses_utf8_upper_bound_for_unicode_and_json() -> None:
    unicode_prompt = PolicyAnswerPrompt(
        query="আমি কি এই অর্ডারটি ফেরত দিতে পারি? 🛍️",
        evidence=PROMPT.evidence,
    )
    system, user = _prompt_messages(unicode_prompt)
    assert _conservative_prompt_token_bound(unicode_prompt) >= len(
        (system + "\n" + user).encode("utf-8")
    )


def test_missing_usage_is_explicitly_unknown_and_provider_failures_keep_estimate() -> None:
    assert _usage_from_mapping(None).usage_unknown is True

    def timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("provider timed out", request=request)

    adapter = GeminiPolicyAnswerProvider("gemini-test", "secret-value", client=_client(timeout_handler))
    with pytest.raises(ProviderRequestError) as error:
        adapter.generate(PROMPT)
    assert error.value.usage_unknown is True
    assert error.value.usage is adapter.last_usage
    assert error.value.usage is not None
    assert error.value.usage.accounted_tokens >= 256


def test_malformed_response_preserves_authoritative_usage_for_caller() -> None:
    def invalid_handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "choices": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8},
            },
            request=request,
        )

    adapter = OpenAICompatiblePolicyAnswerProvider("groq", "model-a", "secret-value", client=_client(invalid_handler))
    with pytest.raises(ProviderRequestError) as error:
        adapter.generate(PROMPT)
    assert error.value.usage_unknown is False
    assert error.value.usage is not None
    assert error.value.usage.accounted_tokens == 18


@pytest.mark.parametrize(
    "base_url",
    [
        "http://models.example.test/v1",
        "https://127.0.0.1/v1",
        "https://169.254.169.254/v1",
        "https://metadata.google.internal/v1",
        "https://arbitrary.example/v1",
    ],
)
def test_configurable_endpoints_reject_unsafe_or_unverified_hosts(base_url: str) -> None:
    with pytest.raises(ProviderConfigurationError):
        ModelScopePolicyAnswerProvider("model-a", "secret-value", base_url=base_url)


def test_configurable_endpoint_test_allowlist_is_explicit_and_https_only() -> None:
    adapter = ModelScopePolicyAnswerProvider(
        "model-a",
        "secret-value",
        base_url="https://models.example.test/v1",
        allowed_hosts={"models.example.test"},
        client=_client(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json_text(EXPECTED)}}],
                    "usage": {"total_tokens": 12},
                },
                request=request,
            )
        ),
    )
    assert adapter.generate(PROMPT) == EXPECTED

    with pytest.raises(ProviderConfigurationError):
        OpenAICompatiblePolicyAnswerProvider(
            "groq",
            "model-a",
            "secret-value",
            base_url="https://arbitrary.example/v1",
            allowed_hosts=None,
        )


def test_factory_keeps_external_inference_fail_closed_by_default() -> None:
    settings = ResolveAISettings(_env_file=None, groq_api_key="secret-value", groq_model="model-a")
    with pytest.raises(ProviderConfigurationError, match="disabled"):
        build_provider_adapter("groq", "model-a", settings)


def test_routed_provider_uses_registry_quota_and_reports_usage() -> None:
    registry = ModelRegistry()
    descriptor = ModelDescriptor(
        provider="groq",
        model_id="model-a",
        capabilities=frozenset({"structured_outputs", "text"}),
        structured_output_supported=True,
        free_eligible=True,
        privacy_eligible=True,
        quota_scope="groq:model-a",
    )
    registry.upsert_discovered([descriptor])
    registry.admit(
        descriptor.model_key,
        descriptor,
        QualificationEvidence(
            structured_output_compliance=1,
            supported_answer_accuracy=0.95,
            citation_validity=1,
            unsupported_safety=1,
            false_acceptance=0,
            wrong_version_exposure=0,
            p95_latency_ms=50,
            evaluation_version="dev-1",
        ),
    )
    registry.activate(descriptor.model_key)
    ledger = QuotaLedger()
    ledger.configure_scope(
        descriptor.quota_scope,
        provider="groq",
        request_limit=2,
        token_limit=4_000,
        concurrency_limit=1,
        reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    router = AdaptiveModelRouter(registry, ledger)
    adapter = OpenAICompatiblePolicyAnswerProvider(
        "groq",
        "model-a",
        "secret-value",
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": json_text(EXPECTED)}}], "usage": {"total_tokens": 12}},
                request=request,
            )
        ),
    )
    provider = RoutedPolicyAnswerProvider(router, {descriptor.model_key: adapter})
    assert provider.generate(PROMPT) == EXPECTED
    assert provider.last_model_key == descriptor.model_key
    assert provider.last_usage is not None
    assert ledger.snapshot(descriptor.quota_scope).requests_used == 1
    assert ledger.snapshot(descriptor.quota_scope).tokens_used == 12


def test_routed_provider_failure_retains_conservative_reserved_usage() -> None:
    registry = ModelRegistry()
    descriptor = ModelDescriptor(
        provider="groq",
        model_id="model-failure",
        capabilities=frozenset({"structured_outputs", "text"}),
        structured_output_supported=True,
        free_eligible=True,
        privacy_eligible=True,
        quota_scope="groq:model-failure",
    )
    registry.upsert_discovered([descriptor])
    registry.admit(
        descriptor.model_key,
        descriptor,
        QualificationEvidence(
            structured_output_compliance=1,
            supported_answer_accuracy=0.95,
            citation_validity=1,
            unsupported_safety=1,
            false_acceptance=0,
            wrong_version_exposure=0,
            p95_latency_ms=50,
            evaluation_version="dev-1",
        ),
    )
    registry.activate(descriptor.model_key)
    ledger = QuotaLedger()
    ledger.configure_scope(
        descriptor.quota_scope,
        provider="groq",
        request_limit=2,
        token_limit=2_000,
        concurrency_limit=1,
        reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    def timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("provider timed out", request=request)

    provider = RoutedPolicyAnswerProvider(
        AdaptiveModelRouter(registry, ledger),
        {
            descriptor.model_key: OpenAICompatiblePolicyAnswerProvider(
                "groq", "model-failure", "secret-value", client=_client(timeout_handler)
            )
        },
    )
    with pytest.raises(ProviderRequestError, match="timeout"):
        provider.generate(PROMPT)
    snapshot = ledger.snapshot(descriptor.quota_scope)
    assert snapshot.requests_used == 1
    assert snapshot.tokens_used >= 256
    assert snapshot.tokens_used < 2_000
    assert snapshot.in_flight == 0


def json_text(value: Mapping[str, object]) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))
