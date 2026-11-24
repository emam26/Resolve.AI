"""Small, dependency-free production authentication primitives.

Production credentials are provisioned as scrypt password hashes in backend
configuration.  This module deliberately has no HTTP or database dependency:
the API layer owns cookies and the application service owns actor
authorization.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import threading
import time
from typing import Iterable

from backend.app.contracts import ActorSummary
from backend.app.db.auth import (
    AuthStateRepository,
    AuthStateUnavailable,
    is_postgresql_url,
)


class AuthConfigurationError(ValueError):
    """Raised when a provisioned account cannot be loaded safely."""


@dataclass(frozen=True)
class ProvisionedAccount:
    username: str
    password_hash: str
    actor: ActorSummary


def _b64decode(value: str, *, label: str) -> bytes:
    try:
        encoded = value.encode("ascii")
        encoded += b"=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(encoded)
    except (ValueError, UnicodeError) as error:
        raise AuthConfigurationError(f"invalid {label}") from error
    if not decoded:
        raise AuthConfigurationError(f"invalid {label}")
    return decoded


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Create the supported scrypt format for provisioning tests/tools only."""

    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("password must contain 12 to 256 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16_384,
        r=8,
        p=1,
        dklen=32,
        maxmem=32 * 1024 * 1024,
    )
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return f"scrypt$16384$8$1${encode(salt)}${encode(digest)}"


def _verify_password(password: str, encoded: str) -> bool:
    """Verify a bounded scrypt record without revealing parse details."""

    try:
        algorithm, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$")
        if algorithm != "scrypt":
            return False
        n, r, p = int(n_text), int(r_text), int(p_text)
        if n != 16_384 or r != 8 or p != 1:
            return False
        salt = _b64decode(salt_text, label="password salt")
        expected = _b64decode(digest_text, label="password digest")
        if len(salt) != 16 or len(expected) != 32:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
            maxmem=32 * 1024 * 1024,
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, UnicodeError, ValueError, OverflowError):
        return False


def _validate_password_hash(encoded: str) -> None:
    try:
        algorithm, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$")
        if (
            algorithm != "scrypt"
            or (int(n_text), int(r_text), int(p_text)) != (16_384, 8, 1)
            or len(_b64decode(salt_text, label="password salt")) != 16
            or len(_b64decode(digest_text, label="password digest")) != 32
        ):
            raise ValueError
    except (TypeError, UnicodeError, ValueError, OverflowError, AuthConfigurationError) as error:
        raise AuthConfigurationError("production account configuration is invalid") from error


def load_provisioned_accounts(raw_json: str | None) -> tuple[ProvisionedAccount, ...]:
    """Parse trusted server-side account configuration, never request data."""

    if not raw_json or not raw_json.strip():
        return ()
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise AuthConfigurationError("production account configuration is invalid") from error
    if not isinstance(payload, list) or len(payload) > 1_000:
        raise AuthConfigurationError("production account configuration is invalid")

    accounts: list[ProvisionedAccount] = []
    seen: set[str] = set()
    roles = {"customer", "support_agent", "refund_approver", "merchant_admin"}
    for item in payload:
        if not isinstance(item, dict):
            raise AuthConfigurationError("production account configuration is invalid")
        username = str(item.get("username", "")).strip()
        password_hash = str(item.get("password_hash", "")).strip()
        actor_id = str(item.get("actor_id", "")).strip()
        role = str(item.get("role", "")).strip()
        display_name = str(item.get("display_name", "")).strip()
        customer_id = item.get("customer_id")
        permissions = item.get("permissions", [])
        key = username.casefold()
        if (
            not 1 <= len(username) <= 128
            or key in seen
            or not actor_id
            or not display_name
            or role not in roles
            or not isinstance(permissions, list)
            or not all(isinstance(value, str) and value for value in permissions)
            or (customer_id is not None and not isinstance(customer_id, str))
        ):
            raise AuthConfigurationError("production account configuration is invalid")
        _validate_password_hash(password_hash)
        seen.add(key)
        accounts.append(
            ProvisionedAccount(
                username=username,
                password_hash=password_hash,
                actor=ActorSummary(
                    actor_id=actor_id,
                    display_name=display_name,
                    role=role,
                    customer_id=customer_id,
                    permissions=list(permissions),
                ),
            )
        )
    return tuple(accounts)


