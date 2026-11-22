"""Offline policy retrieval primitives for the M2 slice."""

from .corpus import POLICY_CORPUS, get_policy_corpus
from .evaluation import (
    DEFAULT_EVALUATION_CASES,
    EvaluationCase,
    RetrievalEvaluationReport,
    evaluate_policy_retrieval,
)
from .models import (
    PolicyAudience,
    PolicyCitation,
    PolicyEvidence,
    PolicyRecord,
)
from .pgvector_store import (
    PgVectorPolicyRetriever,
    PolicyEmbeddingRow,
    create_pgvector_schema,
    seed_policy_embeddings,
)
from .retrieval import is_sufficient_policy_match, retrieve_published_policy

__all__ = [
    "DEFAULT_EVALUATION_CASES",
    "EvaluationCase",
    "POLICY_CORPUS",
    "PolicyAudience",
    "PolicyCitation",
    "PolicyEvidence",
    "PolicyRecord",
    "PolicyEmbeddingRow",
    "PgVectorPolicyRetriever",
    "RetrievalEvaluationReport",
    "evaluate_policy_retrieval",
    "get_policy_corpus",
    "is_sufficient_policy_match",
    "retrieve_published_policy",
    "create_pgvector_schema",
    "seed_policy_embeddings",
]
