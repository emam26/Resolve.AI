"""Frozen, deterministic comparison of policy retrieval implementations."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from statistics import mean, median
from typing import Callable, Sequence

from pydantic import BaseModel, ConfigDict

from .corpus import POLICY_CORPUS
from .evaluation import DEFAULT_EVALUATION_CASES, EvaluationCase
from .fulltext import PostgresFullTextPolicyRetriever
from .models import PolicyAudience, PolicyEvidence, PolicyRecord
from .pgvector_store import PgVectorPolicyRetriever
from .retrieval import retrieve_published_policy
from .semantic import SentenceTransformerEmbeddingProvider


# Labels are frozen before benchmark execution. Keep the corpus small and
# synthetic, but include queries that test paraphrase, vocabulary mismatch,
# ambiguity, stale policy language, access controls and unsupported requests.
CHALLENGING_BENCHMARK_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        label="paraphrase_late_parcel",
        query="My parcel has not arrived on time; where can I get a new delivery estimate?",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Delayed shipments",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="vocabulary_mismatch_delivery",
        query="The courier missed its promised arrival date.",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Delayed shipments",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="ambiguous_late_order",
        query="What happens when my order is late?",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Delayed shipments",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="outdated_wait_instruction",
        query="Do I need to wait three business days before contacting support about a delayed shipment?",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Delayed shipments",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="publication_restricted_delay_policy",
        query="Should I wait three business days before asking support about a late shipment?",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Delayed shipments",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="paraphrase_return_window",
        query="Can I send an unused item back?",
        audience="customer",
        expected_document_id="returns-policy",
        expected_version="v1",
        expected_section="Return window",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="vocabulary_mismatch_return_window",
        query="What is the time limit for sending an unused product back?",
        audience="customer",
        expected_document_id="returns-policy",
        expected_version="v1",
        expected_section="Return window",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="irrelevant_account_question",
        query="How do I change my account password?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
    EvaluationCase(
        label="internal_refund_question",
        query="Can I get my money back immediately?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
        forbidden_document_id="refund-review-policy",
    ),
    EvaluationCase(
        label="unsupported_tracking_question",
        query="Can you show me the courier tracking number?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
)

# Extend, rather than replace, the original five-case M2 evaluation set.
BENCHMARK_EVALUATION_CASES: tuple[EvaluationCase, ...] = (
    *DEFAULT_EVALUATION_CASES,
    *CHALLENGING_BENCHMARK_CASES,
)


class BenchmarkCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    rank: int | None
    reciprocal_rank: float
    answer_contract_valid: bool
    citation_access_control_valid: bool
    wrong_version_exposed: bool
    latency_ms: float


class RetrievalBenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: str
    query_count: int
    supported_query_count: int
    recall_at_3: float
    mrr: float
    answer_contract_accuracy: float
    unsupported_answer_behavior: float
    citation_access_control_accuracy: float
    wrong_version_exposure: float
    latency_ms_mean: float
    latency_ms_p50: float
    latency_ms_p95: float
    cases: list[BenchmarkCaseResult]

    def as_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class BenchmarkMethod:
    name: str
    retrieve: Callable[[str, PolicyAudience, int], Sequence[PolicyEvidence]]


def evaluate_benchmark_method(
    method: BenchmarkMethod,
    *,
    cases: Sequence[EvaluationCase] = BENCHMARK_EVALUATION_CASES,
    corpus: Sequence[PolicyRecord] = POLICY_CORPUS,
    latency_repeats: int = 3,
) -> RetrievalBenchmarkReport:
    """Evaluate one retriever without changing the customer answer path."""

    if not cases:
        raise ValueError("at least one benchmark case is required")
    if latency_repeats <= 0:
        raise ValueError("latency_repeats must be positive")

    supported_count = sum(case.expected_document_id is not None for case in cases)
    recall_hits = 0
    reciprocal_ranks: list[float] = []
    answer_valid_count = 0
    unsupported_count = 0
    unsupported_valid_count = 0
    citation_valid_count = 0
    wrong_version_count = 0
    version_sensitive_count = 0
    latencies: list[float] = []
    case_results: list[BenchmarkCaseResult] = []

    # Warm up model loading/connection setup before measuring steady-state
    # retrieval latency. The same first query is used for each method.
    method.retrieve(cases[0].query, cases[0].audience, 3)

    for case in cases:
        retrieved: Sequence[PolicyEvidence] = []
        case_latencies: list[float] = []
        for _ in range(latency_repeats):
            started = time.perf_counter()
            retrieved = list(method.retrieve(case.query, case.audience, 3))
            case_latencies.append((time.perf_counter() - started) * 1000)
        latency_ms = median(case_latencies)
        latencies.extend(case_latencies)

        rank = _expected_rank(retrieved, case)
        reciprocal_rank = 1.0 / rank if rank is not None else 0.0
        if case.expected_document_id is not None:
            recall_hits += int(rank is not None)
            reciprocal_ranks.append(reciprocal_rank)

        citation_valid = all(
            evidence.status == "published"
            and evidence.release_id
            and evidence.document_version
            and evidence.section
            and _audience_allows(evidence, case.audience)
            for evidence in retrieved
        )
        citation_valid_count += int(citation_valid)

        wrong_version = any(
            (
                case.forbidden_document_id is not None
                and evidence.document_id == case.forbidden_document_id
            )
            or (
                case.forbidden_version is not None
                and evidence.document_id == case.expected_document_id
                and evidence.document_version == case.forbidden_version
            )
            for evidence in retrieved
        )
        wrong_version_count += int(wrong_version)
        if case.forbidden_document_id is not None or case.forbidden_version is not None:
            version_sensitive_count += 1

        answer_contract_valid = _answer_contract_valid(
            case, retrieved, corpus=corpus
        )
        answer_valid_count += int(answer_contract_valid)
        if not case.expect_supported_answer:
            unsupported_count += 1
            unsupported_valid_count += int(answer_contract_valid)

        case_results.append(
            BenchmarkCaseResult(
                label=case.label,
                rank=rank,
                reciprocal_rank=reciprocal_rank,
                answer_contract_valid=answer_contract_valid,
                citation_access_control_valid=citation_valid,
                wrong_version_exposed=wrong_version,
                latency_ms=latency_ms,
            )
        )

    return RetrievalBenchmarkReport(
        method=method.name,
        query_count=len(cases),
        supported_query_count=supported_count,
        recall_at_3=recall_hits / supported_count if supported_count else 0.0,
        mrr=mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        answer_contract_accuracy=answer_valid_count / len(cases),
        unsupported_answer_behavior=(
            unsupported_valid_count / unsupported_count if unsupported_count else 0.0
        ),
        citation_access_control_accuracy=citation_valid_count / len(cases),
        wrong_version_exposure=(
            wrong_version_count / version_sensitive_count
            if version_sensitive_count
            else 0.0
        ),
        latency_ms_mean=mean(latencies),
        latency_ms_p50=_percentile(latencies, 50),
        latency_ms_p95=_percentile(latencies, 95),
        cases=case_results,
    )


def benchmark_from_environment() -> dict[str, object]:
    """Run lexical, PostgreSQL FTS and real local semantic retrieval together."""

    database_url = os.getenv("RESOLVEAI_DATABASE_URL")
    if not database_url or not database_url.startswith(("postgresql", "postgres")):
        raise RuntimeError("RESOLVEAI_DATABASE_URL must be a PostgreSQL URL")

    full_text = PostgresFullTextPolicyRetriever(database_url)
    semantic = PgVectorPolicyRetriever(
        database_url,
        SentenceTransformerEmbeddingProvider(
            model_name=os.getenv(
                "RESOLVEAI_SENTENCE_TRANSFORMER_MODEL",
                "sentence-transformers/all-MiniLM-L6-v2",
            ),
            local_files_only=True,
        ),
    )
    methods = (
        BenchmarkMethod(
            "lexical",
            lambda query, audience, top_k: retrieve_published_policy(
                query, audience=audience, top_k=top_k
            ),
        ),
        BenchmarkMethod(
            "postgres_full_text",
            full_text.retrieve_published_policy,
        ),
        BenchmarkMethod(
            "semantic_pgvector",
            semantic.retrieve_published_policy,
        ),
    )
    try:
        reports = [
            evaluate_benchmark_method(method) for method in methods
        ]
        return {
            "case_count": len(BENCHMARK_EVALUATION_CASES),
            "supported_case_count": sum(
                case.expected_document_id is not None
                for case in BENCHMARK_EVALUATION_CASES
            ),
            "latency_repeats": 3,
            "reports": [report.as_dict() for report in reports],
        }
    finally:
        full_text.close()
        semantic.close()


def _expected_rank(
    evidence: Sequence[PolicyEvidence], case: EvaluationCase
) -> int | None:
    if case.expected_document_id is None:
        return None
    for index, item in enumerate(evidence[:3], start=1):
        if (
            item.document_id == case.expected_document_id
            and item.document_version == case.expected_version
            and item.section == case.expected_section
            and item.status == "published"
            and _audience_allows(item, case.audience)
        ):
            return index
    return None


def _answer_contract_valid(
    case: EvaluationCase,
    evidence: Sequence[PolicyEvidence],
    *,
    corpus: Sequence[PolicyRecord],
) -> bool:
    """Validate the deterministic grounded-answer contract, not just a hit."""

    if not evidence:
        return not case.expect_supported_answer
    first = evidence[0]
    if (
        first.status != "published"
        or not _audience_allows(first, case.audience)
        or not _has_answer_template(first, corpus)
    ):
        return False
    if not case.expect_supported_answer:
        return False
    return _expected_rank((first,), case) == 1


def _has_answer_template(
    evidence: PolicyEvidence, corpus: Sequence[PolicyRecord]
) -> bool:
    return any(
        record.document_id == evidence.document_id
        and record.document_version == evidence.document_version
        and record.section == evidence.section
        and record.release_id == evidence.release_id
        and bool(record.answer_text or record.text)
        for record in corpus
    )


def _audience_allows(evidence: PolicyEvidence, audience: PolicyAudience) -> bool:
    return audience != "customer" or evidence.visibility == "public"


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


if __name__ == "__main__":
    print(json.dumps(benchmark_from_environment(), indent=2))


__all__ = [
    "BENCHMARK_EVALUATION_CASES",
    "CHALLENGING_BENCHMARK_CASES",
    "BenchmarkMethod",
    "RetrievalBenchmarkReport",
    "benchmark_from_environment",
    "evaluate_benchmark_method",
]
