"""Credential-gated model discovery, qualification, quota and routing control.

This module is deliberately separate from the customer answer path.  Discovery
and routing are explicit services; importing the module never performs network
I/O or enables a provider.  A discovered model is unverified until an
independently measured qualification result admits it.
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Mapping, Sequence

import httpx
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from backend.app.config import ProviderName, ResolveAISettings
from backend.app.db.conversations import Base, create_database_engine


MODEL_STATES = frozenset(
    {
        "DISCOVERED",
        "UNVERIFIED",
        "QUALIFIED",
        "ACTIVE",
        "DEGRADED",
        "RATE_LIMITED",
        "QUARANTINED",
        "DISABLED",
        "DEPRECATED",
    }
)
HEALTH_STATES = frozenset({"HEALTHY", "DEGRADED", "RATE_LIMITED", "QUARANTINED"})


class ModelControlError(RuntimeError):
    """Base class for safe model-control failures."""


class DiscoveryUnavailable(ModelControlError):
    """A catalog cannot be queried under the current safe configuration."""


class QualificationRejected(ModelControlError):
    """A model did not satisfy the independent quality and safety gate."""


class QuotaUnavailable(ModelControlError):
    """No verified quota window is available for a request."""


class QuotaExceeded(ModelControlError):
    """A verified quota or concurrency window cannot admit a request."""


class ModelNotRoutable(ModelControlError):
    """A model is not qualified, active, healthy, private, or affordable."""


@dataclass(frozen=True)
class ProviderSpec:
    provider: ProviderName
    discovery_endpoint: str | None
    auth_header: str | None
    requires_credential: bool
    source: str
    static_catalog_reason: str | None = None


@dataclass(frozen=True)
class RateLimitMetadata:
    request_limit: int | None = None
    requests_remaining: int | None = None
    reset_at: datetime | None = None
    retry_after_seconds: float | None = None


def parse_rate_limit_headers(headers: Mapping[str, str], *, now: datetime | None = None) -> RateLimitMetadata:
    """Parse common provider quota headers without assuming a provider contract."""

    lowered = {str(key).casefold(): str(value) for key, value in headers.items()}

    def integer(*names: str) -> int | None:
        for name in names:
            value = lowered.get(name)
            if value is None:
                continue
            try:
                parsed = int(value)
            except ValueError:
                continue
            if parsed >= 0:
                return parsed
        return None

    retry_after: float | None = None
    raw_retry = lowered.get("retry-after")
    if raw_retry is not None:
        try:
            retry_after = max(0.0, float(raw_retry))
        except ValueError:
            retry_after = None
    reset_at: datetime | None = None
    raw_reset = lowered.get("x-ratelimit-reset") or lowered.get("x-rate-limit-reset")
    if raw_reset is not None:
        try:
            reset_value = float(raw_reset)
            if reset_value > 10_000_000:
                reset_at = datetime.fromtimestamp(reset_value, tz=timezone.utc)
            else:
                reset_at = _utc(now or datetime.now(timezone.utc)) + timedelta(seconds=max(0, reset_value))
        except (TypeError, ValueError, OverflowError, OSError):
            reset_at = None
    return RateLimitMetadata(
        request_limit=integer("x-ratelimit-limit", "x-rate-limit-limit"),
        requests_remaining=integer("x-ratelimit-remaining", "x-rate-limit-remaining"),
        reset_at=reset_at,
        retry_after_seconds=retry_after,
    )


PROVIDER_SPECS: Mapping[ProviderName, ProviderSpec] = {
    "groq": ProviderSpec(
        "groq",
        "https://api.groq.com/openai/v1/models",
        "authorization",
        True,
        "official Groq Models API",
    ),
    "gemini": ProviderSpec(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/models",
        "x-goog-api-key",
        True,
        "official Gemini Models API",
    ),
    "openrouter": ProviderSpec(
        "openrouter",
        "https://openrouter.ai/api/v1/models",
        "authorization",
        True,
        "official OpenRouter Models API",
    ),
    "cloudflare": ProviderSpec(
        "cloudflare",
        None,
        "authorization",
        True,
        "official Workers AI model catalog",
        "No verified general model-list endpoint is configured; use an explicitly reviewed catalog.",
    ),
    "modelscope": ProviderSpec(
        "modelscope",
        None,
        "authorization",
        True,
        "official ModelScope model catalog",
        "No verified provider model-list endpoint is configured; use an explicitly reviewed catalog.",
    ),
    "agnes": ProviderSpec(
        "agnes",
        "https://apihub.agnes-ai.com/v1/models",
        "authorization",
        True,
        "Agnes OpenAI-compatible model endpoint",
    ),
    "chutes": ProviderSpec(
        "chutes",
        "https://llm.chutes.ai/v1/models",
        "authorization",
        False,
        "official Chutes model endpoint",
    ),
}


@dataclass(frozen=True)
class ModelDescriptor:
    provider: ProviderName
    model_id: str
    display_name: str = ""
    capabilities: frozenset[str] = field(default_factory=frozenset)
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    structured_output_supported: bool | None = None
    free_eligible: bool | None = None
    pricing: tuple[tuple[str, float], ...] = ()
    rate_limits: tuple[tuple[str, float], ...] = ()
    privacy_eligible: bool = False
    available: bool = True
    deprecated: bool = False
    upstream_provider: str | None = None
    quota_scope: str | None = None
    catalog_version: str = "unknown"

    @property
    def model_key(self) -> str:
        return f"{self.provider}:{self.model_id}"


def _number(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _price_values(value: Any) -> list[float]:
    values: list[float] = []
    if isinstance(value, Mapping):
        for item in value.values():
            values.extend(_price_values(item))
    elif isinstance(value, (int, float)) and math.isfinite(float(value)):
        values.append(float(value))
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return values
        if math.isfinite(number):
            values.append(number)
    return values


def _numeric_pairs(value: Any, prefix: str = "") -> tuple[tuple[str, float], ...]:
    pairs: list[tuple[str, float]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            pairs.extend(_numeric_pairs(item, child_prefix))
    elif isinstance(value, (int, float)) and math.isfinite(float(value)):
        pairs.append((prefix, float(value)))
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return tuple(pairs)
        if math.isfinite(number):
            pairs.append((prefix, number))
    return tuple(pairs)


def _free_status(item: Mapping[str, Any]) -> bool | None:
    if isinstance(item.get("free"), bool):
        return bool(item["free"])
    pricing = item.get("pricing", item.get("price"))
    if pricing is None:
        return None
    values = _price_values(pricing)
    if not values:
        return None
    return all(value == 0 for value in values)


def _structured_status(item: Mapping[str, Any]) -> bool | None:
    for key in ("structured_output_supported", "supports_structured_output"):
        if isinstance(item.get(key), bool):
            return item[key]
    features: list[str] = []
    for key in ("supported_features", "supportedGenerationMethods", "capabilities"):
        value = item.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            features.extend(str(part).casefold() for part in value)
    if any("structured" in feature or "json_mode" in feature for feature in features):
        return True
    return None


def _normalize_model(provider: ProviderName, item: Mapping[str, Any], catalog_version: str) -> ModelDescriptor | None:
    model_id = item.get("id") or item.get("baseModelId") or item.get("name")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    model_id = model_id.removeprefix("models/").strip()
    capabilities = set()
    for key in ("supported_features", "supportedGenerationMethods", "modalities"):
        value = item.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            capabilities.update(str(part).casefold() for part in value)
    status = str(item.get("status", "")).casefold()
    deprecated = bool(item.get("deprecated", False)) or status in {"deprecated", "retired"}
    available = item.get("available", True) is not False and not deprecated
    display_name = item.get("displayName") or item.get("name") or model_id
    upstream = item.get("owned_by") or item.get("provider") or item.get("upstream_provider")
    return ModelDescriptor(
        provider=provider,
        model_id=model_id,
        display_name=str(display_name),
        capabilities=frozenset(capabilities),
        input_token_limit=_number(
            item.get("inputTokenLimit")
            or item.get("context_length")
            or item.get("max_model_len")
        ),
        output_token_limit=_number(item.get("outputTokenLimit") or item.get("max_output_length")),
        structured_output_supported=_structured_status(item),
        free_eligible=_free_status(item),
        pricing=_numeric_pairs(item.get("pricing", item.get("price"))),
        rate_limits=_numeric_pairs(item.get("rate_limits", item.get("limits"))),
        privacy_eligible=bool(item.get("privacy_eligible", False)),
        available=available,
        deprecated=deprecated,
        upstream_provider=str(upstream) if upstream else None,
        quota_scope=str(item.get("quota_scope") or provider),
        catalog_version=catalog_version,
    )


def _payload_items(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("data", "models", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


class ModelDiscoveryService:
    """Discover provider metadata only when explicitly enabled by settings."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        static_catalog: Mapping[ProviderName, Sequence[ModelDescriptor]] | None = None,
    ) -> None:
        self._client = client or httpx.Client()
        self._static_catalog = {
            provider: tuple(entries)
            for provider, entries in (static_catalog or {}).items()
        }
        self._cache: dict[ProviderName, tuple[datetime, tuple[ModelDescriptor, ...]]] = {}
        self._cache_lock = threading.RLock()

    def discover(
        self,
        provider: ProviderName,
        settings: ResolveAISettings,
        *,
        catalog_version: str = "runtime",
    ) -> tuple[ModelDescriptor, ...]:
        spec = PROVIDER_SPECS[provider]
        if not settings.model_discovery_enabled:
            raise DiscoveryUnavailable("model discovery is disabled")
        now = datetime.now(timezone.utc)
        with self._cache_lock:
            cached = self._cache.get(provider)
            if cached is not None and cached[0] > now:
                return cached[1]
        if spec.discovery_endpoint is None:
            entries = self._static_catalog.get(provider, ())
            with self._cache_lock:
                self._cache[provider] = (now + timedelta(seconds=settings.model_catalog_ttl_seconds), entries)
            return entries
        if spec.requires_credential and not _provider_credential_present(settings, provider):
            raise DiscoveryUnavailable("provider discovery credentials are not configured")
        headers: dict[str, str] = {"Accept": "application/json"}
        credential = _provider_credential(settings, provider)
        if credential:
            if spec.auth_header == "authorization":
                headers["Authorization"] = f"Bearer {credential}"
            else:
                headers[spec.auth_header or "Authorization"] = credential
        try:
            response = self._client.get(spec.discovery_endpoint, headers=headers, timeout=settings.provider_timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise DiscoveryUnavailable("provider model discovery failed") from error
        entries = tuple(
            descriptor
            for item in _payload_items(payload)
            if (descriptor := _normalize_model(provider, item, catalog_version)) is not None
        )
        with self._cache_lock:
            self._cache[provider] = (
                now + timedelta(seconds=settings.model_catalog_ttl_seconds),
                entries,
            )
        return entries

    def refresh(
        self,
        provider: ProviderName,
        settings: ResolveAISettings,
        registry: "ModelRegistry",
        *,
        catalog_version: str = "runtime",
    ) -> tuple[ModelDescriptor, ...]:
        """Discover once per cache window and persist the unverified catalog."""

        entries = self.discover(provider, settings, catalog_version=catalog_version)
        registry.upsert_discovered(entries)
        return entries


def _provider_credential(settings: ResolveAISettings, provider: ProviderName) -> str | None:
    if provider == "cloudflare":
        return settings.cloudflare_api_token.get_secret_value() if settings.cloudflare_api_token else None
    credential = getattr(settings, f"{provider}_api_key", None)
    return credential.get_secret_value() if credential else None


def _provider_credential_present(settings: ResolveAISettings, provider: ProviderName) -> bool:
    if provider == "cloudflare":
        return bool(settings.cloudflare_account_id and settings.cloudflare_api_token)
    return bool(getattr(settings, f"{provider}_api_key", None))


@dataclass(frozen=True)
class QualificationEvidence:
    structured_output_compliance: float
    supported_answer_accuracy: float
    citation_validity: float
    unsupported_safety: float
    false_acceptance: int
    wrong_version_exposure: int
    p95_latency_ms: float
    evaluation_version: str
    approved_task_categories: tuple[str, ...] = ("policy_answer",)


@dataclass(frozen=True)
class QualificationDecision:
    accepted: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class QualificationPolicy:
    min_structured_output_compliance: float = 1.0
    min_supported_answer_accuracy: float = 0.90
    min_citation_validity: float = 0.95
    min_unsupported_safety: float = 1.0
    max_false_acceptance: int = 0
    max_wrong_version_exposure: int = 0

    def decide(self, descriptor: ModelDescriptor, evidence: QualificationEvidence) -> QualificationDecision:
        reasons: list[str] = []
        if descriptor.free_eligible is not True:
            reasons.append("free entitlement is not verified")
        if descriptor.privacy_eligible is not True:
            reasons.append("privacy eligibility is not verified")
        if descriptor.structured_output_supported is not True:
            reasons.append("structured output capability is not verified")
        if not evidence.approved_task_categories:
            reasons.append("no approved task category was recorded")
        if not descriptor.available or descriptor.deprecated:
            reasons.append("model is unavailable or deprecated")
        if evidence.structured_output_compliance < self.min_structured_output_compliance:
            reasons.append("structured output qualification failed")
        if evidence.supported_answer_accuracy < self.min_supported_answer_accuracy:
            reasons.append("supported-answer quality gate failed")
        if evidence.citation_validity < self.min_citation_validity:
            reasons.append("citation validity gate failed")
        if evidence.unsupported_safety < self.min_unsupported_safety:
            reasons.append("unsupported-safety gate failed")
        if evidence.false_acceptance > self.max_false_acceptance:
            reasons.append("false-acceptance gate failed")
        if evidence.wrong_version_exposure > self.max_wrong_version_exposure:
            reasons.append("wrong-version gate failed")
        return QualificationDecision(not reasons, tuple(reasons))


class ModelRegistryRow(Base):
    __tablename__ = "ai_model_registry"
    __table_args__ = (UniqueConstraint("provider", "model_id", name="uq_ai_model_provider_id"),)

    model_key: Mapped[str] = mapped_column(String(384), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    health_state: Mapped[str] = mapped_column(String(32), nullable=False, default="HEALTHY")
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    free_eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    privacy_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    structured_output_supported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pricing_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    rate_limits_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    input_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    upstream_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quota_scope: Mapped[str] = mapped_column(String(255), nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(128), nullable=False)
    evaluation_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    benchmark_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    runtime_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    health_cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuotaWindowRow(Base):
    __tablename__ = "ai_quota_windows"

    scope_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    requests_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_flight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=86_400)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuotaReservationRow(Base):
    __tablename__ = "ai_quota_reservations"

    reservation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    reservation_group: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@dataclass(frozen=True)
class RegisteredModel:
    model_key: str
    provider: ProviderName
    model_id: str
    lifecycle: str
    health_state: str
    available: bool
    deprecated: bool
    free_eligible: bool | None
    privacy_eligible: bool
    structured_output_supported: bool | None
    input_token_limit: int | None
    output_token_limit: int | None
    pricing: tuple[tuple[str, float], ...]
    rate_limits: tuple[tuple[str, float], ...]
    approved_task_categories: frozenset[str]
    capabilities: frozenset[str]
    quota_scope: str
    evaluation_version: str | None
    quality_score: float
    citation_validity: float
    latency_p50_ms: float
    latency_p95_ms: float
    failure_rate: float
    in_flight: int
    health_cooldown_until: datetime | None


def _runtime_metrics(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return round(float(ordered[index]), 3)


class ModelRegistry:
    """Persistent registry with safe lifecycle transitions."""

    def __init__(
        self,
        database_url: str = "sqlite+pysqlite:///:memory:",
        *,
        engine=None,
        initialize_schema: bool | None = None,
    ) -> None:
        self._engine = engine or create_database_engine(database_url)
        if initialize_schema is None:
            initialize_schema = self._engine.dialect.name == "sqlite"
        if initialize_schema:
            Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        self._lock = threading.RLock()

    def upsert_discovered(
        self,
        descriptors: Sequence[ModelDescriptor],
        *,
        discovered_at: datetime | None = None,
    ) -> tuple[str, ...]:
        now = _utc(discovered_at or datetime.now(timezone.utc))
        keys: list[str] = []
        with self._lock, self._session_factory.begin() as session:
            for descriptor in descriptors:
                if descriptor.provider not in PROVIDER_SPECS:
                    continue
                existing = session.get(ModelRegistryRow, descriptor.model_key)
                if existing is None:
                    existing = ModelRegistryRow(
                        model_key=descriptor.model_key,
                        provider=descriptor.provider,
                        model_id=descriptor.model_id,
                        display_name=descriptor.display_name,
                        lifecycle="UNVERIFIED",
                        health_state="HEALTHY",
                        available=descriptor.available,
                        deprecated=descriptor.deprecated,
                        free_eligible=descriptor.free_eligible,
                        privacy_eligible=descriptor.privacy_eligible,
                        structured_output_supported=descriptor.structured_output_supported,
                        pricing_json=json.dumps(dict(descriptor.pricing), sort_keys=True),
                        rate_limits_json=json.dumps(dict(descriptor.rate_limits), sort_keys=True),
                        input_token_limit=descriptor.input_token_limit,
                        output_token_limit=descriptor.output_token_limit,
                        capabilities_json=json.dumps(sorted(descriptor.capabilities)),
                        upstream_provider=descriptor.upstream_provider,
                        quota_scope=descriptor.quota_scope or descriptor.provider,
                        catalog_version=descriptor.catalog_version,
                        benchmark_json="{}",
                        runtime_json="{}",
                        discovered_at=now,
                        updated_at=now,
                    )
                    session.add(existing)
                else:
                    existing.display_name = descriptor.display_name
                    existing.available = descriptor.available
                    existing.deprecated = descriptor.deprecated
                    existing.free_eligible = descriptor.free_eligible
                    existing.privacy_eligible = descriptor.privacy_eligible
                    existing.structured_output_supported = descriptor.structured_output_supported
                    existing.pricing_json = json.dumps(dict(descriptor.pricing), sort_keys=True)
                    existing.rate_limits_json = json.dumps(dict(descriptor.rate_limits), sort_keys=True)
                    existing.input_token_limit = descriptor.input_token_limit
                    existing.output_token_limit = descriptor.output_token_limit
                    existing.capabilities_json = json.dumps(sorted(descriptor.capabilities))
                    existing.upstream_provider = descriptor.upstream_provider
                    existing.quota_scope = descriptor.quota_scope or descriptor.provider
                    existing.catalog_version = descriptor.catalog_version
                    if existing.lifecycle not in {"ACTIVE", "DISABLED", "QUARANTINED"}:
                        existing.lifecycle = "UNVERIFIED"
                    if existing.deprecated:
                        existing.lifecycle = "DEPRECATED"
                    existing.updated_at = now
                keys.append(descriptor.model_key)
        return tuple(keys)

    def get(self, model_key: str) -> RegisteredModel | None:
        with self._session_factory() as session:
            row = session.get(ModelRegistryRow, model_key)
            return _registered_model(row) if row is not None else None

    def list(self) -> tuple[RegisteredModel, ...]:
        with self._session_factory() as session:
            rows = session.scalars(select(ModelRegistryRow).order_by(ModelRegistryRow.model_key)).all()
            return tuple(_registered_model(row) for row in rows)

    def admit(
        self,
        model_key: str,
        descriptor: ModelDescriptor,
        evidence: QualificationEvidence,
        policy: QualificationPolicy | None = None,
    ) -> QualificationDecision:
        decision = (policy or QualificationPolicy()).decide(descriptor, evidence)
        with self._lock, self._session_factory.begin() as session:
            row = session.get(ModelRegistryRow, model_key)
            if row is None or row.provider != descriptor.provider or row.model_id != descriptor.model_id:
                raise ModelControlError("model is not registered")
            row.evaluation_version = evidence.evaluation_version
            row.benchmark_json = json.dumps(asdict(evidence), sort_keys=True)
            if decision.accepted:
                row.lifecycle = "QUALIFIED"
            elif row.lifecycle not in {"ACTIVE", "DISABLED", "QUARANTINED", "DEPRECATED"}:
                row.lifecycle = "UNVERIFIED"
            row.updated_at = datetime.now(timezone.utc)
        if not decision.accepted:
            raise QualificationRejected("; ".join(decision.reasons))
        return decision

    def activate(self, model_key: str) -> None:
        with self._lock, self._session_factory.begin() as session:
            row = session.get(ModelRegistryRow, model_key)
            if row is None or row.lifecycle != "QUALIFIED":
                raise ModelNotRoutable("only a qualified model can become active")
            if not row.free_eligible or not row.privacy_eligible or row.structured_output_supported is not True:
                raise ModelNotRoutable("model safety and cost metadata is incomplete")
            row.lifecycle = "ACTIVE"
            row.health_state = "HEALTHY"
            row.updated_at = datetime.now(timezone.utc)

    def update_runtime(
        self,
        model_key: str,
        *,
        success: bool,
        latency_ms: float | None = None,
        failure_kind: str | None = None,
        cooldown_seconds: float = 0,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._lock, self._session_factory.begin() as session:
            row = session.get(ModelRegistryRow, model_key)
            if row is None:
                raise ModelControlError("model is not registered")
            metrics = _runtime_metrics(row.runtime_json)
            latencies = [float(item) for item in metrics.get("latencies", []) if isinstance(item, (int, float))]
            if latency_ms is not None and math.isfinite(latency_ms) and latency_ms >= 0:
                latencies = (latencies + [latency_ms])[-128:]
            requests = int(metrics.get("requests", 0)) + 1
            failures = int(metrics.get("failures", 0)) + (0 if success else 1)
            consecutive_failures = 0 if success else int(metrics.get("consecutive_failures", 0)) + 1
            metrics.update(
                {
                    "latencies": latencies,
                    "requests": requests,
                    "failures": failures,
                    "failure_rate": failures / requests,
                    "consecutive_failures": consecutive_failures,
                    "last_failure_kind": failure_kind,
                }
            )
            row.runtime_json = json.dumps(metrics, sort_keys=True)
            if success:
                row.health_state = "HEALTHY"
                row.health_cooldown_until = None
                if row.lifecycle in {"DEGRADED", "RATE_LIMITED"}:
                    row.lifecycle = "ACTIVE"
            elif failure_kind == "rate_limited":
                row.health_state = "RATE_LIMITED"
                row.lifecycle = "RATE_LIMITED"
                row.health_cooldown_until = now + timedelta(seconds=max(cooldown_seconds, 1))
            elif failure_kind == "auth":
                row.health_state = "QUARANTINED"
                row.lifecycle = "QUARANTINED"
                row.health_cooldown_until = now + timedelta(seconds=max(cooldown_seconds, 300))
            elif consecutive_failures >= 3:
                row.health_state = "DEGRADED"
                row.lifecycle = "DEGRADED"
                row.health_cooldown_until = now + timedelta(seconds=max(cooldown_seconds, 30))
            row.updated_at = now

    def recover_due(self, now: datetime | None = None) -> int:
        current = _utc(now or datetime.now(timezone.utc))
        changed = 0
        with self._lock, self._session_factory.begin() as session:
            rows = session.scalars(
                select(ModelRegistryRow).where(ModelRegistryRow.health_cooldown_until <= current)
            ).all()
            for row in rows:
                if row.health_state != "HEALTHY" and row.lifecycle in {"DEGRADED", "RATE_LIMITED"}:
                    row.health_state = "HEALTHY"
                    row.lifecycle = "ACTIVE"
                    row.health_cooldown_until = None
                    row.updated_at = current
                    changed += 1
        return changed


def _registered_model(row: ModelRegistryRow) -> RegisteredModel:
    metrics = _runtime_metrics(row.runtime_json)
    latencies = [float(item) for item in metrics.get("latencies", []) if isinstance(item, (int, float))]
    requests = int(metrics.get("requests", 0))
    failures = int(metrics.get("failures", 0))
    try:
        capabilities = frozenset(json.loads(row.capabilities_json or "[]"))
    except (TypeError, ValueError):
        capabilities = frozenset()
    return RegisteredModel(
        model_key=row.model_key,
        provider=row.provider,  # type: ignore[arg-type]
        model_id=row.model_id,
        lifecycle=row.lifecycle,
        health_state=row.health_state,
        available=row.available,
        deprecated=row.deprecated,
        free_eligible=row.free_eligible,
        privacy_eligible=row.privacy_eligible,
        structured_output_supported=row.structured_output_supported,
        input_token_limit=row.input_token_limit,
        output_token_limit=row.output_token_limit,
        pricing=tuple(
            (str(key), float(value))
            for key, value in _runtime_metrics(row.pricing_json).items()
            if isinstance(value, (int, float))
        ),
        rate_limits=tuple(
            (str(key), float(value))
            for key, value in _runtime_metrics(row.rate_limits_json).items()
            if isinstance(value, (int, float))
        ),
        approved_task_categories=frozenset(
            str(item)
            for item in _runtime_metrics(row.benchmark_json).get(
                "approved_task_categories", []
            )
        ),
        capabilities=capabilities,
        quota_scope=row.quota_scope,
        evaluation_version=row.evaluation_version,
        quality_score=float(_runtime_metrics(row.benchmark_json).get("supported_answer_accuracy", 0)),
        citation_validity=float(_runtime_metrics(row.benchmark_json).get("citation_validity", 0)),
        latency_p50_ms=_percentile(latencies, 0.50),
        latency_p95_ms=_percentile(latencies, 0.95),
        failure_rate=(failures / requests) if requests else 0.0,
        in_flight=0,
        health_cooldown_until=(
            _utc(row.health_cooldown_until) if row.health_cooldown_until is not None else None
        ),
    )


@dataclass(frozen=True)
class QuotaReservation:
    reservation_id: str
    scope_key: str
    estimated_tokens: int
    scope_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuotaSnapshot:
    scope_key: str
    request_limit: int
    token_limit: int
    concurrency_limit: int
    requests_used: int
    tokens_used: int
    in_flight: int
    reset_at: datetime


@dataclass(frozen=True)
class QuotaScopeConfig:
    """Immutable startup/control-plane limits for one durable quota scope."""

    scope_key: str
    provider: str
    request_limit: int
    token_limit: int
    concurrency_limit: int
    window_seconds: int
    reset_at: datetime


class QuotaLedger:
    """Durable quota reservations with conservative restart reconciliation."""

    def __init__(self, database_url: str = "sqlite+pysqlite:///:memory:", *, engine=None) -> None:
        self._engine = engine or create_database_engine(database_url)
        if self._engine.dialect.name == "sqlite":
            Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        self._lock = threading.RLock()
        self.reconcile_in_flight()

    def configure_scope(
        self,
        scope_key: str,
        *,
        provider: ProviderName,
        request_limit: int,
        token_limit: int,
        concurrency_limit: int,
        reset_at: datetime,
        window_seconds: int = 86_400,
    ) -> None:
        if min(request_limit, token_limit, concurrency_limit, window_seconds) <= 0:
            raise ValueError("verified quota limits must be positive")
        now = datetime.now(timezone.utc)
        with self._lock, self._session_factory.begin() as session:
            _lock_quota_transaction(session)
            row = session.get(QuotaWindowRow, scope_key)
            if row is None:
                session.add(
                    QuotaWindowRow(
                        scope_key=scope_key,
                        provider=provider,
                        request_limit=request_limit,
                        token_limit=token_limit,
                        concurrency_limit=concurrency_limit,
                        window_seconds=window_seconds,
                        reset_at=_utc(reset_at),
                        updated_at=now,
                    )
                )
            else:
                if (
                    row.provider != provider
                    or row.request_limit != request_limit
                    or row.token_limit != token_limit
                    or row.concurrency_limit != concurrency_limit
                    or row.window_seconds != window_seconds
                ):
                    raise QuotaUnavailable(
                        f"durable quota configuration differs for {scope_key}"
                    )
                row.provider = provider
                row.updated_at = now

    @staticmethod
    def experiment_scope_key(experiment_id: str) -> str:
        """Return the only scope-key form accepted for evaluation budgets."""

        normalized = experiment_id.strip()
        if not normalized or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in normalized):
            raise ValueError("experiment_id must contain only letters, numbers, '.', '_' or '-'")
        return f"experiment:{normalized}"

    def configure_experiment(
        self,
        experiment_id: str,
        *,
        request_limit: int,
        token_limit: int,
        concurrency_limit: int,
        reset_at: datetime,
        window_seconds: int = 86_400,
    ) -> str:
        """Create or update one durable budget shared by all providers in an experiment.

        This is a control-plane operation.  The ordinary customer router never
        uses an experiment scope unless an explicit evaluation request is built
        by trusted server-side code.
        """

        scope_key = self.experiment_scope_key(experiment_id)
        self.ensure_scopes(
            QuotaScopeConfig(
                scope_key=scope_key,
                provider="shared-experiment",
                request_limit=request_limit,
                token_limit=token_limit,
                concurrency_limit=concurrency_limit,
                reset_at=reset_at,
                window_seconds=window_seconds,
            )
        )
        return scope_key

    def configure_experiment_from_settings(self, settings: ResolveAISettings) -> str:
        """Create an experiment budget only from explicit trusted settings.

        No FastAPI request can call this method.  In the current application
        there is intentionally no public evaluation endpoint; callers are
        limited to a server-side synthetic harness.
        """

        if not settings.evaluation_enabled:
            raise QuotaUnavailable("evaluation mode is disabled")
        if not settings.evaluation_experiment_id:
            raise QuotaUnavailable("evaluation experiment id is not configured")
        if settings.evaluation_request_quota <= 0 or settings.evaluation_token_quota <= 0:
            raise QuotaUnavailable("evaluation quota limits are not configured")
        return self.configure_experiment(
            settings.evaluation_experiment_id,
            request_limit=settings.evaluation_request_quota,
            token_limit=settings.evaluation_token_quota,
            concurrency_limit=settings.evaluation_max_concurrency,
            reset_at=datetime.now(timezone.utc)
            + timedelta(seconds=settings.evaluation_quota_window_seconds),
            window_seconds=settings.evaluation_quota_window_seconds,
        )

    def ensure_scopes(self, *configs: QuotaScopeConfig) -> None:
        """Atomically initialize missing startup scopes without resetting usage.

        Existing rows are immutable with respect to their limits and reset
        period.  A settings change therefore fails closed instead of silently
        granting new capacity or erasing consumed usage.  PostgreSQL and
        SQLite conflict-safe inserts make concurrent application startup
        converge on the same durable rows.
        """

        if not configs:
            return
        keys = [config.scope_key for config in configs]
        if len(set(keys)) != len(keys):
            raise ValueError("quota scope keys must be unique")
        for config in configs:
            if min(
                config.request_limit,
                config.token_limit,
                config.concurrency_limit,
                config.window_seconds,
            ) <= 0:
                raise ValueError("verified quota limits must be positive")

        with self._lock, self._session_factory.begin() as session:
            _lock_quota_transaction(session)
            for config in configs:
                row = session.get(QuotaWindowRow, config.scope_key, with_for_update=True)
                if row is not None:
                    if (
                        row.provider != config.provider
                        or row.request_limit != config.request_limit
                        or row.token_limit != config.token_limit
                        or row.concurrency_limit != config.concurrency_limit
                        or row.window_seconds != config.window_seconds
                    ):
                        raise QuotaUnavailable(
                            f"durable quota configuration differs for {config.scope_key}"
                        )
                    continue

                values = {
                    "scope_key": config.scope_key,
                    "provider": config.provider,
                    "request_limit": config.request_limit,
                    "token_limit": config.token_limit,
                    "concurrency_limit": config.concurrency_limit,
                    "window_seconds": config.window_seconds,
                    "requests_used": 0,
                    "tokens_used": 0,
                    "in_flight": 0,
                    "reset_at": _utc(config.reset_at),
                    "updated_at": datetime.now(timezone.utc),
                }
                dialect = session.bind.dialect.name
                if dialect == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert as dialect_insert

                    statement = dialect_insert(QuotaWindowRow).values(**values).on_conflict_do_nothing(
                        index_elements=["scope_key"]
                    )
                elif dialect == "sqlite":
                    from sqlalchemy.dialects.sqlite import insert as dialect_insert

                    statement = dialect_insert(QuotaWindowRow).values(**values).on_conflict_do_nothing(
                        index_elements=["scope_key"]
                    )
                else:
                    session.add(QuotaWindowRow(**values))
                    continue
                session.execute(statement)

            for config in configs:
                row = session.get(QuotaWindowRow, config.scope_key, with_for_update=True)
                if row is None or (
                    row.provider != config.provider
                    or row.request_limit != config.request_limit
                    or row.token_limit != config.token_limit
                    or row.concurrency_limit != config.concurrency_limit
                    or row.window_seconds != config.window_seconds
                ):
                    raise QuotaUnavailable(
                        f"durable quota configuration differs for {config.scope_key}"
                    )

    def snapshot(self, scope_key: str, now: datetime | None = None) -> QuotaSnapshot:
        current = _utc(now or datetime.now(timezone.utc))
        with self._session_factory() as session:
            row = session.get(QuotaWindowRow, scope_key)
            if row is None:
                raise QuotaUnavailable("verified quota is not configured")
            reset_at = _utc(row.reset_at)
            if reset_at <= current:
                return QuotaSnapshot(scope_key, row.request_limit, row.token_limit, row.concurrency_limit, 0, 0, row.in_flight, reset_at)
            return QuotaSnapshot(
                scope_key,
                row.request_limit,
                row.token_limit,
                row.concurrency_limit,
                row.requests_used,
                row.tokens_used,
                row.in_flight,
                reset_at,
            )

    def reserve(self, scope_key: str, estimated_tokens: int, now: datetime | None = None) -> QuotaReservation:
        return self.reserve_scopes((scope_key,), estimated_tokens, now)

    def reserve_scopes(
        self,
        scope_keys: Sequence[str],
        estimated_tokens: int,
        now: datetime | None = None,
    ) -> QuotaReservation:
        if estimated_tokens <= 0:
            raise ValueError("estimated_tokens must be positive")
        normalized_scopes = tuple(dict.fromkeys(scope_keys))
        if not normalized_scopes:
            raise ValueError("at least one quota scope is required")
        current = _utc(now or datetime.now(timezone.utc))
        reservation_id = f"quota_{uuid.uuid4().hex}"
        with self._lock, self._session_factory.begin() as session:
            _lock_quota_transaction(session)
            rows: list[QuotaWindowRow] = []
            for scope_key in sorted(normalized_scopes):
                row = session.get(QuotaWindowRow, scope_key, with_for_update=True)
                if row is None:
                    raise QuotaUnavailable("verified quota is not configured")
                if _utc(row.reset_at) <= current:
                    row.requests_used = 0
                    row.tokens_used = 0
                    row.reset_at = current + timedelta(seconds=row.window_seconds)
                if row.requests_used + 1 > row.request_limit:
                    raise QuotaExceeded("request quota exhausted")
                if row.tokens_used + estimated_tokens > row.token_limit:
                    raise QuotaExceeded("token quota exhausted")
                if row.in_flight >= row.concurrency_limit:
                    raise QuotaExceeded("concurrency quota exhausted")
                rows.append(row)

            for index, row in enumerate(rows):
                row.requests_used += 1
                row.tokens_used += estimated_tokens
                row.in_flight += 1
                row.updated_at = current
                session.add(
                    QuotaReservationRow(
                        reservation_id=f"{reservation_id}:{index}",
                        reservation_group=reservation_id,
                        scope_key=row.scope_key,
                        estimated_tokens=estimated_tokens,
                        actual_tokens=None,
                        state="RESERVED",
                        created_at=current,
                    )
                )
        return QuotaReservation(reservation_id, normalized_scopes[0], estimated_tokens, normalized_scopes)

    def complete(self, reservation: QuotaReservation, actual_tokens: int, now: datetime | None = None) -> None:
        if actual_tokens < 0:
            raise ValueError("actual_tokens must not be negative")
        current = _utc(now or datetime.now(timezone.utc))
        with self._lock, self._session_factory.begin() as session:
            _lock_quota_transaction(session)
            reservation_rows = session.scalars(
                select(QuotaReservationRow)
                .where(QuotaReservationRow.reservation_group == reservation.reservation_id)
            ).all()
            if not reservation_rows:
                legacy_row = session.get(QuotaReservationRow, reservation.reservation_id)
                reservation_rows = [legacy_row] if legacy_row is not None else []
            if not reservation_rows:
                return

            # Reserve, completion, release and reconciliation all acquire
            # quota-window locks before reservation-row locks.  A stable lock
            # order prevents PostgreSQL deadlocks under concurrent workers.
            windows: dict[str, QuotaWindowRow] = {}
            for scope_key in sorted({row.scope_key for row in reservation_rows}):
                window = session.get(QuotaWindowRow, scope_key, with_for_update=True)
                if window is None:
                    raise QuotaUnavailable("quota window disappeared")
                windows[scope_key] = window
            if reservation_rows[0].reservation_group == reservation.reservation_id:
                reservation_rows = session.scalars(
                    select(QuotaReservationRow)
                    .where(QuotaReservationRow.reservation_group == reservation.reservation_id)
                    .order_by(QuotaReservationRow.scope_key)
                    .with_for_update()
                ).all()
            else:
                legacy_row = session.get(QuotaReservationRow, reservation.reservation_id, with_for_update=True)
                reservation_rows = [legacy_row] if legacy_row is not None else []
            if not reservation_rows or any(row.state != "RESERVED" for row in reservation_rows):
                return
            for reservation_row in reservation_rows:
                window = windows[reservation_row.scope_key]
                window.tokens_used = max(0, window.tokens_used - reservation_row.estimated_tokens + actual_tokens)
                window.in_flight = max(0, window.in_flight - 1)
                window.updated_at = current
                reservation_row.actual_tokens = actual_tokens
                reservation_row.state = (
                    "OVERRUN"
                    if actual_tokens > reservation_row.estimated_tokens
                    else "COMPLETED"
                )
                reservation_row.completed_at = current

    def release(self, reservation: QuotaReservation, now: datetime | None = None) -> None:
        current = _utc(now or datetime.now(timezone.utc))
        with self._lock, self._session_factory.begin() as session:
            _lock_quota_transaction(session)
            reservation_rows = session.scalars(
                select(QuotaReservationRow)
                .where(QuotaReservationRow.reservation_group == reservation.reservation_id)
            ).all()
            if not reservation_rows:
                legacy_row = session.get(QuotaReservationRow, reservation.reservation_id)
                reservation_rows = [legacy_row] if legacy_row is not None else []
            if not reservation_rows:
                return
            windows: dict[str, QuotaWindowRow] = {}
            for scope_key in sorted({row.scope_key for row in reservation_rows}):
                window = session.get(QuotaWindowRow, scope_key, with_for_update=True)
                if window is None:
                    return
                windows[scope_key] = window
            if reservation_rows[0].reservation_group == reservation.reservation_id:
                reservation_rows = session.scalars(
                    select(QuotaReservationRow)
                    .where(QuotaReservationRow.reservation_group == reservation.reservation_id)
                    .order_by(QuotaReservationRow.scope_key)
                    .with_for_update()
                ).all()
            else:
                legacy_row = session.get(QuotaReservationRow, reservation.reservation_id, with_for_update=True)
                reservation_rows = [legacy_row] if legacy_row is not None else []
            if not reservation_rows or any(row.state != "RESERVED" for row in reservation_rows):
                return
            for reservation_row in reservation_rows:
                window = windows[reservation_row.scope_key]
                window.requests_used = max(0, window.requests_used - 1)
                window.tokens_used = max(0, window.tokens_used - reservation_row.estimated_tokens)
                window.in_flight = max(0, window.in_flight - 1)
                window.updated_at = current
                reservation_row.state = "RELEASED"
                reservation_row.completed_at = current

    def reconcile_in_flight(self) -> int:
        """Clear abandoned in-flight slots while retaining conservative usage."""

        now = datetime.now(timezone.utc)
        changed = 0
        with self._lock, self._session_factory.begin() as session:
            _lock_quota_transaction(session)
            scope_keys = session.scalars(
                select(QuotaReservationRow.scope_key)
                .where(QuotaReservationRow.state == "RESERVED")
                .distinct()
            ).all()
            for scope_key in sorted(scope_keys):
                session.get(QuotaWindowRow, scope_key, with_for_update=True)
            pending = session.scalars(
                select(QuotaReservationRow)
                .where(QuotaReservationRow.state == "RESERVED")
                .with_for_update()
            ).all()
            for reservation in pending:
                window = session.get(QuotaWindowRow, reservation.scope_key)
                if window is not None:
                    window.in_flight = max(0, window.in_flight - 1)
                reservation.state = "RECONCILED"
                reservation.completed_at = now
                changed += 1
        return changed


@dataclass(frozen=True)
class RouteRequest:
    task_category: str = "policy_answer"
    required_capabilities: frozenset[str] = frozenset({"structured_outputs"})
    estimated_tokens: int = 256
    estimated_input_tokens: int | None = None
    estimated_output_tokens: int | None = None
    deadline_ms: float | None = None
    manual_model_id: str | None = None
    execution_mode: Literal["customer", "evaluation"] = "customer"
    experiment_scope_key: str | None = None


@dataclass(frozen=True)
class RouteDecision:
    model_key: str
    provider: ProviderName
    model_id: str
    reservation: QuotaReservation
    score: float
    reasons: tuple[str, ...]


class AdaptiveModelRouter:
    """Deterministic, quota-aware selection among already active models."""

    def __init__(
        self,
        registry: ModelRegistry,
        quota_ledger: QuotaLedger,
        *,
        account_scope_prefix: str | None = None,
    ) -> None:
        self._registry = registry
        self._quota = quota_ledger
        self._account_scope_prefix = account_scope_prefix

    def select(self, request: RouteRequest, now: datetime | None = None) -> RouteDecision | None:
        if request.execution_mode == "customer" and request.experiment_scope_key is not None:
            raise ModelNotRoutable("customer requests cannot provide an evaluation scope")
        if request.execution_mode == "evaluation":
            if not request.experiment_scope_key or not request.experiment_scope_key.startswith("experiment:"):
                raise ModelNotRoutable("evaluation requests require a trusted experiment scope")
        elif request.execution_mode != "customer":
            raise ModelNotRoutable("unknown execution mode")
        current = _utc(now or datetime.now(timezone.utc))
        self._registry.recover_due(current)
        candidates = []
        for model in self._registry.list():
            allowed_lifecycles = {"ACTIVE"} if request.execution_mode == "customer" else {"QUALIFIED", "ACTIVE"}
            if model.lifecycle not in allowed_lifecycles or model.health_state != "HEALTHY":
                continue
            if request.execution_mode == "evaluation" and not model.evaluation_version:
                continue
            if not model.available or model.deprecated or model.free_eligible is not True:
                continue
            if not model.privacy_eligible or model.structured_output_supported is not True:
                continue
            if request.task_category not in model.approved_task_categories:
                continue
            if request.manual_model_id and model.model_id != request.manual_model_id:
                continue
            if not request.required_capabilities.issubset(model.capabilities):
                continue
            if (
                request.estimated_input_tokens is not None
                and model.input_token_limit is not None
                and request.estimated_input_tokens > model.input_token_limit
            ):
                continue
            if (
                request.estimated_output_tokens is not None
                and model.output_token_limit is not None
                and request.estimated_output_tokens > model.output_token_limit
            ):
                continue
            if model.health_cooldown_until and model.health_cooldown_until > current:
                continue
            scope_keys = [model.quota_scope]
            if self._account_scope_prefix:
                scope_keys.append(f"{self._account_scope_prefix}{model.provider}")
            if request.execution_mode == "evaluation":
                scope_keys.append(request.experiment_scope_key)
            snapshots = []
            try:
                for scope_key in dict.fromkeys(scope_keys):
                    snapshot = self._quota.snapshot(scope_key, current)
                    if snapshot.requests_used >= snapshot.request_limit:
                        raise QuotaExceeded("request quota exhausted")
                    if snapshot.tokens_used + request.estimated_tokens > snapshot.token_limit:
                        raise QuotaExceeded("token quota exhausted")
                    if snapshot.in_flight >= snapshot.concurrency_limit:
                        raise QuotaExceeded("concurrency quota exhausted")
                    snapshots.append(snapshot)
            except (QuotaUnavailable, QuotaExceeded):
                continue
            snapshot = snapshots[0]
            if request.deadline_ms is not None and model.latency_p95_ms > request.deadline_ms:
                continue
            quota_headroom = 1 - (snapshot.tokens_used / snapshot.token_limit)
            score = (
                model.quality_score * 0.45
                + model.citation_validity * 0.25
                + (1 / max(model.latency_p95_ms, 1.0)) * 0.15
                + quota_headroom * 0.10
                + (1 - model.failure_rate) * 0.05
            )
            candidates.append((score, model))
        for score, model in sorted(candidates, key=lambda item: (-item[0], item[1].model_key)):
            scope_keys = [model.quota_scope]
            if self._account_scope_prefix:
                scope_keys.append(f"{self._account_scope_prefix}{model.provider}")
            if request.execution_mode == "evaluation":
                scope_keys.append(request.experiment_scope_key)
            try:
                reservation = self._quota.reserve_scopes(
                    tuple(dict.fromkeys(scope_keys)), request.estimated_tokens, current
                )
            except (QuotaUnavailable, QuotaExceeded):
                continue
            return RouteDecision(
                model_key=model.model_key,
                provider=model.provider,
                model_id=model.model_id,
                reservation=reservation,
                score=round(score, 8),
                reasons=("qualified", "privacy-eligible", "free-eligible", "quota-admitted"),
            )
        return None

    def report_success(
        self,
        decision: RouteDecision,
        *,
        actual_tokens: int,
        latency_ms: float,
        usage_known: bool = True,
    ) -> None:
        settled_tokens = (
            actual_tokens
            if usage_known
            else max(decision.reservation.estimated_tokens, actual_tokens)
        )
        self._quota.complete(decision.reservation, settled_tokens)
        self._registry.update_runtime(decision.model_key, success=True, latency_ms=latency_ms)

    def report_failure(
        self,
        decision: RouteDecision,
        *,
        failure_kind: str,
        retry_after_seconds: float = 0,
        dispatched: bool = True,
        actual_tokens: int | None = None,
    ) -> None:
        if dispatched:
            # Unknown or incomplete provider usage must retain the reservation
            # rather than being settled as zero.  A caller may provide an
            # authoritative actual count, but it may not reduce a failed
            # dispatch below the durable reservation without evidence.
            settled_tokens = (
                decision.reservation.estimated_tokens
                if actual_tokens is None
                else max(0, actual_tokens)
            )
            self._quota.complete(decision.reservation, settled_tokens)
        else:
            self._quota.release(decision.reservation)
        self._registry.update_runtime(
            decision.model_key,
            success=False,
            failure_kind=failure_kind,
            cooldown_seconds=retry_after_seconds,
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lock_quota_transaction(session) -> None:
    """Serialize the short quota-control transactions on PostgreSQL.

    Reservations can span a model, provider-account and experiment window.
    A database advisory lock prevents startup reconciliation and multi-scope
    completion from interleaving with another worker's row updates.  SQLite
    already uses the ledger's process lock and does not expose this function.
    """

    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('resolveai:quota-control-v1'))")
        )


__all__ = [
    "AdaptiveModelRouter",
    "DiscoveryUnavailable",
    "ModelControlError",
    "ModelDescriptor",
    "ModelDiscoveryService",
    "ModelNotRoutable",
    "ModelRegistry",
    "ModelRegistryRow",
    "MODEL_STATES",
    "PROVIDER_SPECS",
    "ProviderSpec",
    "RateLimitMetadata",
    "QualificationDecision",
    "QualificationEvidence",
    "QualificationPolicy",
    "QualificationRejected",
    "QuotaExceeded",
    "QuotaLedger",
    "QuotaScopeConfig",
    "QuotaReservation",
    "QuotaReservationRow",
    "QuotaSnapshot",
    "QuotaUnavailable",
    "QuotaWindowRow",
    "RegisteredModel",
    "RouteDecision",
    "RouteRequest",
    "parse_rate_limit_headers",
]
