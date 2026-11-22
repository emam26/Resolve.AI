"""Offline labeled evaluation for the deterministic policy retriever."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from pydantic import BaseModel, ConfigDict

from .corpus import POLICY_CORPUS
from .models import PolicyAudience, PolicyEvidence, PolicyRecord
from .retrieval import retrieve_published_policy

if TYPE_CHECKING:
    from backend.app.ai.answer import PolicyRetriever


@dataclass(frozen=True)
class EvaluationCase:
    """Predeclared label; labels must not be inferred from retrieval output."""

    label: str
    query: str
    audience: PolicyAudience
    expected_document_id: str | None
    expected_version: str | None
    expected_section: str | None
    expect_supported_answer: bool
    forbidden_document_id: str | None = None
    forbidden_version: str | None = None


DEFAULT_EVALUATION_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        label="published_public_delivery_v2",
        query="shipment delayed updated estimate",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Delayed shipments",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="older_delivery_version_filtered",
        query="shipment delayed contact support",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Delayed shipments",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="internal_policy_hidden_from_customer",
        query="refund review approver authorization",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
        forbidden_document_id="refund-review-policy",
    ),
    EvaluationCase(
        label="published_internal_policy_for_staff",
        query="refund review approver authorization",
        audience="support_agent",
        expected_document_id="refund-review-policy",
        expected_version="v1",
        expected_section="Refund review",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="unknown_answer",
        query="can you explain moon cheese logistics",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
)


class EvaluationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    retrieved: list[PolicyEvidence]
    expected_hit_found: bool
    wrong_version_exposed: bool
    citation_visibility_valid: bool
    unsupported_answer_behavior_valid: bool


class RetrievalEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_count: int
    recall_at_3: float
    wrong_version_exposure: float
    citation_visibility_accuracy: float
    unsupported_answer_behavior: float
    cases: list[EvaluationCaseResult]

    def as_dict(self) -> dict[str, object]:
        """Expose a human-readable metric label alongside Python attributes."""

        return {
            "query_count": self.query_count,
            "Recall@3": self.recall_at_3,
            "wrong_version_exposure": self.wrong_version_exposure,
            "citation_visibility_accuracy": self.citation_visibility_accuracy,
            "unsupported_answer_behavior": self.unsupported_answer_behavior,
            "cases": [case.model_dump(mode="json") for case in self.cases],
        }


class _SnapshotPolicyRetriever:
    """Replay one retrieval result through the answer-layer safety checks."""

    def __init__(self, evidence: Sequence[PolicyEvidence]) -> None:
        self._evidence = tuple(evidence)

    def retrieve_published_policy(
        self,
        query: str,
        audience: PolicyAudience = "customer",
        top_k: int = 3,
    ) -> Sequence[PolicyEvidence]:
        del query, audience, top_k
        return self._evidence


def _visibility_valid(evidence: PolicyEvidence, audience: PolicyAudience) -> bool:
    if audience == "customer":
        return evidence.visibility == "public"
    return evidence.visibility in {"public", "internal"}


def _matches_expected(evidence: PolicyEvidence, case: EvaluationCase) -> bool:
    return (
        case.expected_document_id is not None
        and evidence.document_id == case.expected_document_id
        and evidence.document_version == case.expected_version
        and evidence.section == case.expected_section
        and evidence.status == "published"
    )


def evaluate_policy_retrieval(
    cases: Sequence[EvaluationCase] = DEFAULT_EVALUATION_CASES,
    *,
    corpus: Sequence[PolicyRecord] = POLICY_CORPUS,
    policy_retriever: PolicyRetriever | None = None,
) -> RetrievalEvaluationReport:
    """Evaluate retrieval and grounding with lexical or injected retrieval.

    The default remains the deterministic lexical baseline. Supplying the
    application retrieval boundary lets the same frozen labels evaluate a
    semantic/pgvector backend without duplicating policy-access assertions.
    """

    if not cases:
        raise ValueError("at least one evaluation case is required")

    results: list[EvaluationCaseResult] = []
    recall_hits = 0
    recall_total = 0
    wrong_version_count = 0
    version_sensitive_count = 0
    visibility_valid_count = 0
    unsupported_total = 0
    unsupported_valid_count = 0

    # Import lazily to keep retrieval usable without importing the answer layer.
    from backend.app.ai.answer import answer_from_published_policy

    for case in cases:
        if policy_retriever is None:
            retrieved = retrieve_published_policy(
                case.query, case.audience, top_k=3, corpus=corpus
            )
        else:
            retrieved = list(
                policy_retriever.retrieve_published_policy(
                    case.query, audience=case.audience, top_k=3
                )
            )
        expected_hit = any(
            _matches_expected(evidence, case)
            and _visibility_valid(evidence, case.audience)
            for evidence in retrieved
        )
        if case.expected_document_id is not None:
            recall_total += 1
            recall_hits += int(expected_hit)

        wrong_version = any(
            (
                case.forbidden_document_id is not None
                and evidence.document_id == case.forbidden_document_id
            )
            or (
                case.expected_document_id is not None
                and case.forbidden_version is not None
                and evidence.document_id == case.expected_document_id
                and evidence.document_version == case.forbidden_version
            )
            for evidence in retrieved
        )
        if case.forbidden_version is not None or case.forbidden_document_id is not None:
            version_sensitive_count += 1
            wrong_version_count += int(wrong_version)

        citation_valid = all(
            evidence.status == "published"
            and
            evidence.release_id
            and evidence.document_version
            and evidence.section
            and _visibility_valid(evidence, case.audience)
            for evidence in retrieved
        )
        if case.expected_document_id is None:
            citation_valid = citation_valid and not retrieved
        else:
            citation_valid = citation_valid and expected_hit
        answer = answer_from_published_policy(
            case.query,
            audience=case.audience,
            corpus=corpus,
            policy_retriever=(
                _SnapshotPolicyRetriever(retrieved)
                if policy_retriever is not None
                else None
            ),
        )
        grounded_answer_valid = (
            answer.answer is not None
            and answer.evidence != []
            and answer.grounded is True
            and answer.needs_handoff is False
        )
        selected_expected = bool(answer.evidence) and _matches_expected(
            answer.evidence[0], case
        )
        unsupported_valid = (
            grounded_answer_valid and selected_expected
            if case.expect_supported_answer
            else (
                answer.answer is None
                and answer.evidence == []
                and answer.grounded is False
                and answer.needs_handoff is True
            )
        )
        if case.expect_supported_answer:
            citation_valid = citation_valid and unsupported_valid
        visibility_valid_count += int(citation_valid)
        if not case.expect_supported_answer:
            unsupported_total += 1
            unsupported_valid_count += int(unsupported_valid)

        results.append(
            EvaluationCaseResult(
                label=case.label,
                retrieved=retrieved,
                expected_hit_found=expected_hit,
                wrong_version_exposed=wrong_version,
                citation_visibility_valid=citation_valid,
                unsupported_answer_behavior_valid=unsupported_valid,
            )
        )

    return RetrievalEvaluationReport(
        query_count=len(cases),
        recall_at_3=recall_hits / recall_total if recall_total else 0.0,
        wrong_version_exposure=(
            wrong_version_count / version_sensitive_count
            if version_sensitive_count
            else 0.0
        ),
        citation_visibility_accuracy=visibility_valid_count / len(cases),
        unsupported_answer_behavior=(
            unsupported_valid_count / unsupported_total if unsupported_total else 0.0
        ),
        cases=results,
    )


__all__ = [
    "DEFAULT_EVALUATION_CASES",
    "EvaluationCase",
    "RetrievalEvaluationReport",
    "evaluate_policy_retrieval",
]
