"""PostgreSQL/pgvector policy embedding model and safe query builder."""

from __future__ import annotations

import math
from typing import Sequence

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    create_engine,
    delete,
    insert,
    or_,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from backend.app.db.policies import StoredPolicyVersion, PolicyVersionRow

from .models import PolicyAudience, PolicyEvidence, PolicyRecord
from .semantic import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_SEMANTIC_MINIMUM_SCORE,
    EmbeddingProvider,
    SUPPORTED_AUDIENCES,
)


class Base(DeclarativeBase):
    """Local declarative base until the shared database module is introduced."""


class PolicyEmbeddingRow(Base):
    """Published-policy row with a pgvector embedding.

    The vector dimension matches the default local MiniLM adapter.  The table
    deliberately stores policy metadata alongside the vector so the query can
    enforce publication and visibility before returning evidence.
    """

    __tablename__ = "policy_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "document_version",
            "section",
            "release_id",
            name="uq_policy_embedding_revision",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # NULL identifies the original seeded corpus.  Non-NULL values are owned
    # by the M14 managed policy lifecycle and must be joined to that version
    # before retrieval can expose them.
    version_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    document_id: Mapped[str] = mapped_column(String(255), nullable=False)
    document_version: Mapped[str] = mapped_column(String(64), nullable=False)
    section: Mapped[str] = mapped_column(String(255), nullable=False)
    release_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(DEFAULT_EMBEDDING_DIMENSIONS), nullable=False
    )


class PgVectorPolicyRetriever:
    """Query the published policy embedding table through the shared contract."""

    def __init__(
        self,
        database_url: str,
        embedding_provider: EmbeddingProvider,
        *,
        minimum_score: float = DEFAULT_SEMANTIC_MINIMUM_SCORE,
    ) -> None:
        if not database_url.startswith(("postgresql", "postgres")):
            raise ValueError("PgVectorPolicyRetriever requires a PostgreSQL URL")
        self._engine = create_engine(database_url, future=True)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        self._embedding_provider = embedding_provider
        self._minimum_score = minimum_score

    def retrieve_published_policy(
        self,
        query: str,
        audience: PolicyAudience = "customer",
        top_k: int = 3,
    ) -> list[PolicyEvidence]:
        return self._retrieve(
            query,
            audience=audience,
            top_k=top_k,
            minimum_score=self._minimum_score,
        )

    def retrieve_published_policy_candidates(
        self,
        query: str,
        audience: PolicyAudience = "customer",
        top_k: int = 3,
    ) -> list[PolicyEvidence]:
        """Return ranked, access-filtered candidates before the 0.60 gate.

        This is intentionally not the regular retrieval contract.  The
        evaluation layer uses it to distinguish rank quality from the answer
        gate; publication and audience filtering remain enforced by the SQL
        query itself.
        """

        return self._retrieve(
            query,
            audience=audience,
            top_k=top_k,
            minimum_score=-1.0,
        )

    def _retrieve(
        self,
        query: str,
        *,
        audience: PolicyAudience,
        top_k: int,
        minimum_score: float,
    ) -> list[PolicyEvidence]:
        if not query.strip():
            return []
        query_vectors = self._embedding_provider.embed([query])
        if len(query_vectors) != 1:
            raise ValueError("embedding provider must return one query vector")
        query_embedding = tuple(float(value) for value in query_vectors[0])
        statement = build_pgvector_policy_query(
            query_embedding,
            audience=audience,
            top_k=top_k,
            minimum_score=minimum_score,
        )
        with self._session_factory() as session:
            rows = session.execute(statement).all()
        return [
            policy_evidence_from_row(
                row,
                cosine_distance=float(distance),
                minimum_score=minimum_score,
            )
            for row, distance in rows
        ]

    def close(self) -> None:
        """Release the SQLAlchemy engine owned by this retriever."""

        self._engine.dispose()


def create_pgvector_schema(engine: Engine) -> None:
    """Create the extension and table for a provisioned PostgreSQL database."""

    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)