class AuthSessionStore:
    """Opaque expiring sessions with a bounded local fallback.

    Tokens are random and only their HMAC digests are retained.  PostgreSQL is
    used when configured so sessions survive restart and are shared by app
    instances.  SQLite/offline callers retain the intentionally bounded
    process-local behavior used by deterministic tests.
    """

    def __init__(
        self,
        accounts: Iterable[ProvisionedAccount],
        *,
        secret_key: str,
        ttl_seconds: int,
        database_url: str | None = None,
        state_repository: AuthStateRepository | None = None,
    ) -> None:
        if len(secret_key.encode("utf-8")) < 32:
            raise AuthConfigurationError("production auth secret must be at least 32 bytes")
        if ttl_seconds <= 0:
            raise AuthConfigurationError("production session TTL must be positive")
        self._accounts = {account.username.casefold(): account for account in accounts}
        self._secret_key = secret_key.encode("utf-8")
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, tuple[ActorSummary, float]] = {}
        self._lock = threading.RLock()
        self._state_repository = state_repository
        if self._state_repository is None and is_postgresql_url(database_url):
            self._state_repository = AuthStateRepository(database_url or "")

    def _digest(self, token: str) -> str:
        try:
            token_bytes = token.encode("ascii")
        except (UnicodeEncodeError, AttributeError):
            # Bearer values are untrusted input; malformed non-ASCII tokens
            # must be treated as an unknown session rather than a 500 error.
            return ""
        return hmac.new(self._secret_key, token_bytes, hashlib.sha256).hexdigest()

    def login(self, username: str, password: str) -> tuple[str, ActorSummary] | None:
        account = self._accounts.get(username.strip().casefold())
        if account is None or not isinstance(password, str):
            return None
        if not _verify_password(password, account.password_hash):
            return None
        token = secrets.token_urlsafe(32)
        if self._state_repository is not None:
            created_at = datetime.now(timezone.utc)
            self._state_repository.create_session(
                token_digest=self._digest(token),
                username=account.username,
                created_at=created_at,
                expires_at=created_at + timedelta(seconds=self._ttl_seconds),
            )
            return token, account.actor
        with self._lock:
            self._purge_expired(time.monotonic())
            self._sessions[self._digest(token)] = (
                account.actor,
                time.monotonic() + self._ttl_seconds,
            )
        return token, account.actor

    def actor_for_session(self, token: str | None) -> ActorSummary | None:
        if not token:
            return None
        digest = self._digest(token)
        if self._state_repository is not None:
            username = self._state_repository.active_username(
                digest, now=datetime.now(timezone.utc)
            )
            if username is None:
                return None
            account = self._accounts.get(username.casefold())
            return None if account is None else account.actor
        with self._lock:
            record = self._sessions.get(digest)
            if record is None:
                return None
            actor, expires_at = record
            if time.monotonic() >= expires_at:
                self._sessions.pop(digest, None)
                return None
            return actor

    def revoke(self, token: str | None) -> bool:
        if not token:
            return False
        if self._state_repository is not None:
            return self._state_repository.revoke_session(
                self._digest(token), now=datetime.now(timezone.utc)
            )
        with self._lock:
            return self._sessions.pop(self._digest(token), None) is not None

    def _purge_expired(self, now: float) -> None:
        for digest, (_, expires_at) in tuple(self._sessions.items()):
            if now >= expires_at:
                self._sessions.pop(digest, None)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


class AdmissionLimiter:
    """Atomic fixed-window admission control with a PostgreSQL state path."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        database_url: str | None = None,
        state_repository: AuthStateRepository | None = None,
    ) -> None:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("admission limits must be positive")
        self._limit = limit
        self._window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._state_repository = state_repository
        if self._state_repository is None and is_postgresql_url(database_url):
            self._state_repository = AuthStateRepository(database_url or "")

    def check(self, keys: Iterable[str], *, now: float | None = None) -> RateLimitResult:
        normalized = tuple(dict.fromkeys(key for key in keys if key))
        if not normalized:
            return RateLimitResult(True, 0)
        if self._state_repository is not None:
            allowed, retry_after = self._state_repository.check_admission(
                normalized,
                limit=self._limit,
                window_seconds=self._window_seconds,
                now=time.time() if now is None else now,
            )
            return RateLimitResult(allowed, retry_after)
        current = time.monotonic() if now is None else now
        with self._lock:
            buckets = []
            for key in normalized:
                bucket = self._events.setdefault(key, deque())
                while bucket and current - bucket[0] >= self._window_seconds:
                    bucket.popleft()
                buckets.append(bucket)
            blocked = [bucket for bucket in buckets if len(bucket) >= self._limit]
            if blocked:
                retry = max(
                    1,
                    int(self._window_seconds - (current - min(bucket[0] for bucket in blocked))),
                )
                return RateLimitResult(False, retry)
            for bucket in buckets:
                bucket.append(current)
            return RateLimitResult(True, 0)


def parse_trusted_proxy_networks(value: str) -> tuple[object, ...]:
    """Parse explicit proxy networks; malformed entries are ignored safely."""

    networks = []
    for item in value.split(",") if value else ():
        try:
            networks.append(ipaddress.ip_network(item.strip(), strict=False))
        except ValueError:
            continue
    return tuple(networks)


def client_ip(*, remote: str | None, forwarded_for: str | None, trusted_networks: Iterable[object]) -> str:
    """Use forwarded addresses only when the direct peer is trusted."""

    remote_value = (remote or "unknown").strip()
    try:
        remote_address = ipaddress.ip_address(remote_value)
    except ValueError:
        remote_address = None
    if remote_address is not None and any(remote_address in network for network in trusted_networks):
        first = (forwarded_for or "").split(",", 1)[0].strip()
        try:
            return str(ipaddress.ip_address(first))
        except ValueError:
            return remote_value
    return remote_value
