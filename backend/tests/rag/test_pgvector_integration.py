"""Opt-in PostgreSQL/pgvector checks using deterministic local embeddings."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend.app.api import create_app
from backend.app.rag.corpus import POLICY_CORPUS
from backend.app.rag.pgvector_store import (
    PolicyEmbeddingRow,
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
        "warranty": 7,
        "accidental": 8,
        "damage": 9,
        "credit": 10,
        "fulfillment": 11,
        "error": 12,
        "packaging": 13,
        "received": 14,
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
        retriever.close()
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
    results = pg_retriever.retrieve_published_policy("refund review")

    # The expanded operational corpus includes public refund-processing
    # evidence.  It may match the query, but the staff-only review procedure
    # must remain inaccessible to a customer.
    assert all(result.document_id != "refund-review-policy" for result in results)
    assert all(result.visibility == "public" for result in results)


def test_postgres_customer_gets_public_warranty_not_internal_exception_matrix(
    pg_retriever,
) -> None:
    results = pg_retriever.retrieve_published_policy(
        "warranty accidental damage", audience="customer", top_k=3
    )

    assert results
    assert results[0].document_id == "warranty-policy"
    assert results[0].section == "Product warranty coverage"
    assert all(result.visibility == "public" for result in results)


def test_postgres_staff_can_retrieve_internal_warranty_policy(pg_retriever) -> None:
    results = pg_retriever.retrieve_published_policy(
        "warranty exclusion matrix", audience="support_agent", top_k=3
    )

    assert any(
        result.document_id == "warranty-policy"
        and result.section == "Warranty exception matrix"
        and result.visibility == "internal"
        for result in results
    )


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


def test_seed_refreshes_existing_policy_embeddings(pg_retriever) -> None:
    database_url = os.environ["RESOLVEAI_TEST_POSTGRES_URL"]
    engine = create_engine(database_url, future=True)
    record = next(
        item
        for item in POLICY_CORPUS
        if item.document_id == "delivery-policy"
        and item.document_version == "v2"
        and item.section == "Delayed shipments"
    )

    class AlternateEmbeddingProvider:
        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * 20 + [1.0] + [0.0] * 363 for _ in texts]

    class RestoredEmbeddingProvider:
        def embed(self, texts: list[str]) -> list[list[float]]:
            return [
                [
                    1.0 if token in text.casefold() else 0.0
                    for token in ("shipment", "delayed")
                ]
                + [0.0] * 382
                for text in texts
            ]

    try:
        seed_policy_embeddings(engine, (record,), AlternateEmbeddingProvider())
        with engine.connect() as connection:
            row = connection.execute(
                PolicyEmbeddingRow.__table__.select().where(
                    PolicyEmbeddingRow.document_id == record.document_id,
                    PolicyEmbeddingRow.document_version == record.document_version,
                    PolicyEmbeddingRow.section == record.section,
                )
            ).first()
        assert row is not None
        assert row.embedding[20] == 1.0
        assert sum(row.embedding[:20]) == 0.0
    finally:
        seed_policy_embeddings(engine, (record,), RestoredEmbeddingProvider())
        engine.dispose()


def test_customer_api_uses_real_postgres_retriever(pg_retriever) -> None:
    database_url = os.environ["RESOLVEAI_TEST_POSTGRES_URL"]
    client = TestClient(
        create_app(database_url=database_url, policy_retriever=pg_retriever)
    )
    login = client.post(
        "/api/v1/auth/demo-login", json={"demo_actor_id": "customer_001"}
    )
    headers = {"Authorization": f"Bearer {login.json()['session_id']}"}
    conversation = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"channel": "widget", "order_id": None},
    )

    response = client.post(
        f"/api/v1/conversations/{conversation.json()['conversation_id']}/messages",
        headers=headers,
        json={"content": "What should I do about a shipment delay?"},
    )

    assert login.status_code == 200
    assert conversation.status_code == 201
    assert response.status_code == 201
    body = response.json()
    assert body["retrieval_mode"] == "semantic"
    assert body["assistant_reply"]["content"] == (
        "If a shipment is delayed, contact support for an updated estimate."
    )
    assert body["evidence"][0]["document_version"] == "v2"


def test_postgres_threshold_excludes_below_minimum_score(pg_retriever) -> None:
    retriever = PgVectorPolicyRetriever(
        os.environ["RESOLVEAI_TEST_POSTGRES_URL"],
        DeterministicEmbeddingProvider(),
        minimum_score=0.9,
    )
    try:
        assert retriever.retrieve_published_policy("shipment") == []
    finally:
        retriever.close()


def test_postgres_equal_scores_use_stable_metadata_order(pg_retriever) -> None:
    database_url = os.environ["RESOLVEAI_TEST_POSTGRES_URL"]
    engine = create_engine(database_url, future=True)
    test_document_ids = ("aaa-policy", "zzz-policy")
    try:
        with engine.begin() as connection:
            connection.execute(
                PolicyEmbeddingRow.__table__.insert(),
                [
                    {
                        "document_id": "zzz-policy",
                        "document_version": "v1",
                        "section": "Shipment guidance",
                        "release_id": "release_test",
                        "status": "published",
                        "visibility": "public",
                        "text": "Shipment guidance for another test policy.",
                        "embedding": [1.0] + [0.0] * 383,
                    },
                    {
                        "document_id": "aaa-policy",
                        "document_version": "v1",
                        "section": "Shipment guidance",
                        "release_id": "release_test",
                        "status": "published",
                        "visibility": "public",
                        "text": "Shipment guidance for a test policy.",
                        "embedding": [1.0] + [0.0] * 383,
                    },
                ],
            )
        retriever = PgVectorPolicyRetriever(
            database_url,
            DeterministicEmbeddingProvider(),
            minimum_score=0.0,
        )
        results = retriever.retrieve_published_policy("shipment", top_k=2)

        assert [result.document_id for result in results] == list(test_document_ids)
    finally:
        if "retriever" in locals():
            retriever.close()
        with engine.begin() as connection:
            connection.execute(
                PolicyEmbeddingRow.__table__.delete().where(
                    PolicyEmbeddingRow.document_id.in_(test_document_ids)
                )
            )
        engine.dispose()
