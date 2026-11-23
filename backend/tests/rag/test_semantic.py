from __future__ import annotations

from typing import Sequence

import pytest
from sqlalchemy.dialects import postgresql

from backend.app.rag.models import PolicyEvidence, PolicyRecord
from backend.app.rag.pgvector_store import (
    PolicyEmbeddingRow,
    build_pgvector_policy_query,
    policy_evidence_from_row,
)
from backend.app.rag.semantic import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    InMemorySemanticRetriever,
    SentenceTransformerEmbeddingProvider,
    is_applicable_policy_evidence,
    is_sufficient_semantic_match,
)


class FakeEmbeddingProvider:
    def __init__(self, vectors: dict[str, Sequence[float]]) -> None:
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[Sequence[float]]:
        self.calls.append(list(texts))
        return [self.vectors[text] for text in texts]


class FakeSentenceTransformer:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str], **_: object) -> list[list[float]]:
        self.calls.append(texts)
        return [[1.0] + [0.0] * (DEFAULT_EMBEDDING_DIMENSIONS - 1) for _ in texts]


class WrongDimensionSentenceTransformer:
    def encode(self, texts: list[str], **_: object) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _record(
    document_id: str,
    *,
    version: str = "v1",
    status: str = "published",
    visibility: str = "public",
    section: str = "Policy section",
    text: str = "Policy text",
    is_active: bool = True,
) -> PolicyRecord:
    return PolicyRecord(
        document_id=document_id,
        document_version=version,
        section=section,
        release_id=f"release-{document_id}-{version}",
        status=status,  # type: ignore[arg-type]
        visibility=visibility,  # type: ignore[arg-type]
        text=text,
        is_active=is_active,
    )


def _vector(first: float, second: float = 0.0) -> tuple[float, ...]:
    return (first, second) + (0.0,) * (DEFAULT_EMBEDDING_DIMENSIONS - 2)


def test_sentence_transformer_adapter_is_lazy_and_supports_injected_model() -> None:
    model = FakeSentenceTransformer()
    provider = SentenceTransformerEmbeddingProvider(model=model)

    assert model.calls == []
    assert provider.embed(["delayed shipment"]) == [
        (1.0,) + (0.0,) * (DEFAULT_EMBEDDING_DIMENSIONS - 1)
    ]
    assert model.calls == [["delayed shipment"]]


def test_in_memory_semantic_retrieval_preserves_contract_and_filters_visibility() -> None:
    public = _record("delivery-policy", section="Delayed shipments", text="delay estimate")
    old = _record(
        "delivery-policy",
        version="v0",
        status="unpublished",
        section="Delayed shipments",
        text="old delay rule",
    )
    internal = _record(
        "refund-policy",
        visibility="internal",
        section="Refund review",
        text="approver authorization",
    )
    provider = FakeEmbeddingProvider(
        {
            "Delayed shipments\ndelay estimate": _vector(1.0, 0.0),
            "Delayed shipments\nold delay rule": _vector(0.9, 0.1),
            "Refund review\napprover authorization": _vector(0.0, 1.0),
            "shipment delay": _vector(1.0, 0.0),
            "refund review": _vector(0.0, 1.0),
        }
    )
    retriever = InMemorySemanticRetriever([public, old, internal], provider)

    customer_results = retriever.retrieve_published_policy("shipment delay")
    assert customer_results[0].model_dump(mode="json") == {
        "document_id": "delivery-policy",
        "document_version": "v1",
        "section": "Delayed shipments",
        "release_id": "release-delivery-policy-v1",
        "visibility": "public",
        "score": 1.0,
        "text": "delay estimate",
    }
    assert len(customer_results) == 1
    assert retriever.retrieve_published_policy("refund review") == []
    staff_results = retriever.retrieve_published_policy(
        "refund review", audience="support_agent"
    )
    assert staff_results[0].document_id == "refund-policy"
    assert staff_results[0].visibility == "internal"


def test_in_memory_semantic_retrieval_has_stable_ties_and_validates_inputs() -> None:
    first = _record("a-policy", text="first")
    second = _record("b-policy", text="second")
    provider = FakeEmbeddingProvider(
        {
            "Policy section\nfirst": _vector(1.0, 0.0),
            "Policy section\nsecond": _vector(1.0, 0.0),
            "same query": _vector(1.0, 0.0),
        }
    )
    retriever = InMemorySemanticRetriever([second, first], provider)

    results = retriever.retrieve_published_policy("same query", top_k=2)
    assert [result.document_id for result in results] == ["a-policy", "b-policy"]
    with pytest.raises(ValueError, match="top_k must be positive"):
        retriever.retrieve_published_policy("same query", top_k=0)
    with pytest.raises(ValueError, match="unsupported audience"):
        retriever.retrieve_published_policy("same query", audience="guest")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="384 dimensions"):
        SentenceTransformerEmbeddingProvider(
            model=WrongDimensionSentenceTransformer()
        ).embed(["wrong dimensions"])


def test_semantic_retrieval_and_grounding_guard_reject_weak_matches() -> None:
    record = _record("delivery-policy", text="shipment estimate")
    provider = FakeEmbeddingProvider(
        {
            "Policy section\nshipment estimate": _vector(1.0, 0.0),
            "unrelated query": _vector(0.59, 0.8074),
        }
    )
    retriever = InMemorySemanticRetriever([record], provider)

    evidence = retriever.retrieve_published_policy("unrelated query")
    assert evidence == []
    assert not is_sufficient_semantic_match(evidence)