class ManagedPolicyIndexUpdater:
    """Atomically replace one managed policy version in ``policy_embeddings``.

    The M14 policy repository calls its updater while the version is in an
    indexing state.  This class therefore writes rows tagged with the stable
    ``version_id`` but does not decide publication.  Retrieval joins the
    version table and only exposes rows after the repository has committed an
    active ``PUBLISHED``/``READY`` state.
    """

    def __init__(
        self,
        database_url: str | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        engine: Engine | None = None,
    ) -> None:
        if embedding_provider is None:
            raise ValueError("embedding_provider is required")
        if engine is None:
            if not database_url or not database_url.startswith(("postgresql", "postgres")):
                raise ValueError("ManagedPolicyIndexUpdater requires a PostgreSQL URL")
            engine = create_engine(database_url, future=True)
        self._engine = engine
        self._embedding_provider = embedding_provider

    def __call__(self, policy: StoredPolicyVersion) -> str:
        if not policy.version_id:
            raise ValueError("managed policy version_id is required")
        texts = [f"{section.section}\n{section.text}" for section in policy.sections]
        vectors = self._embedding_provider.embed(texts)
        if len(vectors) != len(texts):
            raise ValueError("embedding provider returned an unexpected number of vectors")
        rows: list[dict[str, object]] = []
        for section, vector in zip(policy.sections, vectors):
            values = _validated_embedding(vector)
            rows.append(
                {
                    "version_id": policy.version_id,
                    "document_id": policy.document_id,
                    "document_version": policy.document_version,
                    "section": section.section,
                    "release_id": policy.release_id,
                    # The managed-state join, rather than this denormalized
                    # value, is the publication authority for managed rows.
                    "status": "published",
                    "visibility": policy.visibility,
                    "text": section.text,
                    "embedding": list(values),
                }
            )

        # All validation happens before the transaction starts.  Any delete,
        # insert, constraint error, or connection failure therefore rolls back
        # as one unit and leaves the previous version's rows intact.
        with self._engine.begin() as connection:
            connection.execute(
                delete(PolicyEmbeddingRow).where(
                    PolicyEmbeddingRow.version_id == policy.version_id
                )
            )
            if rows:
                connection.execute(insert(PolicyEmbeddingRow), rows)
        return "READY"


def seed_policy_embeddings(
    engine: Engine,
    records: Sequence[PolicyRecord],
    embedding_provider: EmbeddingProvider,
) -> None:
    """Upsert synthetic policy embeddings using a caller-supplied local embedder."""

    create_pgvector_schema(engine)
    vectors = embedding_provider.embed(
        [f"{record.section}\n{record.text}" for record in records]
    )
    if len(vectors) != len(records):
        raise ValueError("embedding provider returned an unexpected number of vectors")
    with Session(engine) as session:
        for record, vector in zip(records, vectors):
            values = _validated_embedding(vector)
            existing = session.scalar(
                select(PolicyEmbeddingRow).where(
                    PolicyEmbeddingRow.document_id == record.document_id,
                    PolicyEmbeddingRow.document_version == record.document_version,
                    PolicyEmbeddingRow.section == record.section,
                    PolicyEmbeddingRow.release_id == record.release_id,
                    PolicyEmbeddingRow.version_id.is_(None),
                )
            )
            if existing is None:
                session.add(
                    PolicyEmbeddingRow(
                        document_id=record.document_id,
                        document_version=record.document_version,
                        version_id=None,
                        section=record.section,
                        release_id=record.release_id,
                        status=record.status,
                        visibility=record.visibility,
                        text=record.text,
                        embedding=list(values),
                    )
                )
            else:
                existing.status = record.status
                existing.visibility = record.visibility
                existing.text = record.text
                existing.embedding = list(values)
        session.commit()


