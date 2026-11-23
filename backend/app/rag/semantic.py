"""Offline semantic policy retrieval primitives.

The lexical retriever remains the deterministic M2 baseline.  This module
provides a separate embedding boundary so semantic retrieval can be evaluated
with injected vectors without requiring a model download or a live service.
"""

from __future__ import annotations

import math
from typing import Any, Protocol, Sequence

from .models import PolicyAudience, PolicyEvidence, PolicyRecord


DEFAULT_SENTENCE_TRANSFORMER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIMENSIONS = 384
# This gate is calibrated against the frozen synthetic evaluation set and a
# natural-language shipment-delay smoke query for the local MiniLM baseline.
DEFAULT_SEMANTIC_MINIMUM_SCORE = 0.60
SUPPORTED_AUDIENCES = frozenset(
    {"customer", "support_agent", "refund_approver", "merchant_admin"}
)
_STAFF_AUDIENCES = frozenset(
    {"support_agent", "refund_approver", "merchant_admin"}
)
_APPLICABILITY_STOPWORDS = frozenset(
    {
        "a",
        "after",
        "an",
        "and",
        "are",
        "can",
        "do",
        "for",
        "how",
        "i",
        "is",
        "me",
        "my",
        "of",
        "on",
        "the",
        "this",
        "to",
        "what",
        "when",
        "with",
        "you",
    }
)
_APPLICABILITY_GENERIC_TERMS = frozenset(
    {
        "action",
        "contact",
        "customer",
        "help",
        "item",
        "order",
        "payment",
        "policy",
        "request",
        "support",
    }
)
_APPLICABILITY_TERM_ALIASES = {
    "considered": "consider",
    "considering": "consider",
    "need": "require",
    "needs": "require",
    "qualified": "eligible",
    "qualifies": "eligible",
    "qualify": "eligible",
    "required": "require",
    "requires": "require",
    "requests": "request",
    "returns": "return",
}


class EmbeddingProvider(Protocol):
    """Small boundary shared by real and deterministic test embedders."""

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Return one finite numeric vector for each input text."""


class SentenceTransformerEmbeddingProvider:
    """Lazy local sentence-transformers adapter.

    The model is imported and constructed only on the first embedding call.
    ``local_files_only`` defaults to true so a normal local run cannot trigger
    a model download.  Tests can inject a small fake model through ``model``.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_SENTENCE_TRANSFORMER_MODEL,
        *,
        model: Any | None = None,
        local_files_only: bool = True,
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name is required")
        self.model_name = model_name
        self.local_files_only = local_files_only
        self._model = model

    def _get_model(self) -> Any:
        if self._model is None:
            # Keep this import lazy: importing the RAG package must not import
            # torch or attempt to resolve a model from an external registry.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_name,
                local_files_only=self.local_files_only,
            )
        return self._model

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        encoded = self._get_model().encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=False,
            show_progress_bar=False,
        )
        return _coerce_vectors(
            encoded,
            expected_count=len(texts),
            expected_dimensions=DEFAULT_EMBEDDING_DIMENSIONS,
        )


def cosine_similarity(
    left: Sequence[float], right: Sequence[float]
) -> float:
    """Return cosine similarity, treating a zero vector as no match."""

    left_vector = _coerce_vector(left)
    right_vector = _coerce_vector(right)
    if len(left_vector) != len(right_vector):
        raise ValueError("embedding dimensions must match")
    if not left_vector:
        raise ValueError("embedding vectors must not be empty")

    dot_product = sum(left_value * right_value for left_value, right_value in zip(left_vector, right_vector))
    left_norm = math.sqrt(sum(value * value for value in left_vector))
    right_norm = math.sqrt(sum(value * value for value in right_vector))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot_product / (left_norm * right_norm)


class InMemorySemanticRetriever:
    """Deterministic cosine retriever over injected policy embeddings."""

    def __init__(
        self,
        records: Sequence[PolicyRecord],
        embedding_provider: EmbeddingProvider,
        *,
        minimum_score: float = DEFAULT_SEMANTIC_MINIMUM_SCORE,
    ) -> None:
        if not math.isfinite(minimum_score):
            raise ValueError("minimum_score must be finite")
        self._records = tuple(records)
        self._embedding_provider = embedding_provider
        self._minimum_score = minimum_score
        corpus_vectors = embedding_provider.embed(
            [_record_text(record) for record in self._records]
        )
        self._vectors = _coerce_vectors(
            corpus_vectors,
            expected_count=len(self._records),
            expected_dimensions=DEFAULT_EMBEDDING_DIMENSIONS,
        )

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
        """Return access-filtered candidates before the normal score gate."""

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
        _validate_retrieval_inputs(audience, top_k)
        if not query.strip():
            return []

        query_vectors = _coerce_vectors(
            self._embedding_provider.embed([query]),
            expected_count=1,
            expected_dimensions=DEFAULT_EMBEDDING_DIMENSIONS,
        )
        query_vector = query_vectors[0]
        ranked: list[tuple[float, PolicyRecord]] = []
        for record, record_vector in zip(self._records, self._vectors):
            if not _audience_allows(record, audience):
                continue
            score = cosine_similarity(query_vector, record_vector)
            if score >= minimum_score:
                ranked.append((score, record))

        ranked.sort(key=lambda item: (-item[0], *_record_sort_key(item[1])))
        return [_to_evidence(record, score) for score, record in ranked[:top_k]]