def test_applicability_proof_requires_explicit_numeric_and_anchor_support() -> None:
    supported = _record(
        "returns-policy",
        section="Return window",
        text=(
            "Submit a return request within 30 calendar days. Items must be "
            "unused with original packaging."
        ),
    )
    evidence = [
        PolicyEvidence(
            document_id=supported.document_id,
            document_version=supported.document_version,
            section=supported.section,
            release_id=supported.release_id,
            visibility=supported.visibility,
            score=0.54,
            text=supported.text,
        )
    ]

    assert is_applicable_policy_evidence("return 30 days unused", evidence)
    assert not is_applicable_policy_evidence("return 14 days unused", evidence)
    assert not is_applicable_policy_evidence("I need money back", evidence)


def test_applicability_allows_explicit_safe_paraphrase_aliases() -> None:
    evidence = [
        PolicyEvidence(
            document_id="refund-eligibility-policy",
            document_version="v1",
            section="Refund eligibility",
            release_id="release_2026_11_01",
            visibility="public",
            score=0.54,
            text=(
                "A refund or credit request may be considered for an eligible "
                "return, a verified damaged item, or a confirmed fulfillment error."
            ),
        )
    ]

    assert is_applicable_policy_evidence(
        "verified damaged item qualify for credit", evidence
    )


def test_applicability_rejects_superficial_match_with_contradictory_condition() -> None:
    evidence = [
        PolicyEvidence(
            document_id="returns-policy",
            document_version="v1",
            section="Return window",
            release_id="release_2026_11_01",
            visibility="public",
            score=0.54,
            text=(
                "A return request must be submitted within 30 calendar days. "
                "Items must be unopened with original packaging."
            ),
        )
    ]

    assert not is_applicable_policy_evidence(
        "return 30 days opened", evidence
    )


def test_applicability_rejects_candidate_missing_requested_condition_or_fact() -> None:
    evidence = [
        PolicyEvidence(
            document_id="returns-policy",
            document_version="v1",
            section="Return window",
            release_id="release_2026_11_01",
            visibility="public",
            score=0.54,
            text=(
                "A return request must be submitted within 30 calendar days. "
                "Items must be unused."
            ),
        )
    ]

    assert not is_applicable_policy_evidence(
        "return 30 days unused original packaging", evidence
    )


def test_inmemory_published_stale_record_has_no_active_provenance() -> None:
    record = _record(
        "returns-policy",
        version="v0",
        text="return 30 days unused",
        is_active=False,
    )
    provider = FakeEmbeddingProvider(
        {
            "Policy section\nreturn 30 days unused": _vector(1.0, 0.0),
            "return 30 days unused": _vector(0.54, 0.841665),
        }
    )
    retriever = InMemorySemanticRetriever([record], provider)

    candidates = retriever.retrieve_published_policy_candidates(
        "return 30 days unused"
    )

    assert len(candidates) == 1
    assert candidates[0].is_active is False


def test_semantic_retrieval_accepts_the_sufficiency_threshold_boundary() -> None:
    record = _record("delivery-policy", text="shipment estimate")
    provider = FakeEmbeddingProvider(
        {
            "Policy section\nshipment estimate": _vector(0.6, 0.8),
            "threshold query": _vector(1.0, 0.0),
        }
    )
    retriever = InMemorySemanticRetriever(
        [record], provider, minimum_score=0.6
    )

    evidence = retriever.retrieve_published_policy("threshold query")

    assert len(evidence) == 1
    assert evidence[0].score == pytest.approx(0.6)
    assert is_sufficient_semantic_match(evidence, minimum_score=0.6)


def test_pgvector_query_compiles_with_published_audience_filters_and_tie_breaking() -> None:
    statement = build_pgvector_policy_query(
        [1.0] + [0.0] * (DEFAULT_EMBEDDING_DIMENSIONS - 1), top_k=3
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "policy_embeddings.status =" in sql
    assert "policy_embeddings.visibility =" in sql
    assert "policy_embeddings.embedding <=>" in sql
    assert "<=" in sql
    assert "ORDER BY" in sql
    assert "policy_embeddings.document_id ASC" in sql
    assert "LIMIT" in sql
    assert "published" in compiled.params.values()
    assert "public" in compiled.params.values()
    assert 1.0 - 0.60 in compiled.params.values()

    with pytest.raises(ValueError, match="384 dimensions"):
        build_pgvector_policy_query([1.0, 0.0], top_k=3)


def test_pgvector_staff_query_and_evidence_conversion_use_frozen_shape() -> None:
    statement = build_pgvector_policy_query(
        [0.0, 1.0] + [0.0] * (DEFAULT_EMBEDDING_DIMENSIONS - 2),
        audience="support_agent",
        top_k=1,
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "policy_embeddings.visibility IN" in str(compiled)
    scalar_params = {
        value
        for value in compiled.params.values()
        if isinstance(value, str)
    }
    sequence_params = {
        value
        for values in compiled.params.values()
        if isinstance(values, (list, tuple))
        for value in values
        if isinstance(value, str)
    }
    assert scalar_params | sequence_params >= {"published", "public", "internal"}

    row = PolicyEmbeddingRow(
        id=1,
        document_id="refund-policy",
        document_version="v1",
        section="Refund review",
        release_id="release-1",
        status="published",
        visibility="internal",
        text="Approver authorization is required.",
        embedding=[0.0, 1.0],
    )
    evidence = policy_evidence_from_row(row, cosine_distance=0.25)
    assert evidence.model_dump(mode="json") == {
        "document_id": "refund-policy",
        "document_version": "v1",
        "section": "Refund review",
        "release_id": "release-1",
        "visibility": "internal",
        "score": 0.75,
        "text": "Approver authorization is required.",
    }

    with pytest.raises(ValueError, match="below the semantic threshold"):
        policy_evidence_from_row(row, cosine_distance=0.5)
