"""Durable production session and admission-state checks.

These tests use a file-backed SQLite database to exercise the repository
boundary without requiring a live service.  The application selects this
repository only for PostgreSQL; SQLite remains the explicit offline fallback
for the HTTP test suite.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select

from backend.app.api import create_app
from backend.app.config import ResolveAISettings
from backend.app.contracts import ActorSummary
from backend.app.db.auth import (
    AuthAdmissionWindowRow,
    AuthSessionRow,
    AuthStateBase,
    AuthStateRepository,
    AuthStateUnavailable,
)
from backend.app.services.auth import (
    AdmissionLimiter,
    AuthSessionStore,
    ProvisionedAccount,
    hash_password,
)


def _account(username: str, actor_id: str, role: str) -> ProvisionedAccount:
    return ProvisionedAccount(
        username=username,
        password_hash=hash_password("correct horse battery staple"),
        actor=ActorSummary(
            actor_id=actor_id,
            display_name=username.title(),
            role=role,
            customer_id=actor_id if role == "customer" else None,
            permissions=["orders:read:self"] if role == "customer" else ["support:inbox"],
        ),
    )


def _production_settings() -> ResolveAISettings:
    account = _account("alice", "customer_001", "customer")
    return ResolveAISettings(
        _env_file=None,
        production_auth_enabled=True,
        demo_auth_enabled=False,
        auth_secret_key="s" * 32,
        production_auth_users_json=json.dumps(
            [{
                "username": account.username,
                "password_hash": account.password_hash,
                "actor_id": account.actor.actor_id,
                "role": account.actor.role,
                "display_name": account.actor.display_name,
                "customer_id": account.actor.customer_id,
                "permissions": account.actor.permissions,
            }]
        ),
    )


def _repository(tmp_path, *, schema: bool = True) -> AuthStateRepository:
    repository = AuthStateRepository(f"sqlite+pysqlite:///{tmp_path / 'auth.db'}")
    if schema:
        AuthStateBase.metadata.create_all(repository._engine)  # noqa: SLF001 - schema fixture
    return repository


def test_durable_sessions_survive_restart_and_revoke_replay(tmp_path) -> None:
    accounts = (_account("alice", "customer_001", "customer"),)
    first = AuthSessionStore(
        accounts,
        secret_key="s" * 32,
        ttl_seconds=60,
        state_repository=_repository(tmp_path),
    )
    token, actor = first.login("alice", "correct horse battery staple")  # type: ignore[misc]
    assert actor.actor_id == "customer_001"

    restarted = AuthSessionStore(
        accounts,
        secret_key="s" * 32,
        ttl_seconds=60,
        state_repository=_repository(tmp_path),
    )
    assert restarted.actor_for_session(token) == actor
    assert restarted.revoke(token) is True
    assert restarted.actor_for_session(token) is None
    assert restarted.revoke(token) is False

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'auth.db'}", future=True)
    with engine.connect() as connection:
        digest = connection.scalar(select(AuthSessionRow.token_digest))
        assert digest is not None
        assert digest != token
        assert token not in json.dumps({"token_digest": digest})


def test_durable_sessions_expire_and_removed_accounts_cannot_use_old_role(tmp_path) -> None:
    accounts = (_account("alice", "customer_001", "customer"),)
    repository = _repository(tmp_path)
    now = datetime.now(timezone.utc)
    repository.create_session(
        token_digest="a" * 64,
        username="alice",
        created_at=now - timedelta(seconds=61),
        expires_at=now - timedelta(seconds=1),
    )
    store = AuthSessionStore(
        accounts,
        secret_key="s" * 32,
        ttl_seconds=60,
        state_repository=repository,
    )
    assert repository.active_username("a" * 64, now=now) is None

    # A session is not an authority by itself; the current server account map
    # must still contain the username and role before it can be used.
    fresh_token, _ = store.login("alice", "correct horse battery staple")  # type: ignore[misc]
    store_without_account = AuthSessionStore(
        (), secret_key="s" * 32, ttl_seconds=60, state_repository=repository
    )
    assert store_without_account.actor_for_session(fresh_token) is None


def test_durable_sessions_keep_customer_and_staff_roles_isolated(tmp_path) -> None:
    accounts = (
        _account("alice", "customer_001", "customer"),
        _account("bob", "support_001", "support_agent"),
    )
    repository = _repository(tmp_path)
    store = AuthSessionStore(
        accounts,
        secret_key="s" * 32,
        ttl_seconds=60,
        state_repository=repository,
    )
    alice_token, alice = store.login("alice", "correct horse battery staple")  # type: ignore[misc]
    bob_token, bob = store.login("bob", "correct horse battery staple")  # type: ignore[misc]

    restarted = AuthSessionStore(
        accounts,
        secret_key="s" * 32,
        ttl_seconds=60,
        state_repository=_repository(tmp_path),
    )
    assert restarted.actor_for_session(alice_token) == alice
    assert restarted.actor_for_session(bob_token) == bob
    assert restarted.actor_for_session(alice_token).role != "support_agent"  # type: ignore[union-attr]
    assert restarted.actor_for_session(bob_token).role == "support_agent"  # type: ignore[union-attr]


def test_durable_admission_is_atomic_across_two_instances(tmp_path) -> None:
    first = AuthStateRepository(f"sqlite+pysqlite:///{tmp_path / 'auth.db'}")
    AuthStateBase.metadata.create_all(first._engine)  # noqa: SLF001 - schema fixture
    second = AuthStateRepository(f"sqlite+pysqlite:///{tmp_path / 'auth.db'}")
    limiters = [
        AdmissionLimiter(limit=1, window_seconds=60, state_repository=first),
        AdmissionLimiter(limit=1, window_seconds=60, state_repository=second),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda limiter: limiter.check(("ip:shared", "username:alice"), now=1_700_000_000),
                limiters,
            )
        )

    assert sum(result.allowed for result in results) == 1
    assert all(result.retry_after_seconds >= 1 for result in results if not result.allowed)

    with first._session_factory() as session:  # noqa: SLF001 - focused persistence check
        rows = session.scalars(select(AuthAdmissionWindowRow)).all()
        assert {row.bucket_key for row in rows} == {"ip:shared", "username:alice"}
        assert {row.event_count for row in rows} == {1}


def test_unmigrated_auth_state_fails_closed_without_creating_schema(tmp_path) -> None:
    repository = _repository(tmp_path, schema=False)
    store = AuthSessionStore(
        (_account("alice", "customer_001", "customer"),),
        secret_key="s" * 32,
        ttl_seconds=60,
        state_repository=repository,
    )
    limiter = AdmissionLimiter(limit=1, window_seconds=60, state_repository=repository)

    with pytest.raises(AuthStateUnavailable):
        store.login("alice", "correct horse battery staple")
    with pytest.raises(AuthStateUnavailable):
        limiter.check(("ip:127.0.0.1",), now=1_700_000_000)

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'auth.db'}", future=True)
    assert "auth_sessions" not in inspect(engine).get_table_names()
    assert "auth_admission_windows" not in inspect(engine).get_table_names()


@pytest.fixture()
def postgres_url() -> str:
    value = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not value or not value.startswith(("postgresql", "postgres")):
        pytest.skip("set RESOLVEAI_TEST_POSTGRES_URL for durable PostgreSQL auth checks")
    return value


def test_postgres_production_session_is_shared_across_app_instances_and_logout_is_global(
    postgres_url: str,
) -> None:
    from fastapi.testclient import TestClient

    settings = _production_settings()
    first = TestClient(create_app(database_url=postgres_url, settings=settings))
    second = TestClient(create_app(database_url=postgres_url, settings=settings))

    login = first.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    session_cookie = first.cookies.get("resolveai_session")
    csrf_cookie = first.cookies.get("resolveai_csrf")
    assert session_cookie and csrf_cookie
    second.cookies.set("resolveai_session", session_cookie)
    second.cookies.set("resolveai_csrf", csrf_cookie)

    assert second.get("/api/v1/me").json()["actor_id"] == "customer_001"
    assert second.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": login.json()["csrf_token"]}
    ).status_code == 204
    assert first.get("/api/v1/me").status_code == 401


def test_postgres_admission_window_is_atomic_across_app_instances(
    postgres_url: str,
) -> None:
    key = f"m22-pg-{uuid4().hex}"
    repositories = [AuthStateRepository(postgres_url), AuthStateRepository(postgres_url)]
    limiters = [
        AdmissionLimiter(limit=1, window_seconds=60, state_repository=repository)
        for repository in repositories
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda limiter: limiter.check((key,), now=1_700_000_000), limiters
            )
        )
    assert sum(result.allowed for result in results) == 1
    assert all(result.retry_after_seconds >= 1 for result in results if not result.allowed)