def _record_text(record: PolicyRecord) -> str:
    return f"{record.section}\n{record.text}"


def _record_sort_key(record: PolicyRecord) -> tuple[str, str, str, str]:
    return (
        record.document_id,
        record.document_version,
        record.section,
        record.release_id,
    )


def _audience_allows(record: PolicyRecord, audience: PolicyAudience) -> bool:
    if record.status != "published":
        return False
    if audience == "customer":
        return record.visibility == "public"
    return record.visibility in {"public", "internal"}


def _to_evidence(record: PolicyRecord, score: float) -> PolicyEvidence:
    return PolicyEvidence(
        document_id=record.document_id,
        document_version=record.document_version,
        section=record.section,
        release_id=record.release_id,
        visibility=record.visibility,
        score=float(score),
        text=record.text,
        status=record.status,
        is_active=record.status == "published" and record.is_active,
    )


def _validate_retrieval_inputs(audience: PolicyAudience, top_k: int) -> None:
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise ValueError("top_k must be positive")
    if audience not in SUPPORTED_AUDIENCES:
        raise ValueError(f"unsupported audience: {audience}")


def is_sufficient_semantic_match(
    evidence: Sequence[PolicyEvidence],
    *,
    minimum_score: float = DEFAULT_SEMANTIC_MINIMUM_SCORE,
) -> bool:
    """Guard future grounded answers against weak semantic overlap.

    Retrieval results are candidates, not permission to answer. Callers that
    turn semantic evidence into an answer must apply this guard and hand off
    when the top result does not clear the conservative threshold.
    """

    if not math.isfinite(minimum_score):
        raise ValueError("minimum_score must be finite")
    return bool(evidence) and evidence[0].score >= minimum_score


def is_applicable_policy_evidence(
    query: str,
    evidence: Sequence[PolicyEvidence],
    *,
    minimum_anchor_terms: int = 3,
) -> bool:
    """Accept a weak semantic candidate only with explicit text support.

    This is a narrow evidence-completeness check, not a replacement for the
    semantic threshold. It considers only the rank-one candidate, requires
    every numeric query constraint in its text, and requires at least three
    content-bearing query terms to all appear in the evidence text. Publication
    and audience filtering remain the retriever's responsibility and are
    rechecked by the answer layer.
    """

    if not query.strip() or not evidence or minimum_anchor_terms < 1:
        return False
    first = evidence[0]
    query_terms = _applicability_terms(query)
    text_terms = set(_applicability_terms(first.text))
    numeric_terms = {term for term in query_terms if term.isdigit()}
    if not numeric_terms.issubset(text_terms):
        return False
    anchor_terms = {
        term
        for term in query_terms
        if term not in _APPLICABILITY_GENERIC_TERMS
    }
    if len(anchor_terms) < minimum_anchor_terms:
        return False
    return anchor_terms.issubset(text_terms)


def _applicability_terms(value: str) -> tuple[str, ...]:
    return tuple(
        _APPLICABILITY_TERM_ALIASES.get(term, term)
        for term in (
            "".join(character for character in raw.casefold() if character.isalnum())
            for raw in value.split()
        )
        if term and term not in _APPLICABILITY_STOPWORDS
    )


def _coerce_vector(values: Sequence[float]) -> tuple[float, ...]:
    try:
        vector = tuple(float(value) for value in values)
    except (TypeError, ValueError) as error:
        raise ValueError("embedding vectors must contain numbers") from error
    if not vector or not all(math.isfinite(value) for value in vector):
        raise ValueError("embedding vectors must be non-empty and finite")
    return vector


def _coerce_vectors(
    values: Sequence[Sequence[float]],
    *,
    expected_count: int,
    expected_dimensions: int | None = None,
) -> list[tuple[float, ...]]:
    try:
        vectors = [_coerce_vector(vector) for vector in values]
    except TypeError as error:
        raise ValueError("embedding provider must return a sequence of vectors") from error
    if len(vectors) != expected_count:
        raise ValueError(
            "embedding provider returned an unexpected number of vectors"
        )
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) > 1:
        raise ValueError("embedding vectors must have consistent dimensions")
    if expected_dimensions is not None and dimensions != {expected_dimensions}:
        raise ValueError(
            "embedding vectors must have "
            f"{expected_dimensions} dimensions"
        )
    return vectors


__all__ = [
    "DEFAULT_EMBEDDING_DIMENSIONS",
    "DEFAULT_SEMANTIC_MINIMUM_SCORE",
    "DEFAULT_SENTENCE_TRANSFORMER_MODEL",
    "EmbeddingProvider",
    "InMemorySemanticRetriever",
    "SUPPORTED_AUDIENCES",
    "SentenceTransformerEmbeddingProvider",
    "cosine_similarity",
    "is_applicable_policy_evidence",
    "is_sufficient_semantic_match",
]