def build_pgvector_policy_query(
    query_embedding: Sequence[float],
    audience: PolicyAudience = "customer",
    top_k: int = 3,
    *,
    minimum_score: float = DEFAULT_SEMANTIC_MINIMUM_SCORE,
):
    """Build a parameterized, visibility-safe cosine-distance query.

    The returned SQLAlchemy statement is intentionally unbound to a session;
    callers can execute it with their configured PostgreSQL session.  Distance
    is selected alongside the row so the caller can turn it into the M2
    evidence score without another query.
    """

    _validate_query_inputs(query_embedding, audience, top_k, minimum_score)
    distance = PolicyEmbeddingRow.embedding.cosine_distance(
        list(query_embedding)
    ).label("cosine_distance")
    maximum_distance = 1.0 - minimum_score
    visibility_filter = (
        PolicyEmbeddingRow.visibility == "public"
        if audience == "customer"
        else PolicyEmbeddingRow.visibility.in_(("public", "internal"))
    )
    legacy_policy = PolicyEmbeddingRow.version_id.is_(None)
    managed_policy = and_(
        PolicyEmbeddingRow.version_id.is_not(None),
        PolicyVersionRow.version_id == PolicyEmbeddingRow.version_id,
        PolicyVersionRow.document_id == PolicyEmbeddingRow.document_id,
        PolicyVersionRow.document_version == PolicyEmbeddingRow.document_version,
        PolicyVersionRow.release_id == PolicyEmbeddingRow.release_id,
        PolicyVersionRow.visibility == PolicyEmbeddingRow.visibility,
        PolicyVersionRow.state == "PUBLISHED",
        PolicyVersionRow.is_active.is_(True),
        PolicyVersionRow.index_state == "READY",
    )
    return (
        select(PolicyEmbeddingRow, distance)
        .outerjoin(
            PolicyVersionRow,
            PolicyVersionRow.version_id == PolicyEmbeddingRow.version_id,
        )
        .where(
            PolicyEmbeddingRow.status == "published",
            visibility_filter,
            or_(legacy_policy, managed_policy),
            distance <= maximum_distance,
        )
        .order_by(
            distance.asc(),
            PolicyEmbeddingRow.document_id.asc(),
            PolicyEmbeddingRow.document_version.asc(),
            PolicyEmbeddingRow.section.asc(),
            PolicyEmbeddingRow.release_id.asc(),
        )
        .limit(top_k)
    )


def policy_evidence_from_row(
    row: PolicyEmbeddingRow,
    *,
    cosine_distance: float,
    minimum_score: float = DEFAULT_SEMANTIC_MINIMUM_SCORE,
) -> PolicyEvidence:
    """Convert a pgvector row and distance into the frozen evidence shape."""

    if not math.isfinite(cosine_distance):
        raise ValueError("cosine_distance must be finite")
    if not math.isfinite(minimum_score):
        raise ValueError("minimum_score must be finite")
    score = 1.0 - cosine_distance
    if score < minimum_score:
        raise ValueError("cosine similarity is below the semantic threshold")
    return PolicyEvidence(
        document_id=row.document_id,
        document_version=row.document_version,
        section=row.section,
        release_id=row.release_id,
        visibility=row.visibility,  # type: ignore[arg-type]
        score=score,
        text=row.text,
        status=row.status,  # type: ignore[arg-type]
        is_active=True,
    )


def _validate_query_inputs(
    query_embedding: Sequence[float],
    audience: PolicyAudience,
    top_k: int,
    minimum_score: float,
) -> None:
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise ValueError("top_k must be positive")
    if audience not in SUPPORTED_AUDIENCES:
        raise ValueError(f"unsupported audience: {audience}")
    if not math.isfinite(minimum_score) or not -1.0 <= minimum_score <= 1.0:
        raise ValueError("minimum_score must be finite and between -1 and 1")
    try:
        vector = tuple(float(value) for value in query_embedding)
    except (TypeError, ValueError) as error:
        raise ValueError("query_embedding must contain numbers") from error
    if not vector or not all(math.isfinite(value) for value in vector):
        raise ValueError("query_embedding must be non-empty and finite")
    if len(vector) != DEFAULT_EMBEDDING_DIMENSIONS:
        raise ValueError(
            "query_embedding must have "
            f"{DEFAULT_EMBEDDING_DIMENSIONS} dimensions"
        )


def _validated_embedding(values: Sequence[float]) -> tuple[float, ...]:
    try:
        vector = tuple(float(value) for value in values)
    except (TypeError, ValueError) as error:
        raise ValueError("policy embedding must contain numbers") from error
    if len(vector) != DEFAULT_EMBEDDING_DIMENSIONS:
        raise ValueError(
            "policy embedding must have "
            f"{DEFAULT_EMBEDDING_DIMENSIONS} dimensions"
        )
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("policy embedding must contain only finite values")
    return vector


__all__ = [
    "Base",
    "PgVectorPolicyRetriever",
    "ManagedPolicyIndexUpdater",
    "PolicyEmbeddingRow",
    "build_pgvector_policy_query",
    "create_pgvector_schema",
    "policy_evidence_from_row",
    "seed_policy_embeddings",
]
