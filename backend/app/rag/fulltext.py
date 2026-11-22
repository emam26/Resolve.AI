"""PostgreSQL full-text retrieval for the offline comparison benchmark.

This retriever is deliberately benchmark-only. The customer investigation
workflow continues to use the lexical baseline or configured semantic path;
this module measures PostgreSQL's native English text search against the same
published policy rows without adding a third production route.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import String, create_engine, func, literal_column, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .models import PolicyAudience, PolicyEvidence
from .pgvector_store import PolicyEmbeddingRow
from .semantic import SUPPORTED_AUDIENCES


FULL_TEXT_INDEX_NAME = "ix_policy_embeddings_policy_text_fts"


def ensure_full_text_index(engine: Engine) -> None:
    """Create the native GIN expression index used by the benchmark."""

    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {FULL_TEXT_INDEX_NAME} "
                "ON policy_embeddings USING gin "
                "(to_tsvector('english', section || ' ' || text))"
            )
        )


def build_full_text_policy_query(
    query: str,
    audience: PolicyAudience = "customer",
    top_k: int = 3,
):
    """Build a parameterized PostgreSQL English full-text query."""

    _validate_inputs(query, audience, top_k)
    document = func.to_tsvector(
        "english",
        PolicyEmbeddingRow.section
        + literal_column("' '", type_=String())
        + PolicyEmbeddingRow.text,
    )
    query_vector = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank_cd(document, query_vector).label("text_rank")
    visibility_filter = (
        PolicyEmbeddingRow.visibility == "public"
        if audience == "customer"
        else PolicyEmbeddingRow.visibility.in_(("public", "internal"))
    )
    return (
        select(PolicyEmbeddingRow, rank)
        .where(
            PolicyEmbeddingRow.status == "published",
            visibility_filter,
            document.op("@@")(query_vector),
        )
        .order_by(
            rank.desc(),
            PolicyEmbeddingRow.document_id.asc(),
            PolicyEmbeddingRow.document_version.asc(),
            PolicyEmbeddingRow.section.asc(),
            PolicyEmbeddingRow.release_id.asc(),
        )
        .limit(top_k)
    )


class PostgresFullTextPolicyRetriever:
    """Query published policy text with PostgreSQL's native FTS features."""

    retrieval_mode = "full_text"

    def __init__(self, database_url: str, *, ensure_index: bool = True) -> None:
        if not database_url.startswith(("postgresql", "postgres")):
            raise ValueError("PostgresFullTextPolicyRetriever requires a PostgreSQL URL")
        self._engine = create_engine(database_url, future=True)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        if ensure_index:
            ensure_full_text_index(self._engine)

    def retrieve_published_policy(
        self,
        query: str,
        audience: PolicyAudience = "customer",
        top_k: int = 3,
    ) -> list[PolicyEvidence]:
        if not query.strip():
            return []
        statement = build_full_text_policy_query(query, audience, top_k)
        with self._session_factory() as session:
            rows = session.execute(statement).all()
        return [
            _policy_evidence_from_row(row, rank=float(text_rank))
            for row, text_rank in rows
        ]

    def close(self) -> None:
        """Release the SQLAlchemy engine owned by this retriever."""

        self._engine.dispose()


def _policy_evidence_from_row(
    row: PolicyEmbeddingRow,
    *,
    rank: float,
) -> PolicyEvidence:
    return PolicyEvidence(
        document_id=row.document_id,
        document_version=row.document_version,
        section=row.section,
        release_id=row.release_id,
        visibility=row.visibility,  # type: ignore[arg-type]
        score=rank,
        text=row.text,
        status=row.status,  # type: ignore[arg-type]
    )


def _validate_inputs(query: str, audience: PolicyAudience, top_k: int) -> None:
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise ValueError("top_k must be positive")
    if audience not in SUPPORTED_AUDIENCES:
        raise ValueError(f"unsupported audience: {audience}")
    if not isinstance(query, str):
        raise ValueError("query must be text")


__all__ = [
    "FULL_TEXT_INDEX_NAME",
    "PostgresFullTextPolicyRetriever",
    "build_full_text_policy_query",
    "ensure_full_text_index",
]
