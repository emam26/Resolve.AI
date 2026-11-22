from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine

from backend.app.rag.corpus import POLICY_CORPUS
from backend.app.rag.fulltext import PostgresFullTextPolicyRetriever
from backend.app.rag.pgvector_store import create_pgvector_schema, seed_policy_embeddings


class DeterministicEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * 384
            lowered = text.casefold()
            for axis, token in enumerate(("shipment", "delayed", "refund", "review", "return", "unused")):
                if token in lowered:
                    vector[axis] = 1.0
            vectors.append(vector)
        return vectors


@pytest.fixture()
def full_text_retriever() -> PostgresFullTextPolicyRetriever:
    database_url = os.getenv("RESOLVEAI_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("set RESOLVEAI_TEST_POSTGRES_URL to an actual PostgreSQL database")
    engine = create_engine(database_url, future=True)
    create_pgvector_schema(engine)
    seed_policy_embeddings(engine, POLICY_CORPUS, DeterministicEmbeddingProvider())
    retriever = PostgresFullTextPolicyRetriever(database_url)
    try:
        yield retriever
    finally:
        retriever.close()
        engine.dispose()


def test_full_text_customer_filters_publication_and_internal_policy(full_text_retriever) -> None:
    delivery = full_text_retriever.retrieve_published_policy("shipment delayed")
    internal = full_text_retriever.retrieve_published_policy("refund review")

    assert delivery
    assert delivery[0].document_id == "delivery-policy"
    assert delivery[0].document_version == "v2"
    assert all(item.visibility == "public" for item in delivery)
    assert internal == []


def test_full_text_staff_can_retrieve_published_internal_policy(full_text_retriever) -> None:
    results = full_text_retriever.retrieve_published_policy(
        "refund review approver authorization", audience="support_agent"
    )

    assert results
    assert results[0].document_id == "refund-review-policy"
    assert results[0].visibility == "internal"


def test_full_text_irrelevant_and_repeatable_results(full_text_retriever) -> None:
    assert full_text_retriever.retrieve_published_policy("moon cheese logistics") == []
    first = full_text_retriever.retrieve_published_policy("shipment delayed")
    second = full_text_retriever.retrieve_published_policy("shipment delayed")
    assert first == second
