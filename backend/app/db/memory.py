"""Bounded, customer-scoped persistence for untrusted customer memory.

Memory is an optional context source, not an authorization source.  Callers
must keep the customer identity server-established and treat every stored
value as untrusted regardless of its provenance label.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Final
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from .conversations import Base, create_database_engine


MAX_MEMORY_RECORDS_PER_CUSTOMER: Final = 50
MAX_MEMORY_CONTENT_CHARS: Final = 512
MAX_MEMORY_PROVENANCE_CHARS: Final = 64
MEMORY_PROVENANCES: Final = frozenset(
    {"customer_reported", "conversation_summary", "staff_verified"}
)
_INSERT_RETRIES: Final = 3
_MEMORY_TOKEN_PATTERN: Final = re.compile(r"[a-z0-9]+")
_MEMORY_STOP_WORDS: Final = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "for",
        "from",
        "how",
        "is",
        "it",
        "my",
        "of",
        "the",
        "to",
        "was",
        "what",
        "when",
        "where",
        "with",
        "your",
    }
)


class CustomerMemoryValidationError(ValueError):
    """Raised when a memory record does not meet its bounded input contract."""


class CustomerMemoryLimitError(ValueError):
    """Raised when a customer has reached the configured memory bound."""


class CustomerMemoryConflictError(RuntimeError):
    """Raised when concurrent writes cannot claim a bounded memory slot."""


class CustomerMemoryRow(Base):
    """A single bounded memory item owned by exactly one customer."""

    __tablename__ = "customer_memories"
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "slot",
            name="uq_customer_memory_customer_slot",
        ),
        CheckConstraint("customer_id <> ''", name="ck_customer_memory_customer_id"),
        CheckConstraint("slot >= 0", name="ck_customer_memory_slot"),
        CheckConstraint(
            f"length(content) BETWEEN 1 AND {MAX_MEMORY_CONTENT_CHARS}",
            name="ck_customer_memory_content_length",
        ),
        CheckConstraint(
            f"length(provenance) BETWEEN 1 AND {MAX_MEMORY_PROVENANCE_CHARS}",
            name="ck_customer_memory_provenance_length",
        ),
    )

    memory_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(String(MAX_MEMORY_CONTENT_CHARS), nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(MAX_MEMORY_PROVENANCE_CHARS), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class StoredCustomerMemory:
    """Transport value for a memory record after customer scoping."""

    memory_id: str
    customer_id: str
    content: str
    provenance: str
    created_at: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_customer_id(customer_id: str) -> str:
    normalized = customer_id.strip()
    if not normalized or len(normalized) > 128 or "\x00" in normalized:
        raise CustomerMemoryValidationError("customer_id must be a bounded non-empty identifier")
    return normalized


def _validate_content(content: str) -> str:
    if not isinstance(content, str):
        raise CustomerMemoryValidationError("memory content must be text")
    if "\x00" in content:
        raise CustomerMemoryValidationError("memory content contains an invalid character")
    normalized = content.strip()
    if not normalized:
        raise CustomerMemoryValidationError("memory content must not be empty")
    if len(normalized) > MAX_MEMORY_CONTENT_CHARS:
        raise CustomerMemoryValidationError(
            f"memory content exceeds {MAX_MEMORY_CONTENT_CHARS} characters"
        )
    return normalized


def _validate_provenance(provenance: str) -> str:
    normalized = provenance.strip()
    if normalized not in MEMORY_PROVENANCES:
        raise CustomerMemoryValidationError("unsupported memory provenance")
    return normalized


class CustomerMemoryRepository:
    """Persist explicitly-created memories with strict customer scoping.

    SQLite databases are initialized like the existing local repositories.  A
    PostgreSQL caller should use the corresponding Alembic migration and pass
    ``initialize_schema=False``; creating tables from request code is not a
    substitute for production migrations.
    """

    def __init__(
        self,
        database_url: str = "sqlite+pysqlite:///:memory:",
        *,
        engine: Engine | None = None,
        initialize_schema: bool | None = None,
        max_records_per_customer: int = MAX_MEMORY_RECORDS_PER_CUSTOMER,
    ) -> None:
        if not 1 <= max_records_per_customer <= MAX_MEMORY_RECORDS_PER_CUSTOMER:
            raise ValueError(
                "max_records_per_customer must be between 1 and "
                f"{MAX_MEMORY_RECORDS_PER_CUSTOMER}"
            )
        self._engine = engine or create_database_engine(database_url)
        if initialize_schema is None:
            initialize_schema = self._engine.dialect.name == "sqlite"
        if initialize_schema:
            Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        self._max_records = max_records_per_customer

    @property
    def engine(self) -> Engine:
        return self._engine

    def add(
        self,
        *,
        customer_id: str,
        content: str,
        provenance: str,
        created_at: datetime | None = None,
    ) -> StoredCustomerMemory:
        """Add one bounded memory item, never replacing an existing item."""

        owner = _validate_customer_id(customer_id)
        safe_content = _validate_content(content)
        safe_provenance = _validate_provenance(provenance)
        timestamp = _utc(created_at or datetime.now(timezone.utc))

        for attempt in range(_INSERT_RETRIES):
            memory_id = f"mem_{uuid4().hex}"
            try:
                with self._session_factory.begin() as session:
                    occupied = set(
                        session.scalars(
                            select(CustomerMemoryRow.slot)
                            .where(CustomerMemoryRow.customer_id == owner)
                            .order_by(CustomerMemoryRow.slot)
                            .with_for_update()
                        ).all()
                    )
                    if len(occupied) >= self._max_records:
                        raise CustomerMemoryLimitError(
                            "customer memory limit reached"
                        )
                    slot = next(
                        candidate
                        for candidate in range(self._max_records)
                        if candidate not in occupied
                    )
                    session.add(
                        CustomerMemoryRow(
                            memory_id=memory_id,
                            customer_id=owner,
                            slot=slot,
                            content=safe_content,
                            provenance=safe_provenance,
                            created_at=timestamp,
                        )
                    )
            except IntegrityError:
                if attempt == _INSERT_RETRIES - 1:
                    raise CustomerMemoryConflictError(
                        "concurrent customer memory write could not be completed"
                    ) from None
                continue
            stored = self.get(memory_id, customer_id=owner)
            if stored is None:
                raise CustomerMemoryConflictError("stored memory could not be reloaded")
            return stored

        raise CustomerMemoryConflictError("customer memory write could not be completed")

    def get(self, memory_id: str, *, customer_id: str) -> StoredCustomerMemory | None:
        """Read by ID only when the caller supplies the owning customer ID."""

        owner = _validate_customer_id(customer_id)
        with self._session_factory() as session:
            row = session.scalar(
                select(CustomerMemoryRow).where(
                    CustomerMemoryRow.memory_id == memory_id,
                    CustomerMemoryRow.customer_id == owner,
                )
            )
            return None if row is None else self._stored(row)

    def list_for_customer(
        self, customer_id: str, *, limit: int = MAX_MEMORY_RECORDS_PER_CUSTOMER
    ) -> list[StoredCustomerMemory]:
        """List only memories belonging to the supplied customer."""

        owner = _validate_customer_id(customer_id)
        if limit < 1:
            raise ValueError("limit must be positive")
        bounded_limit = min(limit, self._max_records)
        with self._session_factory() as session:
            rows = session.scalars(
                select(CustomerMemoryRow)
                .where(CustomerMemoryRow.customer_id == owner)
                .order_by(CustomerMemoryRow.slot)
                .limit(bounded_limit)
            ).all()
            return [self._stored(row) for row in rows]

    def select_for_context(
        self,
        customer_id: str,
        query: str,
        *,
        limit: int = 5,
    ) -> list[StoredCustomerMemory]:
        """Return bounded, customer-scoped memories ranked by lexical relevance.

        This is intentionally small and deterministic: at most the existing
        customer memory bound is read, query terms never authorize records, and
        recency breaks relevance ties.  It is continuity context only; policy
        evidence and live order facts remain authoritative elsewhere.
        """

        owner = _validate_customer_id(customer_id)
        if limit < 1:
            raise ValueError("limit must be positive")
        bounded_limit = min(limit, self._max_records)
        query_terms = {
            token
            for token in _MEMORY_TOKEN_PATTERN.findall(query.casefold())
            if token not in _MEMORY_STOP_WORDS
        }
        with self._session_factory() as session:
            rows = session.scalars(
                select(CustomerMemoryRow)
                .where(CustomerMemoryRow.customer_id == owner)
                .order_by(CustomerMemoryRow.slot.desc())
                .limit(self._max_records)
            ).all()
            ranked = sorted(
                rows,
                key=lambda row: (
                    -len(
                        query_terms
                        & set(_MEMORY_TOKEN_PATTERN.findall(row.content.casefold()))
                    ),
                    -row.slot,
                ),
            )
            return [self._stored(row) for row in ranked[:bounded_limit]]

    def count_for_customer(self, customer_id: str) -> int:
        """Return the bounded number of records for one customer."""

        return len(self.list_for_customer(customer_id))

    @staticmethod
    def _stored(row: CustomerMemoryRow) -> StoredCustomerMemory:
        return StoredCustomerMemory(
            memory_id=row.memory_id,
            customer_id=row.customer_id,
            content=row.content,
            provenance=row.provenance,
            created_at=_utc(row.created_at),
        )
