from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from backend.app.ai.model_control import (
    AdaptiveModelRouter,
    DiscoveryUnavailable,
    ModelDescriptor,
    ModelDiscoveryService,
    ModelNotRoutable,
    ModelRegistry,
    QualificationEvidence,
    QualificationPolicy,
    QualificationRejected,
    QuotaExceeded,
    QuotaLedger,
    QuotaScopeConfig,
    QuotaUnavailable,
    RouteRequest,
    parse_rate_limit_headers,
)
from backend.app.config import ResolveAISettings


def _settings(**overrides) -> ResolveAISettings:
    return ResolveAISettings(
        _env_file=None,
        model_discovery_enabled=True,
        model_catalog_ttl_seconds=300,
        provider_timeout_seconds=1,
        **overrides,
    )


def _descriptor(model_id: str, *, provider: str = "groq", quality: float = 0.95) -> ModelDescriptor:
    return ModelDescriptor(
        provider=provider,  # type: ignore[arg-type]
        model_id=model_id,
        capabilities=frozenset({"structured_outputs", "text"}),
        structured_output_supported=True,
        free_eligible=True,
        privacy_eligible=True,
        quota_scope=f"{provider}:{model_id}",
    )


def _evidence(*, quality: float = 0.95, version: str = "dev-1") -> QualificationEvidence:
    return QualificationEvidence(
        structured_output_compliance=1.0,
        supported_answer_accuracy=quality,
        citation_validity=1.0,
        unsupported_safety=1.0,
        false_acceptance=0,
        wrong_version_exposure=0,
        p95_latency_ms=50,
        evaluation_version=version,
    )


def test_discovery_uses_official_shape_and_caches_without_logging_credentials() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "llama-verified",
                        "owned_by": "groq",
                        "context_length": 8192,
                        "max_output_length": 1024,
                        "supported_features": ["structured_outputs"],
                        "pricing": {"prompt": 0, "completion": 0},
                        "rate_limits": {"requests_per_minute": 30},
                    }
                ]
            },
            request=request,
        )

    service = ModelDiscoveryService(client=httpx.Client(transport=httpx.MockTransport(handler)))
    settings = _settings(groq_api_key="test-secret")

    first = service.discover("groq", settings, catalog_version="catalog-1")
    second = service.discover("groq", settings, catalog_version="catalog-1")

    assert len(calls) == 1
    assert first == second
    assert first[0].model_id == "llama-verified"
    assert first[0].free_eligible is True
    assert first[0].structured_output_supported is True
    assert first[0].privacy_eligible is False
    assert first[0].input_token_limit == 8192
    assert dict(first[0].pricing) == {"prompt": 0.0, "completion": 0.0}
    assert dict(first[0].rate_limits) == {"requests_per_minute": 30.0}


