"""Credential-gated HTTP inference adapters and routed provider boundary.

The adapters in this module are deliberately inert until ``generate`` is
called with an explicitly configured provider.  They receive only the
server-authorized :class:`PolicyAnswerPrompt`; the answer layer remains the
final citation and evidence validator.  No adapter logs credentials or
provider response bodies.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping, Protocol
from urllib.parse import quote

import httpx

from backend.app.ai.generation import GeneratedPolicyAnswer, PolicyAnswerPrompt
from backend.app.ai.model_control import (
    AdaptiveModelRouter,
    RateLimitMetadata,
    RouteRequest,
    parse_rate_limit_headers,
)
from backend.app.config import ProviderName, ResolveAISettings


OPENAI_COMPATIBLE_BASE_URLS: Mapping[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "agnes": "https://apihub.agnes-ai.com/v1",
    "chutes": "https://llm.chutes.ai/v1",
}
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_CLOUDFLARE_BASE_URL = "https://api.cloudflare.com/client/v4"


class ProviderConfigurationError(ValueError):
    """Raised when a provider is not completely configured for a request."""


class ProviderRequestError(RuntimeError):
    """Safe provider failure with no credential or response-body disclosure."""

    def __init__(
        self,
        provider: str,
        kind: str,
        *,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.provider = provider
        self.kind = kind
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        suffix = f" status={status_code}" if status_code is not None else ""
        super().__init__(f"{provider} provider request failed: {kind}{suffix}")


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated: bool = False

    @property
    def accounted_tokens(self) -> int:
        for value in (self.total_tokens, self.input_tokens, self.output_tokens):
            if value is not None and value >= 0:
                return value
        return 0


class ProviderAdapter(Protocol):
    provider: ProviderName
    model_id: str
    last_usage: ProviderUsage | None
    last_rate_limits: RateLimitMetadata | None

    def generate(self, prompt: PolicyAnswerPrompt) -> object:
        """Return a parsed provider candidate for the existing answer validator."""


def _prompt_messages(prompt: PolicyAnswerPrompt) -> tuple[str, str]:
    """Serialize only the server-authorized prompt fields for remote inference."""

    evidence = [
        {
            "citation_id": item.citation_id,
            "policy_text": item.evidence.text,
            "server_answer_text": item.answer_text,
        }
        for item in prompt.evidence
    ]
    user_payload = json.dumps(
        {"query": prompt.query, "evidence": evidence},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    system = (
        f"{prompt.system_instruction}\n\n"
        "Return exactly one JSON object with keys answer and citation_ids."
    )
    return system, user_payload


def _parse_json_candidate(value: object) -> object:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        raise ValueError("provider response content is not JSON text")
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError) as error:
        raise ValueError("provider response is not valid JSON") from error
    if not isinstance(parsed, Mapping):
        raise ValueError("provider response must be a JSON object")
    return dict(parsed)


def _token_count(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _usage_from_mapping(value: object, *, estimated: bool = False) -> ProviderUsage:
    if not isinstance(value, Mapping):
        return ProviderUsage(estimated=estimated)
    input_tokens = _token_count(
        value.get("prompt_tokens", value.get("promptTokenCount"))
    )
    output_tokens = _token_count(
        value.get("completion_tokens", value.get("candidatesTokenCount"))
    )
    total_tokens = _token_count(value.get("total_tokens", value.get("totalTokenCount")))
    return ProviderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated=estimated,
    )


class _HTTPProvider:
    provider: ProviderName

    def __init__(
        self,
        provider: ProviderName,
        model_id: str,
        *,
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not model_id.strip():
            raise ProviderConfigurationError("model_id is required")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ProviderConfigurationError("timeout_seconds must be positive")
        self.provider = provider
        self.model_id = model_id.strip()
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.Client()
        self._owns_client = client is None
        self.last_usage: ProviderUsage | None = None
        self.last_rate_limits: RateLimitMetadata | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _post(self, url: str, *, headers: Mapping[str, str], payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(
                url,
                headers=dict(headers),
                json=dict(payload),
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise ProviderRequestError(self.provider, "timeout") from error
        except httpx.HTTPError as error:
            raise ProviderRequestError(self.provider, "unavailable") from error

        self.last_rate_limits = parse_rate_limit_headers(response.headers)
        if response.status_code >= 400:
            if response.status_code in {401, 403}:
                kind = "auth"
            elif response.status_code == 429:
                kind = "rate_limited"
            else:
                kind = "http_error"
            raise ProviderRequestError(
                self.provider,
                kind,
                status_code=response.status_code,
                retry_after_seconds=self.last_rate_limits.retry_after_seconds,
            )
        try:
            body = response.json()
        except ValueError as error:
            raise ProviderRequestError(self.provider, "invalid_response") from error
        if not isinstance(body, Mapping):
            raise ProviderRequestError(self.provider, "invalid_response")
        return dict(body)

    def _record_fallback_usage(self, prompt: PolicyAnswerPrompt, output: object) -> None:
        if self.last_usage is not None and self.last_usage.accounted_tokens > 0:
            return
        output_size = len(output) if isinstance(output, str) else len(json.dumps(output))
        self.last_usage = ProviderUsage(
            input_tokens=len(prompt.query.split()),
            output_tokens=max(1, output_size // 4),
            estimated=True,
        )


class OpenAICompatiblePolicyAnswerProvider(_HTTPProvider):
    """HTTP adapter for providers exposing the OpenAI chat-completions shape."""

    def __init__(
        self,
        provider: ProviderName,
        model_id: str,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        if provider not in {"groq", "openrouter", "agnes", "chutes", "modelscope"}:
            raise ProviderConfigurationError("provider is not OpenAI-compatible")
        if not api_key.strip():
            raise ProviderConfigurationError("provider credential is required")
        if base_url is None:
            base_url = OPENAI_COMPATIBLE_BASE_URLS.get(provider)
        if not base_url:
            raise ProviderConfigurationError("an explicit provider base URL is required")
        super().__init__(provider, model_id, timeout_seconds=timeout_seconds, client=client)
        self._endpoint = base_url.rstrip("/")
        if not self._endpoint.endswith("/chat/completions"):
            self._endpoint += "/chat/completions"
        self._api_key = api_key

    def generate(self, prompt: PolicyAnswerPrompt) -> object:
        system, user = _prompt_messages(prompt)
        body = self._post(
            self._endpoint,
            headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
            payload={
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise ProviderRequestError(self.provider, "invalid_response")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) for item in content if isinstance(item, Mapping)
            )
        try:
            result = _parse_json_candidate(content)
        except ValueError as error:
            raise ProviderRequestError(self.provider, "invalid_response") from error
        self.last_usage = _usage_from_mapping(body.get("usage"))
        self._record_fallback_usage(prompt, content)
        return result


class ModelScopePolicyAnswerProvider(OpenAICompatiblePolicyAnswerProvider):
    """ModelScope adapter; the endpoint is explicit because no catalog URL is assumed."""

    def __init__(self, model_id: str, api_key: str, *, base_url: str, **kwargs: Any) -> None:
        super().__init__("modelscope", model_id, api_key, base_url=base_url, **kwargs)


class GeminiPolicyAnswerProvider(_HTTPProvider):
    """Native Gemini ``generateContent`` adapter with API key headers only."""

    def __init__(
        self,
        model_id: str,
        api_key: str,
        *,
        base_url: str = DEFAULT_GEMINI_BASE_URL,
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ProviderConfigurationError("provider credential is required")
        super().__init__("gemini", model_id, timeout_seconds=timeout_seconds, client=client)
        self._api_key = api_key
        self._endpoint = (
            f"{base_url.rstrip('/')}/models/{quote(self.model_id, safe='')}:generateContent"
        )

    def generate(self, prompt: PolicyAnswerPrompt) -> object:
        system, user = _prompt_messages(prompt)
        body = self._post(
            self._endpoint,
            headers={"x-goog-api-key": self._api_key, "Accept": "application/json"},
            payload={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
            },
        )
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], Mapping):
            raise ProviderRequestError(self.provider, "invalid_response")
        content = candidates[0].get("content")
        parts = content.get("parts") if isinstance(content, Mapping) else None
        text = "".join(
            str(item.get("text", "")) for item in parts or () if isinstance(item, Mapping)
        )
        try:
            result = _parse_json_candidate(text)
        except ValueError as error:
            raise ProviderRequestError(self.provider, "invalid_response") from error
        self.last_usage = _usage_from_mapping(body.get("usageMetadata"))
        self._record_fallback_usage(prompt, text)
        return result


class CloudflareWorkersAIPolicyAnswerProvider(_HTTPProvider):
    """Cloudflare Workers AI adapter using account-scoped REST inference."""

    def __init__(
        self,
        model_id: str,
        account_id: str,
        api_token: str,
        *,
        base_url: str = DEFAULT_CLOUDFLARE_BASE_URL,
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not account_id.strip() or not api_token.strip():
            raise ProviderConfigurationError("Cloudflare account and credential are required")
        super().__init__("cloudflare", model_id, timeout_seconds=timeout_seconds, client=client)
        self._api_token = api_token
        self._endpoint = (
            f"{base_url.rstrip('/')}/accounts/{quote(account_id, safe='')}/ai/run/"
            f"{quote(self.model_id, safe='/@')}"
        )

    def generate(self, prompt: PolicyAnswerPrompt) -> object:
        system, user = _prompt_messages(prompt)
        body = self._post(
            self._endpoint,
            headers={"Authorization": f"Bearer {self._api_token}", "Accept": "application/json"},
            payload={
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        result = body.get("result")
        content: object
        usage: object = body.get("usage")
        if isinstance(result, Mapping):
            content = result.get("response", result.get("output", result))
            usage = result.get("usage", usage)
        else:
            content = result
        try:
            parsed = _parse_json_candidate(content)
        except ValueError as error:
            raise ProviderRequestError(self.provider, "invalid_response") from error
        self.last_usage = _usage_from_mapping(usage)
        self._record_fallback_usage(prompt, content)
        return parsed


def _provider_secret(settings: ResolveAISettings, provider: ProviderName) -> str | None:
    if provider == "cloudflare":
        return settings.cloudflare_api_token.get_secret_value() if settings.cloudflare_api_token else None
    value = getattr(settings, f"{provider}_api_key", None)
    return value.get_secret_value() if value is not None else None


def build_provider_adapter(
    provider: ProviderName,
    model_id: str,
    settings: ResolveAISettings,
    *,
    client: httpx.Client | None = None,
    modelscope_base_url: str | None = None,
) -> ProviderAdapter:
    """Build one adapter only when the global zero-cost gates explicitly allow it."""

    if not settings.external_inference_enabled or settings.zero_cost_mode:
        raise ProviderConfigurationError("external inference is disabled by safety policy")
    if settings.provider_request_quota <= 0 or settings.provider_token_quota <= 0:
        raise ProviderConfigurationError("provider quotas must be positive")
    if not getattr(settings, f"{provider}_enabled"):
        raise ProviderConfigurationError("provider is disabled")
    secret = _provider_secret(settings, provider)
    if provider == "cloudflare":
        if secret is None or settings.cloudflare_account_id is None:
            raise ProviderConfigurationError("Cloudflare credentials are incomplete")
        return CloudflareWorkersAIPolicyAnswerProvider(
            model_id,
            settings.cloudflare_account_id.get_secret_value(),
            secret,
            timeout_seconds=settings.provider_timeout_seconds,
            client=client,
        )
    if secret is None:
        raise ProviderConfigurationError("provider credential is missing")
    if provider == "gemini":
        return GeminiPolicyAnswerProvider(
            model_id,
            secret,
            timeout_seconds=settings.provider_timeout_seconds,
            client=client,
        )
    if provider == "modelscope":
        if not modelscope_base_url:
            raise ProviderConfigurationError("ModelScope requires an explicit base URL")
        return ModelScopePolicyAnswerProvider(
            model_id,
            secret,
            base_url=modelscope_base_url,
            timeout_seconds=settings.provider_timeout_seconds,
            client=client,
        )
    return OpenAICompatiblePolicyAnswerProvider(
        provider,
        model_id,
        secret,
        timeout_seconds=settings.provider_timeout_seconds,
        client=client,
    )


class RoutedPolicyAnswerProvider:
    """Connect the durable router to the existing validated answer boundary."""

    def __init__(
        self,
        router: AdaptiveModelRouter,
        adapters: Mapping[str, ProviderAdapter],
        *,
        task_category: str = "policy_answer",
        estimated_tokens: int = 256,
        deadline_ms: float | None = None,
    ) -> None:
        if estimated_tokens <= 0:
            raise ValueError("estimated_tokens must be positive")
        self._router = router
        self._adapters = dict(adapters)
        self._task_category = task_category
        self._estimated_tokens = estimated_tokens
        self._deadline_ms = deadline_ms
        self.last_usage: ProviderUsage | None = None
        self.last_model_key: str | None = None

    def generate(self, prompt: PolicyAnswerPrompt) -> object:
        started = perf_counter()
        decision = self._router.select(
            RouteRequest(
                task_category=self._task_category,
                estimated_tokens=self._estimated_tokens,
                deadline_ms=self._deadline_ms,
            )
        )
        if decision is None:
            raise ProviderRequestError("router", "no_qualified_capacity")
        adapter = self._adapters.get(decision.model_key)
        if adapter is None:
            self._router.report_failure(decision, failure_kind="configuration", dispatched=False)
            raise ProviderRequestError(decision.provider, "adapter_unavailable")
        self.last_model_key = decision.model_key
        try:
            output = adapter.generate(prompt)
        except ProviderRequestError as error:
            self._router.report_failure(
                decision,
                failure_kind=error.kind,
                retry_after_seconds=error.retry_after_seconds or 0,
            )
            raise
        except Exception as error:
            self._router.report_failure(decision, failure_kind="provider")
            raise ProviderRequestError(decision.provider, "unavailable") from error
        try:
            GeneratedPolicyAnswer.model_validate(output)
        except Exception as error:
            self._router.report_failure(decision, failure_kind="invalid_response")
            raise ProviderRequestError(decision.provider, "invalid_response") from error
        usage = getattr(adapter, "last_usage", None)
        self.last_usage = usage if isinstance(usage, ProviderUsage) else None
        self._router.report_success(
            decision,
            actual_tokens=(usage.accounted_tokens if isinstance(usage, ProviderUsage) else self._estimated_tokens),
            latency_ms=(perf_counter() - started) * 1000,
        )
        return output


__all__ = [
    "CloudflareWorkersAIPolicyAnswerProvider",
    "DEFAULT_CLOUDFLARE_BASE_URL",
    "DEFAULT_GEMINI_BASE_URL",
    "GeminiPolicyAnswerProvider",
    "ModelScopePolicyAnswerProvider",
    "OPENAI_COMPATIBLE_BASE_URLS",
    "OpenAICompatiblePolicyAnswerProvider",
    "ProviderAdapter",
    "ProviderConfigurationError",
    "ProviderRequestError",
    "ProviderUsage",
    "RoutedPolicyAnswerProvider",
    "build_provider_adapter",
]
