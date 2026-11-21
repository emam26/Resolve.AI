"""PostgreSQL/pgvector policy embedding model and safe query builder."""

from __future__ import annotations

import math
from typing import Sequence

from pgvector.sqlalchemy import Vector
from sqlalchemy import Integer, String, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .models import PolicyAudience, PolicyEvidence
from .semantic import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_SEMANTIC_MINIMUM_SCORE,
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    return (
        select(PolicyEmbeddingRow, distance)
        .where(
            PolicyEmbeddingRow.status == "published",
            visibility_filter,
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


__all__ = [
    "Base",
    "PolicyEmbeddingRow",
    "build_pgvector_policy_query",
    "policy_evidence_from_row",
]
