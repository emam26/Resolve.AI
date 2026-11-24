"""Durable production authentication state.

The application keeps demo authentication intentionally in memory.  Production
sessions and admission windows, however, must be shared by application
instances and survive a process restart when PostgreSQL is configured.  This
module provides only that small persistence boundary; it does not provision
schema or own account credentials.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Iterable

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    String,
    create_engine,
    delete,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class AuthStateBase(DeclarativeBase):
    """Metadata for the two managed authentication-state tables."""


class AuthSessionRow(AuthStateBase):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("length(token_digest) = 64", name="ck_auth_session_digest"),
        CheckConstraint("length(username) BETWEEN 1 AND 128", name="ck_auth_session_username"),
        CheckConstraint("expires_at > created_at", name="ck_auth_session_expiry"),
    )

    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthAdmissionWindowRow(AuthStateBase):
    __tablename__ = "auth_admission_windows"
    __table_args__ = (
        CheckConstraint("length(bucket_key) BETWEEN 1 AND 256", name="ck_auth_admission_key"),
        CheckConstraint("event_count >= 0", name="ck_auth_admission_count"),
        CheckConstraint("window_seconds > 0", name="ck_auth_admission_window"),
    )

    bucket_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)


class AuthStateUnavailable(RuntimeError):
    """Raised when managed auth state cannot be read or written safely."""


def is_postgresql_url(database_url: str | None) -> bool:
    return bool(database_url and database_url.startswith(("postgresql", "postgres")))


def _as_utc(value: datetime) -> datetime:
    """Normalize database-returned naive SQLite timestamps for comparisons."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AuthStateRepository:
    """Small SQLAlchemy repository for shared production auth state.

    The repository never creates tables.  Managed PostgreSQL schema is owned by
    Alembic, so a missing migration is reported as unavailable and callers can
    fail closed.  SQLite is supported for deterministic repository tests only.
    """

    def __init__(self, database_url: str, *, engine: Engine | None = None) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        self._engine = engine or create_engine(
            database_url,
            future=True,
            connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
        )
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)

    def create_session(
        self,
        *,
        token_digest: str,
        username: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        try:
            with self._session_factory.begin() as session:
                session.execute(
                    delete(AuthSessionRow).where(AuthSessionRow.expires_at <= created_at)
                )
                session.add(
                    AuthSessionRow(
                        token_digest=token_digest,
                        username=username,
                        created_at=created_at,
                        expires_at=expires_at,
                    )
                )
        except SQLAlchemyError as error:
            raise AuthStateUnavailable from error

    def active_username(self, token_digest: str, *, now: datetime) -> str | None:
        if not token_digest:
            return None
        try:
            with self._session_factory() as session:
                row = session.scalar(
                    select(AuthSessionRow).where(
                        AuthSessionRow.token_digest == token_digest,
                        AuthSessionRow.revoked_at.is_(None),
                        AuthSessionRow.expires_at > now,
                    )
                )
                return None if row is None else row.username
        except SQLAlchemyError as error:
            raise AuthStateUnavailable from error

    def revoke_session(self, token_digest: str, *, now: datetime) -> bool:
        if not token_digest:
            return False
        try:
            with self._session_factory.begin() as session:
                result = session.execute(
                    update(AuthSessionRow)
                    .where(
                        AuthSessionRow.token_digest == token_digest,
                        AuthSessionRow.revoked_at.is_(None),
                        AuthSessionRow.expires_at > now,
                    )
                    .values(revoked_at=now)
                )
                return result.rowcount == 1
        except SQLAlchemyError as error:
            raise AuthStateUnavailable from error

    def check_admission(
        self,
        keys: Iterable[str],
        *,
        limit: int,
        window_seconds: int,
        now: float,
    ) -> tuple[bool, int]:
        """Atomically reserve one event across all normalized keys.

        PostgreSQL row locks serialize concurrent updates.  Keys are processed
        in lexical order to avoid lock-order inversions between requests that
        share multiple buckets (for example IP plus username).
        """

        normalized = tuple(sorted(dict.fromkeys(key for key in keys if key)))
        if not normalized:
            return True, 0
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("admission limits must be positive")
        current = datetime.fromtimestamp(now, tz=timezone.utc)
        window_start = datetime.fromtimestamp(
            math.floor(now / window_seconds) * window_seconds,
            tz=timezone.utc,
        )
        try:
            with self._session_factory.begin() as session:
                rows: list[AuthAdmissionWindowRow] = []
                for key in normalized:
                    self._insert_missing_bucket(
                        session,
                        key=key,
                        window_start=window_start,
                        window_seconds=window_seconds,
                    )
                    row = session.scalar(
                        select(AuthAdmissionWindowRow)
                        .where(AuthAdmissionWindowRow.bucket_key == key)
                        .with_for_update()
                    )
                    if row is None:
                        raise AuthStateUnavailable
                    if (
                        row.window_seconds != window_seconds
                        or current
                        >= _as_utc(row.window_started_at) + timedelta(seconds=window_seconds)
                    ):
                        row.window_started_at = window_start
                        row.window_seconds = window_seconds
                        row.event_count = 0
                    rows.append(row)

                blocked = [row for row in rows if row.event_count >= limit]
                if blocked:
                    retry_at = min(
                        _as_utc(row.window_started_at) + timedelta(seconds=window_seconds)
                        for row in blocked
                    )
                    retry_after = max(1, math.ceil((retry_at - current).total_seconds()))
                    return False, retry_after

                for row in rows:
                    row.event_count += 1
                return True, 0
        except AuthStateUnavailable:
            raise
        except SQLAlchemyError as error:
            raise AuthStateUnavailable from error

    def _insert_missing_bucket(
        self,
        session,
        *,
        key: str,
        window_start: datetime,
        window_seconds: int,
    ) -> None:
        values = {
            "bucket_key": key,
            "window_started_at": window_start,
            "window_seconds": window_seconds,
            "event_count": 0,
        }
        dialect = self._engine.dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert

            statement = insert(AuthAdmissionWindowRow).values(**values).on_conflict_do_nothing(
                index_elements=["bucket_key"]
            )
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert

            statement = insert(AuthAdmissionWindowRow).values(**values).on_conflict_do_nothing(
                index_elements=["bucket_key"]
            )
        else:
            raise AuthStateUnavailable
        session.execute(statement)
