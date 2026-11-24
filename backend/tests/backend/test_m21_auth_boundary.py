from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api import create_app
from backend.app.config import ResolveAISettings
from backend.app.db.conversations import (
    ConversationRepository,
    REQUIRED_POSTGRES_TABLES,
    SUPPORTED_ALEMBIC_HEAD,
)
from backend.app.services.auth import (
    AdmissionLimiter,
    AuthSessionStore,
    client_ip,
    hash_password,
)


def _settings(*, login_limit: int = 10) -> ResolveAISettings:
    password_hash = hash_password("correct horse battery staple")
    users = json.dumps(
        [
            {
                "username": "alice",
                "password_hash": password_hash,
                "actor_id": "customer_001",
                "role": "customer",
                "display_name": "Alice",
                "customer_id": "customer_001",
                "permissions": ["orders:read:self"],
            }
        ]
    )
    return ResolveAISettings(
        _env_file=None,
        production_auth_enabled=True,
        demo_auth_enabled=False,
        auth_secret_key="s" * 32,
        production_auth_users_json=users,
        login_rate_limit=login_limit,
    )


def test_production_login_uses_opaque_cookie_and_csrf_protection() -> None:
    client = TestClient(create_app(settings=_settings()))

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "correct horse battery staple"},
    )

    assert login.status_code == 200
    assert "session_id" not in login.json()
    assert isinstance(login.json()["csrf_token"], str)
    session_cookie = client.cookies.get("resolveai_session")
    assert session_cookie is not None
    assert session_cookie not in login.text
    assert "HttpOnly" in login.headers["set-cookie"]
    assert client.get("/api/v1/me").json()["actor_id"] == "customer_001"

    blocked = client.post("/api/v1/auth/logout")
    assert blocked.status_code == 403
    csrf = login.json()["csrf_token"]
    allowed = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert allowed.status_code == 204
    assert client.get("/api/v1/me").status_code == 401


def test_configured_hosted_origin_allows_credentialed_preflight() -> None:
    settings = _settings()
    settings.cors_origins = "https://resolveai.pages.dev"
    client = TestClient(create_app(settings=settings))

    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://resolveai.pages.dev",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://resolveai.pages.dev"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_demo_login_is_not_a_production_auth_fallback() -> None:
    client = TestClient(create_app(settings=_settings()))

    assert client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": "customer_001"}
    ).status_code == 404
    assert client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "wrong"}
    ).status_code == 401


def test_production_requires_postgresql_for_durable_auth_state() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL"):
        ResolveAISettings(
            _env_file=None,
            environment="production",
            production_auth_enabled=True,
            demo_auth_enabled=False,
            auth_secret_key="s" * 32,
            production_auth_users_json="[]",
            database_url="sqlite+pysqlite:///:memory:",
        )


def test_login_rate_limit_returns_retry_guidance_and_ignores_spoofed_forwarding() -> None:
    client = TestClient(create_app(settings=_settings(login_limit=2)))
    headers = {"X-Forwarded-For": "203.0.113.20"}
    for _ in range(2):
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "wrong"},
            headers=headers,
        ).status_code == 401
    limited = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "wrong"},
        headers={"X-Forwarded-For": "198.51.100.40"},
    )
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    assert limited.json()["error"]["code"] == "rate_limited"


def test_forwarded_ip_is_used_only_for_explicitly_trusted_proxy() -> None:
    assert client_ip(
        remote="10.0.0.5",
        forwarded_for="203.0.113.20",
        trusted_networks=(),
    ) == "10.0.0.5"
    assert client_ip(
        remote="10.0.0.5",
        forwarded_for="203.0.113.20",
        trusted_networks=(__import__("ipaddress").ip_network("10.0.0.0/8"),),
    ) == "203.0.113.20"


def test_admission_limit_is_atomic_under_concurrent_requests() -> None:
    limiter = AdmissionLimiter(limit=1, window_seconds=60)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: limiter.check(("same-user",)), range(8)))
    assert sum(result.allowed for result in results) == 1
    assert all(result.retry_after_seconds >= 1 for result in results if not result.allowed)


def test_malformed_session_tokens_fail_closed_without_server_error() -> None:
    store = AuthSessionStore((), secret_key="s" * 32, ttl_seconds=60)

    assert store.actor_for_session("not-ascii-\u00e9") is None
    assert store.revoke("not-ascii-\u00e9") is False


class _FakeConnection:
    def __init__(self, version: str | None):
        self.version = version

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement):
        result = Mock()
        if "version_num" in str(statement):
            result.scalar_one_or_none.return_value = self.version
        return result


def _fake_postgres_repository(monkeypatch, *, version: str | None, tables: set[str]):
    engine = Mock()
    engine.dialect.name = "postgresql"
    engine.connect.return_value = _FakeConnection(version)
    monkeypatch.setattr(
        "backend.app.db.conversations.inspect",
        lambda connection: Mock(get_table_names=lambda: sorted(tables)),
    )
    repository = ConversationRepository.__new__(ConversationRepository)
    repository._engine = engine
    repository._expected_alembic_head = SUPPORTED_ALEMBIC_HEAD
    return repository


def test_postgres_readiness_requires_supported_head_and_schema(monkeypatch) -> None:
    ready = _fake_postgres_repository(
        monkeypatch,
        version=SUPPORTED_ALEMBIC_HEAD,
        tables=set(REQUIRED_POSTGRES_TABLES),
    )
    assert ready.database_ready() is True

    stale = _fake_postgres_repository(
        monkeypatch,
        version="20261124_09",
        tables=set(REQUIRED_POSTGRES_TABLES),
    )
    assert stale.database_ready() is False

    missing = _fake_postgres_repository(
        monkeypatch,
        version=SUPPORTED_ALEMBIC_HEAD,
        tables=set(REQUIRED_POSTGRES_TABLES) - {"policy_index_jobs"},
    )
    assert missing.database_ready() is False