def test_discovery_is_disabled_by_default_and_unverified_models_are_not_active() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": []}, request=request)

    service = ModelDiscoveryService(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(DiscoveryUnavailable, match="disabled"):
        service.discover("groq", ResolveAISettings(_env_file=None))
    assert calls == []

    registry = ModelRegistry()
    model = _descriptor("new-model")
    registry.upsert_discovered([model])
    assert registry.get(model.model_key).lifecycle == "UNVERIFIED"


def test_static_only_providers_fail_closed_without_an_invented_endpoint() -> None:
    service = ModelDiscoveryService()
    settings = _settings()

    assert service.discover("cloudflare", settings) == ()
    assert service.discover("modelscope", settings) == ()


def test_refresh_persists_static_catalog_as_unverified() -> None:
    model = ModelDescriptor(provider="cloudflare", model_id="reviewed-model")
    service = ModelDiscoveryService(static_catalog={"cloudflare": [model]})
    registry = ModelRegistry()

    entries = service.refresh("cloudflare", _settings(), registry, catalog_version="manual-1")

    assert entries == (model,)
    stored = registry.get(model.model_key)
    assert stored is not None
    assert stored.lifecycle == "UNVERIFIED"


def test_qualification_requires_cost_privacy_structure_and_quality_gates() -> None:
    registry = ModelRegistry()
    model = _descriptor("qualified-model")
    registry.upsert_discovered([model])

    decision = registry.admit(model.model_key, model, _evidence())
    assert decision.accepted is True
    registry.activate(model.model_key)
    assert registry.get(model.model_key).lifecycle == "ACTIVE"

    unsafe = ModelDescriptor(
        provider="groq",
        model_id="unsafe-model",
        capabilities=frozenset({"text"}),
        structured_output_supported=None,
        free_eligible=None,
        privacy_eligible=False,
    )
    registry.upsert_discovered([unsafe])
    with pytest.raises(QualificationRejected) as error:
        registry.admit(unsafe.model_key, unsafe, _evidence(quality=0.1))
    assert "free entitlement is not verified" in str(error.value)
    assert registry.get(unsafe.model_key).lifecycle == "UNVERIFIED"


def test_quota_reservation_is_atomic_and_restart_reconciles_in_flight(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'quota.db'}"
    ledger = QuotaLedger(database_url)
    reset_at = datetime.now(timezone.utc) + timedelta(hours=1)
    ledger.configure_scope(
        "groq:qualified-model",
        provider="groq",
        request_limit=2,
        token_limit=100,
        concurrency_limit=1,
        reset_at=reset_at,
    )

    reservation = ledger.reserve("groq:qualified-model", 25)
    with pytest.raises(QuotaExceeded, match="concurrency"):
        ledger.reserve("groq:qualified-model", 25)
    restarted = QuotaLedger(database_url)
    snapshot = restarted.snapshot("groq:qualified-model")
    assert snapshot.in_flight == 0
    assert snapshot.requests_used == 1
    assert snapshot.tokens_used == 25

    # The old reservation is conservatively reconciled after restart; its
    # external usage is unknown and therefore cannot be retroactively changed.
    restarted.complete(reservation, 10)
    snapshot = restarted.snapshot("groq:qualified-model")
    assert snapshot.in_flight == 0
    assert snapshot.tokens_used == 25
    next_reservation = restarted.reserve("groq:qualified-model", 25)
    restarted.complete(next_reservation, 10)
    assert restarted.snapshot("groq:qualified-model").tokens_used == 35


def test_router_prefers_qualified_quality_and_distributes_when_capacity_is_busy() -> None:
    registry = ModelRegistry()
    first = _descriptor("fast-quality")
    second = _descriptor("backup-quality")
    registry.upsert_discovered([first, second])
    registry.admit(first.model_key, first, _evidence(quality=0.99))
    registry.admit(second.model_key, second, _evidence(quality=0.90))
    registry.activate(first.model_key)
    registry.activate(second.model_key)

    ledger = QuotaLedger()
    reset_at = datetime.now(timezone.utc) + timedelta(hours=1)
    for model in (first, second):
        ledger.configure_scope(
            model.quota_scope,
            provider="groq",
            request_limit=10,
            token_limit=1000,
            concurrency_limit=1,
            reset_at=reset_at,
        )
    router = AdaptiveModelRouter(registry, ledger)
    first_route = router.select(RouteRequest(estimated_tokens=20))
    assert first_route is not None
    assert first_route.model_id == "fast-quality"
    second_route = router.select(RouteRequest(estimated_tokens=20))
    assert second_route is not None
    assert second_route.model_id == "backup-quality"
    router.report_success(first_route, actual_tokens=12, latency_ms=20)
    router.report_success(second_route, actual_tokens=14, latency_ms=25)


def test_router_manual_override_cannot_bypass_qualification_or_quota() -> None:
    registry = ModelRegistry()
    model = _descriptor("manual-model")
    registry.upsert_discovered([model])
    registry.admit(model.model_key, model, _evidence())
    registry.activate(model.model_key)
    ledger = QuotaLedger()
    ledger.configure_scope(
        model.quota_scope,
        provider="groq",
        request_limit=1,
        token_limit=10,
        concurrency_limit=1,
        reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    router = AdaptiveModelRouter(registry, ledger)
    assert router.select(RouteRequest(manual_model_id="unknown")) is None
    decision = router.select(RouteRequest(manual_model_id="manual-model", estimated_tokens=10))
    assert decision is not None
    router.report_failure(decision, failure_kind="rate_limited", retry_after_seconds=60)
    assert router.select(RouteRequest(manual_model_id="manual-model", estimated_tokens=1)) is None


def test_health_failures_quarantine_and_recover_without_polling() -> None:
    registry = ModelRegistry()
    model = _descriptor("recoverable-model")
    registry.upsert_discovered([model])
    registry.admit(model.model_key, model, _evidence())
    registry.activate(model.model_key)
    for _ in range(3):
        registry.update_runtime(model.model_key, success=False, failure_kind="timeout", cooldown_seconds=1)
    assert registry.get(model.model_key).lifecycle == "DEGRADED"
    assert registry.recover_due(datetime.now(timezone.utc) + timedelta(seconds=31)) == 1
    assert registry.get(model.model_key).lifecycle == "ACTIVE"


def test_health_threshold_uses_consecutive_failures() -> None:
    registry = ModelRegistry()
    model = _descriptor("consecutive-model")
    registry.upsert_discovered([model])
    registry.admit(model.model_key, model, _evidence())
    registry.activate(model.model_key)
    registry.update_runtime(model.model_key, success=False, failure_kind="timeout")
    registry.update_runtime(model.model_key, success=False, failure_kind="timeout")
    registry.update_runtime(model.model_key, success=True, latency_ms=5)
    registry.update_runtime(model.model_key, success=False, failure_kind="timeout")
    registry.update_runtime(model.model_key, success=False, failure_kind="timeout")
    assert registry.get(model.model_key).lifecycle == "ACTIVE"
    registry.update_runtime(model.model_key, success=False, failure_kind="timeout")
    assert registry.get(model.model_key).lifecycle == "DEGRADED"


def test_rate_limit_headers_are_parsed_without_assuming_all_provider_limits() -> None:
    metadata = parse_rate_limit_headers(
        {
            "X-RateLimit-Limit": "10",
            "X-RateLimit-Remaining": "4",
            "Retry-After": "2",
        }
    )
    assert metadata.request_limit == 10
    assert metadata.requests_remaining == 4
    assert metadata.retry_after_seconds == 2


def _configure_routing_scopes(
    ledger: QuotaLedger,
    descriptors: tuple[ModelDescriptor, ...],
    *,
    request_limit: int = 10,
    token_limit: int = 1_000,
    concurrency_limit: int = 2,
) -> None:
    reset_at = datetime.now(timezone.utc) + timedelta(hours=1)
    for descriptor in descriptors:
        ledger.configure_scope(
            descriptor.quota_scope or descriptor.provider,
            provider=descriptor.provider,
            request_limit=request_limit,
            token_limit=token_limit,
            concurrency_limit=concurrency_limit,
            reset_at=reset_at,
        )
        ledger.configure_scope(
            f"account:{descriptor.provider}",
            provider=descriptor.provider,
            request_limit=request_limit,
            token_limit=token_limit,
            concurrency_limit=concurrency_limit,
            reset_at=reset_at,
        )


def test_shared_experiment_budget_is_atomic_across_provider_scopes() -> None:
    registry = ModelRegistry()
    groq = _descriptor("eval-groq", provider="groq")
    gemini = _descriptor("eval-gemini", provider="gemini")
    for descriptor in (groq, gemini):
        registry.upsert_discovered([descriptor])
        registry.admit(descriptor.model_key, descriptor, _evidence())

    ledger = QuotaLedger()
    _configure_routing_scopes(ledger, (groq, gemini))
    experiment_scope = ledger.configure_experiment(
        "m18-fix-boundary",
        request_limit=2,
        token_limit=30,
        concurrency_limit=2,
        reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    router = AdaptiveModelRouter(registry, ledger, account_scope_prefix="account:")

    first = router.select(
        RouteRequest(
            manual_model_id=groq.model_id,
            estimated_tokens=20,
            execution_mode="evaluation",
            experiment_scope_key=experiment_scope,
        )
    )
    assert first is not None
    second = router.select(
        RouteRequest(
            manual_model_id=gemini.model_id,
            estimated_tokens=15,
            execution_mode="evaluation",
            experiment_scope_key=experiment_scope,
        )
    )
    assert second is None
    router.report_success(first, actual_tokens=20, latency_ms=10)

    exact_boundary = router.select(
        RouteRequest(
            manual_model_id=gemini.model_id,
            estimated_tokens=10,
            execution_mode="evaluation",
            experiment_scope_key=experiment_scope,
        )
    )
    assert exact_boundary is not None
    assert ledger.snapshot(experiment_scope).requests_used == 2
    assert ledger.snapshot(experiment_scope).tokens_used == 30
    router.report_success(exact_boundary, actual_tokens=10, latency_ms=10)


def test_experiment_budget_from_settings_requires_explicit_nonzero_enablement() -> None:
    ledger = QuotaLedger()
    with pytest.raises(QuotaUnavailable, match="evaluation mode is disabled"):
        ledger.configure_experiment_from_settings(ResolveAISettings(_env_file=None))

    settings = ResolveAISettings(
        _env_file=None,
        evaluation_enabled=True,
        evaluation_experiment_id="approved-synthetic",
        evaluation_request_quota=48,
        evaluation_token_quota=50_000,
        evaluation_max_concurrency=2,
    )
    scope = ledger.configure_experiment_from_settings(settings)
    snapshot = ledger.snapshot(scope)
    assert scope == "experiment:approved-synthetic"
    assert snapshot.request_limit == 48
    assert snapshot.token_limit == 50_000
    assert snapshot.concurrency_limit == 2


def test_experiment_capacity_survives_restart_and_reconciliation(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'experiment.db'}"
    ledger = QuotaLedger(database_url)
    scope = ledger.configure_experiment(
        "restart-safe",
        request_limit=2,
        token_limit=20,
        concurrency_limit=1,
        reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    reservation = ledger.reserve(scope, 10)

    restarted = QuotaLedger(database_url)
    after_restart = restarted.snapshot(scope)
    assert after_restart.requests_used == 1
    assert after_restart.tokens_used == 10
    assert after_restart.in_flight == 0
    next_reservation = restarted.reserve(scope, 10)
    restarted.complete(next_reservation, 10)
    with pytest.raises(QuotaExceeded, match="request"):
        restarted.reserve(scope, 1)
    # The abandoned reservation cannot later reduce consumed experiment usage.
    restarted.complete(reservation, 0)
    assert restarted.snapshot(scope).tokens_used == 20


def test_concurrent_shared_reservations_cannot_oversubscribe_budget() -> None:
    ledger = QuotaLedger()
    scope = ledger.configure_experiment(
        "concurrency-boundary",
        request_limit=4,
        token_limit=40,
        concurrency_limit=4,
        reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    def reserve_one() -> bool:
        try:
            ledger.reserve(scope, 10)
            return True
        except QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _item: reserve_one(), range(8)))
    assert sum(outcomes) == 4
    snapshot = ledger.snapshot(scope)
    assert snapshot.requests_used == 4
    assert snapshot.tokens_used == 40
    assert snapshot.in_flight == 4


def test_startup_scope_initialization_is_idempotent_and_fails_closed_on_changes(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'startup.db'}"
    reset_at = datetime.now(timezone.utc) + timedelta(hours=1)
    config = QuotaScopeConfig(
        scope_key="account:groq",
        provider="groq",
        request_limit=48,
        token_limit=50_000,
        concurrency_limit=2,
        window_seconds=86_400,
        reset_at=reset_at,
    )
    ledger = QuotaLedger(database_url)
    ledger.ensure_scopes(config)
    reservation = ledger.reserve("account:groq", 256)
    restarted = QuotaLedger(database_url)
    restarted.ensure_scopes(config)
    assert restarted.snapshot("account:groq").tokens_used == 256
    with pytest.raises(QuotaUnavailable, match="durable quota configuration differs"):
        restarted.ensure_scopes(
            QuotaScopeConfig(
                scope_key="account:groq",
                provider="groq",
                request_limit=49,
                token_limit=50_000,
                concurrency_limit=2,
                window_seconds=86_400,
                reset_at=reset_at,
            )
        )
    restarted.release(reservation)


def test_customer_mode_cannot_consume_evaluation_budget_or_use_qualified_only_model() -> None:
    registry = ModelRegistry()
    descriptor = _descriptor("evaluation-only")
    registry.upsert_discovered([descriptor])
    registry.admit(descriptor.model_key, descriptor, _evidence())
    ledger = QuotaLedger()
    _configure_routing_scopes(ledger, (descriptor,))
    experiment_scope = ledger.configure_experiment(
        "isolation",
        request_limit=1,
        token_limit=256,
        concurrency_limit=1,
        reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    router = AdaptiveModelRouter(registry, ledger, account_scope_prefix="account:")

    assert router.select(RouteRequest()) is None
    assert ledger.snapshot(experiment_scope).requests_used == 0
    evaluation = router.select(
        RouteRequest(execution_mode="evaluation", experiment_scope_key=experiment_scope)
    )
    assert evaluation is not None
    router.report_failure(evaluation, failure_kind="test", dispatched=False)
    with pytest.raises(ModelNotRoutable, match="evaluation scope"):
        router.select(RouteRequest(experiment_scope_key=experiment_scope))


def test_unknown_success_usage_never_settles_below_reserved_capacity() -> None:
    registry = ModelRegistry()
    descriptor = _descriptor("unknown-usage")
    registry.upsert_discovered([descriptor])
    registry.admit(descriptor.model_key, descriptor, _evidence())
    registry.activate(descriptor.model_key)
    ledger = QuotaLedger()
    ledger.configure_scope(
        descriptor.quota_scope,
        provider=descriptor.provider,
        request_limit=2,
        token_limit=300,
        concurrency_limit=1,
        reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    router = AdaptiveModelRouter(registry, ledger)
    decision = router.select(RouteRequest(estimated_tokens=256))
    assert decision is not None
    router.report_success(decision, actual_tokens=8, usage_known=False, latency_ms=1)
    assert ledger.snapshot(descriptor.quota_scope).tokens_used == 256


def test_actual_token_overrun_is_recorded_and_stops_further_dispatch() -> None:
    registry = ModelRegistry()
    descriptor = _descriptor("overrun-usage")
    registry.upsert_discovered([descriptor])
    registry.admit(descriptor.model_key, descriptor, _evidence())
    registry.activate(descriptor.model_key)
    ledger = QuotaLedger()
    ledger.configure_scope(
        descriptor.quota_scope,
        provider=descriptor.provider,
        request_limit=2,
        token_limit=300,
        concurrency_limit=1,
        reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    router = AdaptiveModelRouter(registry, ledger)
    decision = router.select(RouteRequest(estimated_tokens=256))
    assert decision is not None
    router.report_success(decision, actual_tokens=400, latency_ms=1)
    assert ledger.snapshot(descriptor.quota_scope).tokens_used == 400
    assert router.select(RouteRequest(estimated_tokens=1)) is None
