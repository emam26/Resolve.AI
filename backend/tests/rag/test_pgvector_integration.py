"""Opt-in PostgreSQL/pgvector checks using deterministic local embeddings."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine

from backend.app.rag.corpus import POLICY_CORPUS
from backend.app.rag.pgvector_store import (
    PgVectorPolicyRetriever,
    create_pgvector_schema,
    seed_policy_embeddings,
)


class DeterministicEmbeddingProvider:
    """Small fixed embedding used only for repeatable database integration tests."""

    _AXES = {
        "shipment": 0,
        "delayed": 1,
        "refund": 2,
        "review": 3,
        "return": 4,
        "unused": 5,
        "moon": 6,
    }

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.casefold()
            vector = [0.0] * 384
            for token, axis in self._AXES.items():
                if token in lowered:
                    vector[axis] = 1.0
            vectors.append(vector)
        return vectors


@pytest.fixture()
def pg_retriever() -> PgVectorPolicyRetriever:
    database_url = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip(
            "set RESOLVEAI_TEST_POSTGRES_URL to an actual PostgreSQL+pgvector database"
        )
    engine = create_engine(database_url, future=True)
    provider = DeterministicEmbeddingProvider()
    create_pgvector_schema(engine)
    seed_policy_embeddings(engine, POLICY_CORPUS, provider)
    retriever = PgVectorPolicyRetriever(database_url, provider)
    try:
        yield retriever
    finally:
        engine.dispose()


def test_postgres_customer_match_excludes_unpublished_revision(pg_retriever) -> None:
    results = pg_retriever.retrieve_published_policy("shipment delayed")

    assert results
    assert results[0].document_id == "delivery-policy"
    assert results[0].document_version == "v2"
    assert all(result.visibility == "public" for result in results)


def test_postgres_irrelevant_query_returns_no_evidence(pg_retriever) -> None:
    assert pg_retriever.retrieve_published_policy("moon cheese logistics") == []


def test_postgres_customer_cannot_retrieve_internal_policy(pg_retriever) -> None:
    assert pg_retriever.retrieve_published_policy("refund review") == []


def test_postgres_staff_can_retrieve_published_internal_policy(pg_retriever) -> None:
    results = pg_retriever.retrieve_published_policy(
        "refund review", audience="support_agent"
    )

    assert results
    assert results[0].document_id == "refund-review-policy"
    assert results[0].visibility == "internal"


def test_postgres_results_are_repeatable(pg_retriever) -> None:
    first = pg_retriever.retrieve_published_policy("shipment delayed")
    second = pg_retriever.retrieve_published_policy("shipment delayed")

    assert first == second
