"""Persistent policy versions, sections, index state, and audit history.

This module owns the database state machine used by the M14 policy-management
service.  Alembic remains the integration point for production databases; the
repository creates tables only for the same SQLite-friendly local-test mode as
the existing conversation and refund repositories.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Iterable, Literal, Protocol
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column, relationship, sessionmaker

from .conversations import Base, create_database_engine


POLICY_STATES: Final[frozenset[str]] = frozenset(
    {"DRAFT", "INDEXING", "READY_FOR_TEST", "PUBLISHED", "UNPUBLISHED", "FAILED"}
)
POLICY_VISIBILITIES: Final[frozenset[str]] = frozenset({"public", "internal"})
POLICY_INDEX_STATES: Final[frozenset[str]] = frozenset(
    {"NOT_INDEXED", "READY", "UNAVAILABLE", "FAILED"}
)
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def validate_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise PolicyValidationError(
            f"{field_name} must use lowercase letters, digits, '.', '_' or '-'"
        )
    return normalized


class PolicyVersionRow(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "document_version", name="uq_policy_version"),
        CheckConstraint(
            "state IN ('DRAFT', 'INDEXING', 'READY_FOR_TEST', 'PUBLISHED', 'UNPUBLISHED', 'FAILED')",
            name="ck_policy_versions_state",
        ),
        CheckConstraint("visibility IN ('public', 'internal')", name="ck_policy_versions_visibility"),
        CheckConstraint("revision >= 1", name="ck_policy_versions_revision"),
        CheckConstraint(
            "index_state IN ('NOT_INDEXED', 'READY', 'UNAVAILABLE', 'FAILED')",
            name="ck_policy_versions_index_state",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # The title is retained for compatibility with the earlier local draft;
    # the frozen M14 API uses document_id as the public policy name.
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    release_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    index_state: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_INDEXED")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sections: Mapped[list["PolicySectionRow"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="PolicySectionRow.position",
    )


class PolicyDocumentRow(Base):
    """Lock row that serializes activation for one logical document."""

    __tablename__ = "policy_documents"

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicySectionRow(Base):
    __tablename__ = "policy_sections"
    __table_args__ = (UniqueConstraint("version_id", "section", name="uq_policy_section"),)

    section_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("policy_versions.version_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[PolicyVersionRow] = relationship(back_populates="sections")


class PolicyIndexRow(Base):
    """Local materialized index manifest; vector indexing is injected separately."""

    __tablename__ = "policy_index_entries"
    __table_args__ = (
        UniqueConstraint("version_id", "section", name="uq_policy_index_section"),
        CheckConstraint("index_state IN ('READY', 'STALE')", name="ck_policy_index_state"),
    )

    index_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("policy_versions.version_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_version: Mapped[str] = mapped_column(String(64), nullable=False)
    release_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    section: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    index_state: Mapped[str] = mapped_column(String(32), nullable=False, default="READY")
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyAuditRow(Base):
    __tablename__ = "policy_audit_log"

    audit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_version: Mapped[str] = mapped_column(String(64), nullable=False)
    release_id: Mapped[str] = mapped_column(String(128), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyIndexJobRow(Base):
    """Durable state for one managed-policy index attempt.

    The row is deliberately independent of the vector table.  A future
    updater can use ``version_id`` to replace the managed embedding rows, but
    publication only observes the terminal ``SUCCEEDED`` result recorded by
    this lifecycle transaction.
    """

    __tablename__ = "policy_index_jobs"
    __table_args__ = (
        UniqueConstraint("version_id", "attempt", name="uq_policy_index_job_attempt"),
        CheckConstraint(
            "state IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')",
            name="ck_policy_index_job_state",
        ),
        CheckConstraint("attempt >= 1", name="ck_policy_index_job_attempt"),
    )

    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("policy_versions.version_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@dataclass(frozen=True)
class PolicySection:
    section: str
    text: str


@dataclass(frozen=True)
class StoredPolicyVersion:
    version_id: str
    document_id: str
    document_version: str
    title: str
    visibility: str
    release_id: str
    state: str
    is_active: bool
    revision: int
    index_state: str
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    effective_from: datetime | None
    effective_to: datetime | None
    content_hash: str
    sections: tuple[PolicySection, ...]


@dataclass(frozen=True)
class StoredPolicyAudit:
    audit_id: str
    actor_id: str
    actor_role: str
    action: str
    document_id: str
    document_version: str
    release_id: str
    from_state: str | None
    to_state: str | None
    metadata: dict[str, object]
    revision: int | None
    created_at: datetime


class PolicyConflict(RuntimeError):
    """Raised for stale revisions or invalid policy state transitions."""

    def __init__(
        self,
        message: str,
        *,
        current_revision: int | None = None,
        current_state: str | None = None,
    ) -> None:
        super().__init__(message)
        self.current_revision = current_revision
        self.current_state = current_state


class PolicyValidationError(ValueError):
    """Raised when a policy draft cannot be stored or published safely."""


class PolicyIndexUpdateError(RuntimeError):
    """Raised when an index callback fails; the lifecycle transaction is rolled back."""


PolicyIndexResult = Literal["READY", "UNAVAILABLE"]


class PolicyIndexUpdater(Protocol):
    def __call__(self, policy: StoredPolicyVersion) -> PolicyIndexResult: ...


class PolicyRepository:
    """Database-backed policy lifecycle and audit repository.

    The caller supplies the index callback.  It is called while the lifecycle
    transaction holds the per-document lock.  A callback failure aborts the
    transaction, preserving the previous active version.  With no callback,
    publication is explicit ``UNAVAILABLE`` rather than falsely reporting a
    successful retrieval-index update.
    """

    def __init__(
        self,
        database_url: str = "sqlite+pysqlite:///:memory:",
        *,
        engine: Engine | None = None,
        initialize_schema: bool | None = None,
        index_updater: PolicyIndexUpdater | None = None,
    ) -> None:
        self._engine = engine or create_database_engine(database_url)
        if initialize_schema is None:
            initialize_schema = self._engine.dialect.name == "sqlite"
        if initialize_schema:
            Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        self._index_updater = index_updater
        self.recover_interrupted_indexing()

    @property
    def engine(self) -> Engine:
        return self._engine

    def database_ready(self) -> bool:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    def _index_jobs_enabled(self) -> bool:
        """Allow old databases to keep the M14 callback contract during upgrade.

        Alembic revision 20261123_06 creates the job table.  SQLite test
        databases created from metadata have it immediately; a PostgreSQL
        database still on M14 can continue using the prior lifecycle until
        that migration is applied, without claiming durable job evidence.
        """

        return inspect(self._engine).has_table("policy_index_jobs")

    @staticmethod
    def _hash_sections(sections: Iterable[PolicySection]) -> str:
        payload = [{"section": item.section, "text": item.text} for item in sections]
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def validate_sections(sections: Iterable[PolicySection]) -> list[str]:
        items = list(sections)
        errors: list[str] = []
        if not items:
            errors.append("at least one section is required")
        seen: set[str] = set()
        for position, item in enumerate(items):
            section = item.section.strip()
            content = item.text.strip()
            if not section:
                errors.append(f"sections[{position}].section is required")
            elif len(section) > 255 or any(ord(char) < 32 for char in section):
                errors.append(f"sections[{position}].section is invalid")
            if section.casefold() in seen:
                errors.append(f"duplicate section: {section}")
            seen.add(section.casefold())
            if not content:
                errors.append(f"sections[{position}].text is required")
            if len(content) > 100_000:
                errors.append(f"sections[{position}].text exceeds 100000 characters")
        return errors

    @classmethod
    def _normalize_sections(cls, sections: Iterable[PolicySection]) -> tuple[PolicySection, ...]:
        items = tuple(
            PolicySection(section=item.section.strip(), text=item.text.strip())
            for item in sections
        )
        errors = cls.validate_sections(items)
        if errors:
            raise PolicyValidationError("; ".join(errors))
        return items

    @staticmethod
    def _audit(
        session,
        *,
        actor_id: str,
        actor_role: str,
        action: str,
        row: PolicyVersionRow,
        from_state: str | None,
        to_state: str | None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        # Keep the optimistic-lock revision alongside every audit event.  The
        # revision is derived from the version row at the transition boundary
        # so API consumers can correlate a write with the state they observed,
        # without requiring a second mutable audit column.
        audit_metadata = dict(metadata or {})
        audit_metadata.setdefault("revision", row.revision)
        session.add(
            PolicyAuditRow(
                audit_id=f"pa_{uuid4().hex}",
                actor_id=actor_id,
                actor_role=actor_role,
                action=action,
                document_id=row.document_id,
                document_version=row.document_version,
                release_id=row.release_id,
                from_state=from_state,
                to_state=to_state,
                metadata_json=json.dumps(audit_metadata, sort_keys=True),
                created_at=datetime.now(timezone.utc),
            )
        )

    @staticmethod
    def _ensure_document(session, document_id: str, now: datetime) -> PolicyDocumentRow:
        document = session.get(PolicyDocumentRow, document_id, with_for_update=True)
        if document is None:
            document = PolicyDocumentRow(document_id=document_id, updated_at=now)
            session.add(document)
            session.flush()
        return document

    @staticmethod
    def _lock_document(session, document_id: str, now: datetime) -> PolicyDocumentRow:
        document = session.scalar(
            select(PolicyDocumentRow)
            .where(PolicyDocumentRow.document_id == document_id)
            .with_for_update()
        )
        if document is None:
            document = PolicyDocumentRow(document_id=document_id, updated_at=now)
            session.add(document)
            session.flush()
        else:
            document.updated_at = now
        return document

    def create(
        self,
        *,
        actor_id: str,
        actor_role: str = "merchant_admin",
        document_id: str,
        document_version: str | None = None,
        release_id: str | None = None,
        visibility: str,
        sections: Iterable[PolicySection],
        title: str | None = None,
    ) -> StoredPolicyVersion:
        document_id = validate_identifier(document_id, "document_id")
        if document_version is None:
            document_version = "v1"
        document_version = validate_identifier(document_version, "document_version")
        if release_id is None:
            release_id = f"release_{uuid4().hex}"
        release_id = validate_identifier(release_id, "release_id")
        visibility = visibility.strip().lower()
        if visibility not in POLICY_VISIBILITIES:
            raise PolicyValidationError("visibility must be public or internal")
        items = self._normalize_sections(sections)
        now = datetime.now(timezone.utc)
        try:
            with self._session_factory.begin() as session:
                self._ensure_document(session, document_id, now)
                duplicate = session.scalar(
                    select(PolicyVersionRow).where(
                        PolicyVersionRow.document_id == document_id,
                        PolicyVersionRow.document_version == document_version,
                    )
                )
                if duplicate is not None:
                    raise PolicyConflict("policy version already exists")
                row = PolicyVersionRow(
                    version_id=f"pv_{uuid4().hex}",
                    document_id=document_id,
                    document_version=document_version,
                    title=(title or document_id).strip(),
                    visibility=visibility,
                    release_id=release_id,
                    state="DRAFT",
                    is_active=False,
                    revision=1,
                    index_state="NOT_INDEXED",
                    failure_reason=None,
                    created_at=now,
                    updated_at=now,
                    effective_from=None,
                    effective_to=None,
                    content_hash=self._hash_sections(items),
                )
                row.sections = [
                    PolicySectionRow(section=item.section, text=item.text, position=index)
                    for index, item in enumerate(items)
                ]
                session.add(row)
                session.flush()
                self._audit(
                    session,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    action="CREATE_DRAFT",
                    row=row,
                    from_state=None,
                    to_state="DRAFT",
                )
        except IntegrityError as error:
            raise PolicyConflict("policy version or release already exists") from error
        return self.get(document_id, document_version)  # type: ignore[return-value]

    def get(self, document_id: str, document_version: str) -> StoredPolicyVersion | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(PolicyVersionRow).where(
                    PolicyVersionRow.document_id == document_id,
                    PolicyVersionRow.document_version == document_version,
                )
            )
            return None if row is None else self._stored(row)

    def get_by_id(self, version_id: str) -> StoredPolicyVersion | None:
        with self._session_factory() as session:
            row = session.get(PolicyVersionRow, version_id)
            return None if row is None else self._stored(row)

    def list(
        self,
        *,
        query: str | None = None,
        state: str | None = None,
        visibility: str | None = None,
        document_id: str | None = None,
    ) -> list[StoredPolicyVersion]:
        with self._session_factory() as session:
            statement = select(PolicyVersionRow).order_by(
                PolicyVersionRow.document_id,
                PolicyVersionRow.document_version,
            )
            if state:
                statement = statement.where(PolicyVersionRow.state == state)
            if visibility:
                statement = statement.where(PolicyVersionRow.visibility == visibility)
            if document_id:
                statement = statement.where(PolicyVersionRow.document_id == document_id)
            records = [self._stored(row) for row in session.scalars(statement).all()]
        terms = tuple((query or "").casefold().split())
        if not terms:
            return records
        return [
            item
            for item in records
            if all(
                term in (
                    item.document_id
                    + " "
                    + item.title
                    + " "
                    + " ".join(section.text for section in item.sections)
                ).casefold()
                for term in terms
            )
        ]

    def validate(self, version_id: str) -> list[str]:
        record = self.get_by_id(version_id)
        if record is None:
            raise KeyError(version_id)
        return self.validate_sections(record.sections)

    def index(
        self,
        version_id: str,
        *,
        actor_id: str,
        actor_role: str = "merchant_admin",
        fail_reason: str | None = None,
        expected_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> StoredPolicyVersion:
        """Run one durable index attempt and stop at READY_FOR_TEST.

        A callback is still the integration boundary for the actual vector
        updater.  The job row records whether that callback completed, failed,
        or was interrupted; no policy becomes publishable until it completed
        successfully.
        """
        errors = self.validate(version_id)
        now = datetime.now(timezone.utc)
        callback_error: PolicyIndexUpdateError | None = None
        with self._session_factory.begin() as session:
            row = session.scalar(
                select(PolicyVersionRow)
                .where(PolicyVersionRow.version_id == version_id)
                .with_for_update()
            )
            if row is None:
                raise KeyError(version_id)
            if expected_revision is not None:
                self._check_revision(row, expected_revision)
            if row.state == "READY_FOR_TEST":
                return self._stored(row)
            if row.state == "PUBLISHED" and row.is_active:
                return self._stored(row)
            if row.state not in {"DRAFT", "FAILED", "UNPUBLISHED"}:
                raise PolicyConflict(
                    f"cannot index policy in state {row.state}",
                    current_revision=row.revision,
                    current_state=row.state,
                )
            jobs_enabled = self._index_jobs_enabled()
            if jobs_enabled and idempotency_key is not None:
                previous = session.scalar(
                    select(PolicyIndexJobRow)
                    .where(
                        PolicyIndexJobRow.version_id == version_id,
                        PolicyIndexJobRow.idempotency_key == idempotency_key,
                    )
                    .order_by(PolicyIndexJobRow.attempt.desc())
                )
                if previous is not None:
                    if previous.state == "RUNNING":
                        raise PolicyConflict(
                            "policy index attempt is already running",
                            current_revision=row.revision,
                            current_state=row.state,
                        )
                    return self._stored(row)

            job: PolicyIndexJobRow | None = None
            if jobs_enabled:
                latest_attempt = session.scalar(
                    select(PolicyIndexJobRow.attempt)
                    .where(PolicyIndexJobRow.version_id == version_id)
                    .order_by(PolicyIndexJobRow.attempt.desc())
                ) or 0
                job = PolicyIndexJobRow(
                    job_id=f"pij_{uuid4().hex}",
                    version_id=version_id,
                    attempt=latest_attempt + 1,
                    state="RUNNING",
                    actor_id=actor_id,
                    actor_role=actor_role,
                    idempotency_key=idempotency_key,
                    failure_reason=None,
                    created_at=now,
                    started_at=now,
                    finished_at=None,
                )
                session.add(job)
                session.flush()
            old_state = row.state
            row.state = "INDEXING"
            row.index_state = "NOT_INDEXED"
            row.updated_at = now
            self._audit(
                session,
                actor_id=actor_id,
                actor_role=actor_role,
                action="INDEX_JOB_STARTED" if job is not None else "START_INDEX",
                row=row,
                from_state=old_state,
                to_state="INDEXING",
                metadata=(
                    {"job_id": job.job_id, "attempt": job.attempt}
                    if job is not None
                    else None
                ),
            )
            if errors or fail_reason:
                row.state = "FAILED"
                row.index_state = "FAILED"
                row.failure_reason = fail_reason or "; ".join(errors)
                row.revision += 1
                row.updated_at = datetime.now(timezone.utc)
                self._audit(
                    session,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    action="INDEX_JOB_FAILED" if job is not None else "INDEX_FAILED",
                    row=row,
                    from_state="INDEXING",
                    to_state="FAILED",
                    metadata={
                        "reason": row.failure_reason,
                        **(
                            {"job_id": job.job_id, "attempt": job.attempt}
                            if job is not None
                            else {}
                        ),
                    },
                )
                if job is not None:
                    job.state = "FAILED"
                    job.failure_reason = row.failure_reason
                    job.finished_at = row.updated_at
            else:
                try:
                    index_state = self._run_index_update(row)
                except PolicyIndexUpdateError as error:
                    callback_error = error
                    index_state = "UNAVAILABLE"
                if index_state != "READY":
                    row.state = "FAILED"
                    row.index_state = "UNAVAILABLE"
                    row.failure_reason = (
                        "policy index updater failed"
                        if callback_error is not None
                        else "retrieval index updater is unavailable"
                    )
                    row.revision += 1
                    row.updated_at = datetime.now(timezone.utc)
                    self._audit(
                        session,
                        actor_id=actor_id,
                        actor_role=actor_role,
                        action="INDEX_JOB_FAILED" if job is not None else "INDEX_FAILED",
                        row=row,
                        from_state="INDEXING",
                        to_state="FAILED",
                        metadata={
                            "reason": row.failure_reason,
                            **(
                                {"job_id": job.job_id, "attempt": job.attempt}
                                if job is not None
                                else {}
                            ),
                        },
                    )
                    if job is not None:
                        job.state = "FAILED"
                        job.failure_reason = row.failure_reason
                        job.finished_at = row.updated_at
                else:
                    self._write_index_rows(session, row, now)
                    row.state = "READY_FOR_TEST"
                    row.index_state = "READY"
                    row.failure_reason = None
                    row.revision += 1
                    row.updated_at = datetime.now(timezone.utc)
                    self._audit(
                        session,
                        actor_id=actor_id,
                        actor_role=actor_role,
                        action="INDEX_JOB_SUCCEEDED" if job is not None else "INDEX_READY",
                        row=row,
                        from_state="INDEXING",
                        to_state="READY_FOR_TEST",
                        metadata=(
                            {"job_id": job.job_id, "attempt": job.attempt}
                            if job is not None
                            else None
                        ),
                    )
                    if job is not None:
                        job.state = "SUCCEEDED"
                        job.finished_at = row.updated_at
        if callback_error is not None:
            raise callback_error
        return self.get_by_id(version_id)  # type: ignore[return-value]

    def update_draft(
        self,
        document_id: str,
        document_version: str,
        *,
        actor_id: str,
        actor_role: str = "merchant_admin",
        expected_revision: int = 1,
        release_id: str,
        visibility: str,
        sections: Iterable[PolicySection],
        title: str | None = None,
    ) -> StoredPolicyVersion:
        release_id = validate_identifier(release_id, "release_id")
        visibility = visibility.strip().lower()
        if visibility not in POLICY_VISIBILITIES:
            raise PolicyValidationError("visibility must be public or internal")
        items = self._normalize_sections(sections)
        now = datetime.now(timezone.utc)
        with self._session_factory.begin() as session:
            row = session.scalar(
                select(PolicyVersionRow)
                .where(
                    PolicyVersionRow.document_id == document_id,
                    PolicyVersionRow.document_version == document_version,
                )
                .with_for_update()
            )
            if row is None:
                raise KeyError(document_version)
            self._check_revision(row, expected_revision)
            if row.state != "DRAFT":
                raise PolicyConflict(
                    "only draft policies can be edited",
                    current_revision=row.revision,
                    current_state=row.state,
                )
            old_state = row.state
            if title is not None:
                normalized_title = title.strip()
                if not normalized_title:
                    raise PolicyValidationError("title is required")
                row.title = normalized_title
            row.release_id = release_id
            row.visibility = visibility
            # Delete rows explicitly before inserting replacements.  Relying
            # on relationship orphan ordering can violate the unique
            # (version_id, section) constraint on SQLite and PostgreSQL.
            session.execute(delete(PolicySectionRow).where(PolicySectionRow.version_id == row.version_id))
            session.flush()
            row.sections = [
                PolicySectionRow(section=item.section, text=item.text, position=index)
                for index, item in enumerate(items)
            ]
            row.content_hash = self._hash_sections(items)
            row.index_state = "NOT_INDEXED"
            row.failure_reason = None
            row.revision += 1
            row.updated_at = now
            session.execute(delete(PolicyIndexRow).where(PolicyIndexRow.version_id == row.version_id))
            self._audit(
                session,
                actor_id=actor_id,
                actor_role=actor_role,
                action="EDIT_DRAFT",
                row=row,
                from_state=old_state,
                to_state=row.state,
                metadata={"revision": row.revision},
            )
        return self.get(document_id, document_version)  # type: ignore[return-value]

    def publish(
        self,
        document_id: str,
        document_version: str,
        *,
        actor_id: str,
        actor_role: str = "merchant_admin",
        expected_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> StoredPolicyVersion:
        # A draft must pass through the durable index-attempt state machine
        # before publication. This keeps direct publish requests equivalent to
        # the explicit index-then-publish API flow.
        draft = self.get(document_id, document_version)
        if draft is None:
            raise KeyError(document_version)
        publish_expected_revision = expected_revision
        if draft.state == "DRAFT":
            indexed = self.index(
                draft.version_id,
                actor_id=actor_id,
                actor_role=actor_role,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
            )
            if indexed.state != "READY_FOR_TEST":
                raise PolicyConflict(
                    "policy index is unavailable; publication was not activated",
                    current_revision=indexed.revision,
                    current_state=indexed.state,
                )
            publish_expected_revision = indexed.revision
        now = datetime.now(timezone.utc)
        with self._session_factory.begin() as session:
            self._lock_document(session, document_id, now)
            row = session.scalar(
                select(PolicyVersionRow)
                .where(
                    PolicyVersionRow.document_id == document_id,
                    PolicyVersionRow.document_version == document_version,
                )
                .with_for_update()
            )
            if row is None:
                raise KeyError(document_version)
            if publish_expected_revision is not None:
                self._check_revision(row, publish_expected_revision)
            if row.state == "PUBLISHED" and row.is_active:
                return self._stored(row)
            if row.state not in {"DRAFT", "READY_FOR_TEST"}:
                raise PolicyConflict(
                    "policy must be DRAFT or READY_FOR_TEST before publish",
                    current_revision=row.revision,
                    current_state=row.state,
                )
            if not row.sections or self.validate_sections(
                PolicySection(section=item.section, text=item.text) for item in row.sections
            ):
                raise PolicyValidationError("policy sections are invalid")

            publish_from_state = row.state
            index_state = row.index_state
            if index_state != "READY":
                raise PolicyConflict(
                    "policy index is not ready",
                    current_revision=row.revision,
                    current_state=row.state,
                )
            previous = session.scalars(
                select(PolicyVersionRow)
                .where(
                    PolicyVersionRow.document_id == document_id,
                    PolicyVersionRow.is_active.is_(True),
                    PolicyVersionRow.version_id != row.version_id,
                )
                .with_for_update()
            ).all()
            for prior in previous:
                old_state = prior.state
                prior.is_active = False
                prior.state = "UNPUBLISHED"
                prior.effective_to = now
                prior.updated_at = now
                prior.revision += 1
                self._audit(
                    session,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    action="DEACTIVATE",
                    row=prior,
                    from_state=old_state,
                    to_state="UNPUBLISHED",
                    metadata={"replacement_version": row.document_version},
                )
                session.execute(
                    update(PolicyIndexRow)
                    .where(PolicyIndexRow.version_id == prior.version_id)
                    .values(index_state="STALE")
                )
            row.state = "PUBLISHED"
            row.is_active = True
            row.index_state = index_state
            row.effective_from = row.effective_from or now
            row.effective_to = None
            row.failure_reason = None
            row.revision += 1
            row.updated_at = now
            self._audit(
                session,
                actor_id=actor_id,
                actor_role=actor_role,
                action="PUBLISH",
                row=row,
                from_state=publish_from_state,
                to_state="PUBLISHED",
                metadata={"index_state": index_state, "revision": row.revision, "idempotency_key": idempotency_key},
            )
        return self.get(document_id, document_version)  # type: ignore[return-value]

    def rollback(
        self,
        document_id: str,
        document_version: str,
        *,
        target_version: str,
        actor_id: str,
        actor_role: str,
        expected_revision: int,
    ) -> StoredPolicyVersion:
        target_version = validate_identifier(target_version, "target_version")
        if target_version == document_version:
            raise PolicyConflict("rollback target must differ from the current version")
        target_snapshot = self.get(document_id, target_version)
        if target_snapshot is None:
            raise KeyError(target_version)
        if target_snapshot.state == "UNPUBLISHED":
            indexed_target = self.index(
                target_snapshot.version_id,
                actor_id=actor_id,
                actor_role=actor_role,
                expected_revision=target_snapshot.revision,
            )
            if indexed_target.state != "READY_FOR_TEST":
                raise PolicyConflict(
                    "rollback target index is unavailable; active version was preserved",
                    current_revision=target_snapshot.revision,
                    current_state=indexed_target.state,
                )
        now = datetime.now(timezone.utc)
        with self._session_factory.begin() as session:
            self._lock_document(session, document_id, now)
            current = session.scalar(
                select(PolicyVersionRow)
                .where(
                    PolicyVersionRow.document_id == document_id,
                    PolicyVersionRow.document_version == document_version,
                )
                .with_for_update()
            )
            target = session.scalar(
                select(PolicyVersionRow)
                .where(
                    PolicyVersionRow.document_id == document_id,
                    PolicyVersionRow.document_version == target_version,
                )
                .with_for_update()
            )
            if current is None or target is None:
                raise KeyError(document_version if current is None else target_version)
            self._check_revision(current, expected_revision)
            if current.state != "PUBLISHED" or not current.is_active:
                raise PolicyConflict(
                    "only the active published version can be rolled back",
                    current_revision=current.revision,
                    current_state=current.state,
                )
            if target.state not in {"UNPUBLISHED", "READY_FOR_TEST"} or target.effective_from is None:
                raise PolicyConflict(
                    "rollback target must be a previously published version",
                    current_revision=target.revision,
                    current_state=target.state,
                )
            if self.validate_sections(
                PolicySection(section=item.section, text=item.text) for item in target.sections
            ):
                raise PolicyValidationError("rollback target sections are invalid")

            index_state = target.index_state
            if index_state != "READY":
                raise PolicyConflict(
                    "rollback target index is unavailable; active version was preserved",
                    current_revision=current.revision,
                    current_state=current.state,
                )
            current.state = "UNPUBLISHED"
            current.is_active = False
            current.effective_to = now
            current.updated_at = now
            current.revision += 1
            session.execute(
                update(PolicyIndexRow)
                .where(PolicyIndexRow.version_id == current.version_id)
                .values(index_state="STALE")
            )
            target.state = "PUBLISHED"
            target.is_active = True
            target.index_state = index_state
            target.effective_to = None
            target.revision += 1
            target.updated_at = now
            self._write_index_rows(session, target, now)
            self._audit(
                session,
                actor_id=actor_id,
                actor_role=actor_role,
                action="ROLLBACK",
                row=current,
                from_state="PUBLISHED",
                to_state="UNPUBLISHED",
                metadata={
                    "target_version": target_version,
                    "target_revision": target.revision,
                    "index_state": index_state,
                },
            )
        return self.get(document_id, target_version)  # type: ignore[return-value]

    def audits(
        self,
        *,
        document_id: str,
        document_version: str,
        limit: int = 100,
    ) -> list[StoredPolicyAudit]:
        with self._session_factory() as session:
            row = session.scalar(
                select(PolicyVersionRow).where(
                    PolicyVersionRow.document_id == document_id,
                    PolicyVersionRow.document_version == document_version,
                )
            )
            if row is None:
                return []
            rows = session.scalars(
                select(PolicyAuditRow)
                .where(
                    PolicyAuditRow.document_id == document_id,
                    PolicyAuditRow.document_version == document_version,
                )
                .order_by(PolicyAuditRow.created_at.desc(), PolicyAuditRow.audit_id.desc())
                .limit(max(1, min(limit, 200)))
            ).all()
            return [self._stored_audit(item) for item in rows]

    def recent_audits(self, *, limit: int = 100) -> list[StoredPolicyAudit]:
        with self._session_factory() as session:
            rows = session.scalars(select(PolicyAuditRow).order_by(
                PolicyAuditRow.created_at.desc(), PolicyAuditRow.audit_id.desc()
            ).limit(max(1, min(limit, 100)))).all()
            return [self._stored_audit(row) for row in rows]

    def recover_interrupted_indexing(self) -> int:
        with self._session_factory.begin() as session:
            recovered_jobs = []
            if self._index_jobs_enabled():
                recovered_jobs = session.scalars(
                    select(PolicyIndexJobRow).where(PolicyIndexJobRow.state == "RUNNING")
                ).all()
                for job in recovered_jobs:
                    job.state = "INTERRUPTED"
                    job.failure_reason = "indexing interrupted; restart required"
                    job.finished_at = datetime.now(timezone.utc)
            rows = session.scalars(
                select(PolicyVersionRow).where(PolicyVersionRow.state == "INDEXING")
            ).all()
            for row in rows:
                row.state = "FAILED"
                row.index_state = "FAILED"
                row.failure_reason = "indexing interrupted; restart required"
                row.revision += 1
                row.updated_at = datetime.now(timezone.utc)
                self._audit(
                    session,
                    actor_id="system:restart",
                    actor_role="system",
                    action="RECOVER_INDEX",
                    row=row,
                    from_state="INDEXING",
                    to_state="FAILED",
                    metadata={
                        "interrupted_jobs": [
                            job.job_id for job in recovered_jobs if job.version_id == row.version_id
                        ]
                    },
                )
            return len(rows) + len(recovered_jobs)

    def _run_index_update(self, row: PolicyVersionRow) -> str:
        if self._index_updater is None:
            return "UNAVAILABLE"
        payload = self._stored(row)
        try:
            result = self._index_updater(payload)
        except Exception as error:  # callback failures must abort publication
            raise PolicyIndexUpdateError("policy index update failed") from error
        normalized = str(result).upper()
        if normalized not in {"READY", "UNAVAILABLE"}:
            raise PolicyIndexUpdateError("policy index updater returned an invalid state")
        return normalized

    @staticmethod
    def _write_index_rows(session, row: PolicyVersionRow, now: datetime) -> None:
        session.execute(delete(PolicyIndexRow).where(PolicyIndexRow.version_id == row.version_id))
        for section in row.sections:
            session.add(
                PolicyIndexRow(
                    version_id=row.version_id,
                    document_id=row.document_id,
                    document_version=row.document_version,
                    release_id=row.release_id,
                    section=section.section,
                    text=section.text,
                    visibility=row.visibility,
                    index_state="READY",
                    indexed_at=now,
                )
            )

    @staticmethod
    def _check_revision(row: PolicyVersionRow, expected_revision: int) -> None:
        if expected_revision != row.revision:
            raise PolicyConflict(
                "stale policy revision",
                current_revision=row.revision,
                current_state=row.state,
            )

    @staticmethod
    def _stored(row: PolicyVersionRow) -> StoredPolicyVersion:
        sections = tuple(
            PolicySection(section=item.section, text=item.text)
            for item in sorted(row.sections, key=lambda item: item.position)
        )
        return StoredPolicyVersion(
            version_id=row.version_id,
            document_id=row.document_id,
            document_version=row.document_version,
            title=row.title,
            visibility=row.visibility,
            release_id=row.release_id,
            state=row.state,
            is_active=row.is_active,
            revision=row.revision,
            index_state=row.index_state,
            failure_reason=row.failure_reason,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
            effective_from=None if row.effective_from is None else _utc(row.effective_from),
            effective_to=None if row.effective_to is None else _utc(row.effective_to),
            content_hash=row.content_hash,
            sections=sections,
        )

    @staticmethod
    def _stored_audit(row: PolicyAuditRow) -> StoredPolicyAudit:
        try:
            metadata = json.loads(row.metadata_json or "{}")
        except json.JSONDecodeError:
            metadata = {}
        return StoredPolicyAudit(
            audit_id=row.audit_id,
            actor_id=row.actor_id,
            actor_role=row.actor_role,
            action=row.action,
            document_id=row.document_id,
            document_version=row.document_version,
            release_id=row.release_id,
            from_state=row.from_state,
            to_state=row.to_state,
            metadata=metadata,
            revision=metadata.get("revision") if isinstance(metadata.get("revision"), int) else None,
            created_at=_utc(row.created_at),
        )


__all__ = [
    "POLICY_INDEX_STATES",
    "POLICY_STATES",
    "POLICY_VISIBILITIES",
    "PolicyAuditRow",
    "PolicyConflict",
    "PolicyDocumentRow",
    "PolicyIndexRow",
    "PolicyIndexJobRow",
    "PolicyIndexUpdateError",
    "PolicyIndexUpdater",
    "PolicyRepository",
    "PolicySection",
    "PolicySectionRow",
    "PolicyValidationError",
    "PolicyVersionRow",
    "StoredPolicyAudit",
    "StoredPolicyVersion",
    "validate_identifier",
]
