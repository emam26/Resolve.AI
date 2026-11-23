"""Offline labeled evaluation for the deterministic policy retriever."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import TYPE_CHECKING, Protocol, Sequence

from pydantic import BaseModel, ConfigDict

from .corpus import POLICY_CORPUS
from .models import PolicyAudience, PolicyEvidence, PolicyRecord
from .retrieval import retrieve_published_policy
from .semantic import is_sufficient_semantic_match

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
        query="approver authorization external action",
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


# Frozen M11A additions for operational customer investigations.  The original
# five-case M2 tuple remains stable because it is reused by the M8 benchmark.
M11A_EVALUATION_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        label="published_public_shipping_estimate",
        query="shipping estimate carrier acceptance",
        audience="customer",
        expected_document_id="shipping-policy",
        expected_version="v1",
        expected_section="Shipping estimates",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_missing_package",
        query="tracking delivered missing package",
        audience="customer",
        expected_document_id="missing-package-policy",
        expected_version="v1",
        expected_section="Missing packages",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_damaged_item",
        query="damaged item packaging photos",
        audience="customer",
        expected_document_id="product-damage-policy",
        expected_version="v1",
        expected_section="Damaged items",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_wrong_item",
        query="received wrong item order",
        audience="customer",
        expected_document_id="fulfillment-policy",
        expected_version="v1",
        expected_section="Wrong items",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_partial_delivery",
        query="partial delivery expected item",
        audience="customer",
        expected_document_id="fulfillment-policy",
        expected_version="v1",
        expected_section="Partial order deliveries",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_cancellation",
        query="cancellation order fulfillment",
        audience="customer",
        expected_document_id="order-cancellation-policy",
        expected_version="v1",
        expected_section="Order cancellations",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_return_window",
        query="return 30 days unused",
        audience="customer",
        expected_document_id="returns-policy",
        expected_version="v1",
        expected_section="Return window",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_return_credit_processing",
        query="return credit processing status",
        audience="customer",
        expected_document_id="refund-processing-policy",
        expected_version="v1",
        expected_section="Return credit processing",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_human_escalation",
        query="human support insufficient evidence",
        audience="customer",
        expected_document_id="human-support-policy",
        expected_version="v1",
        expected_section="Human support escalation",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_delivered_not_received",
        query="tracking delivered package not received",
        audience="customer",
        expected_document_id="missing-package-policy",
        expected_version="v1",
        expected_section="Delivered but not received",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_late_delivery_followup",
        query="carrier movement estimated date passes delivery investigation",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Late delivery follow-up",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_return_exceptions",
        query="return unused packaging 30 days",
        audience="customer",
        expected_document_id="returns-policy",
        expected_version="v1",
        expected_section="Return window",
        expect_supported_answer=True,
        forbidden_version="v0",
    ),
    EvaluationCase(
        label="published_public_refund_eligibility",
        query="credit damaged fulfillment error",
        audience="customer",
        expected_document_id="refund-eligibility-policy",
        expected_version="v1",
        expected_section="Refund eligibility",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="published_public_product_warranty",
        query="warranty accidental damage",
        audience="customer",
        expected_document_id="warranty-policy",
        expected_version="v1",
        expected_section="Product warranty coverage",
        expect_supported_answer=True,
    ),
)


DEVELOPMENT_EVALUATION_SET_VERSION = "rag-development-v1"

# Independently authored public development labels.  Keep this tuple separate
# from the frozen M2/M11A cases and from benchmark/holdout data so additions do
# not silently rewrite historical metrics.  Queries intentionally include
# paraphrases, near-policy hard negatives, ambiguity, stale-version language,
# customer attempts to reach internal policy, and unsupported requests.
DEVELOPMENT_EVALUATION_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        label="dev_paraphrase_delivery_estimate",
        query="My parcel is late; how do I get an updated arrival estimate?",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Delayed shipments",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="dev_paraphrase_return_deadline",
        query="I want to send back an unused item; what deadline applies after delivery?",
        audience="customer",
        expected_document_id="returns-policy",
        expected_version="v1",
        expected_section="Return window",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="dev_paraphrase_damage_evidence",
        query="The product arrived broken; should I keep the box and send pictures?",
        audience="customer",
        expected_document_id="product-damage-policy",
        expected_version="v1",
        expected_section="Damaged items",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="dev_hard_negative_shipping_vs_delay",
        query="When does the shipping estimate begin once the carrier accepts my order?",
        audience="customer",
        expected_document_id="shipping-policy",
        expected_version="v1",
        expected_section="Shipping estimates",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="dev_hard_negative_refund_status_vs_eligibility",
        query="My eligible return was received; when does credit processing begin?",
        audience="customer",
        expected_document_id="refund-processing-policy",
        expected_version="v1",
        expected_section="Return credit processing",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="dev_hard_negative_warranty_coverage",
        query="Does the product warranty cover a defect during normal use?",
        audience="customer",
        expected_document_id="warranty-policy",
        expected_version="v1",
        expected_section="Product warranty coverage",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="dev_ambiguous_order_request",
        query="Can you help with my order?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
    EvaluationCase(
        label="dev_ambiguous_refund_request",
        query="I need money back; what are my options?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
    EvaluationCase(
        label="dev_wrong_version_return_window",
        query="Is the old 14-day return policy still current, or should I use the current window?",
        audience="customer",
        expected_document_id="returns-policy",
        expected_version="v1",
        expected_section="Return window",
        expect_supported_answer=True,
        forbidden_version="v0",
    ),
    EvaluationCase(
        label="dev_wrong_version_delay_wait_rule",
        query="Does the old three-business-day delay rule still apply, or can I contact support now?",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Delayed shipments",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="dev_internal_customer_refund_authority",
        query="Can a refund approver authorize the external payment action for my request?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
        forbidden_document_id="refund-review-policy",
    ),
    EvaluationCase(
        label="dev_internal_customer_warranty_matrix",
        query="Please show me the internal warranty exception matrix for my product.",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
        forbidden_document_id="warranty-policy",
    ),
    EvaluationCase(
        label="dev_unsupported_account_password",
        query="Where do I update my login email address?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
    EvaluationCase(
        label="dev_unsupported_tracking_number",
        query="What is the parcel reference code for my shipment?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
    EvaluationCase(
        label="dev_unsupported_gift_wrapping",
        query="Do you offer gift wrapping?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
)


FRESH_DEVELOPMENT_EVALUATION_SET_VERSION = "rag-development-v2"

# A fresh, independently authored development set for M11B-R.  These labels
# are intentionally separate from the historical M2/M11A cases, the M8
# benchmark, and private holdouts.  They are for diagnosis and candidate
# selection only; they do not change customer answer acceptance.
FRESH_DEVELOPMENT_EVALUATION_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        label="fresh_paraphrase_missing_delivery",
        query="The tracking page says delivered, but I cannot find the parcel anywhere.",
        audience="customer",
        expected_document_id="missing-package-policy",
        expected_version="v1",
        expected_section="Delivered but not received",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="fresh_paraphrase_cancellation",
        query="Can I stop the order before the carrier takes it into fulfillment?",
        audience="customer",
        expected_document_id="order-cancellation-policy",
        expected_version="v1",
        expected_section="Order cancellations",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="fresh_paraphrase_warranty_defect",
        query="A product failed during ordinary use; is that covered by the limited warranty?",
        audience="customer",
        expected_document_id="warranty-policy",
        expected_version="v1",
        expected_section="Product warranty coverage",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="fresh_hard_negative_delivery_investigation",
        query="The carrier has not moved the shipment for several business days; can support investigate?",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Late delivery follow-up",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="fresh_hard_negative_credit_eligibility",
        query="The item problem was verified; when can a credit request be considered?",
        audience="customer",
        expected_document_id="refund-eligibility-policy",
        expected_version="v1",
        expected_section="Refund eligibility",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="fresh_hard_negative_wrong_item",
        query="The shipment contains a different product than the one I ordered.",
        audience="customer",
        expected_document_id="fulfillment-policy",
        expected_version="v1",
        expected_section="Wrong items",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="fresh_wrong_version_delay_rule",
        query="Is the previous wait-before-contacting rule still used for late shipments?",
        audience="customer",
        expected_document_id="delivery-policy",
        expected_version="v2",
        expected_section="Delayed shipments",
        expect_supported_answer=True,
        forbidden_version="v1",
    ),
    EvaluationCase(
        label="fresh_wrong_version_return_window",
        query="Does the former fourteen-day window still apply to an unused product?",
        audience="customer",
        expected_document_id="returns-policy",
        expected_version="v1",
        expected_section="Return window",
        expect_supported_answer=True,
        forbidden_version="v0",
    ),
    EvaluationCase(
        label="fresh_staff_refund_review",
        query="Which internal review roles must authorize an external refund action?",
        audience="support_agent",
        expected_document_id="refund-review-policy",
        expected_version="v1",
        expected_section="Refund review",
        expect_supported_answer=True,
    ),
    EvaluationCase(
        label="fresh_customer_internal_refund_authority",
        query="Please disclose the staff authorization steps for an external refund payment.",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
        forbidden_document_id="refund-review-policy",
    ),
    EvaluationCase(
        label="fresh_customer_internal_warranty_matrix",
        query="Show me the employee-only warranty exception decision matrix.",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
    EvaluationCase(
        label="fresh_ambiguous_order_help",
        query="I need assistance with something about my order.",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
    EvaluationCase(
        label="fresh_ambiguous_money_back",
        query="Can you tell me what to do about getting money back?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
    EvaluationCase(
        label="fresh_unsupported_address_change",
        query="How can I change the delivery address after placing the order?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
    EvaluationCase(
        label="fresh_unsupported_gift_message",
        query="Can the merchant add a gift message to my package?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
    EvaluationCase(
        label="fresh_unsupported_subscription",
        query="Where can I manage a recurring subscription for this product?",
        audience="customer",
        expected_document_id=None,
        expected_version=None,
        expected_section=None,
        expect_supported_answer=False,
    ),
)


def validate_evaluation_case_labels(
    cases: Sequence[EvaluationCase],
    *,
    corpus: Sequence[PolicyRecord] = POLICY_CORPUS,
) -> tuple[str, ...]:
    """Return stable-label errors before an evaluation set is executed."""

    errors: list[str] = []
    records = {
        (record.document_id, record.document_version, record.section): record
        for record in corpus
    }
    records_by_document = {}
    for record in corpus:
        records_by_document.setdefault(record.document_id, set()).add(
            record.document_version
        )
    seen_labels: set[str] = set()

    for case in cases:
        if not case.label.strip():
            errors.append("case has an empty label")
        elif case.label in seen_labels:
            errors.append(f"{case.label}: duplicate label")
        seen_labels.add(case.label)
        if not case.query.strip():
            errors.append(f"{case.label}: query is empty")

        expected_key = (
            case.expected_document_id,
            case.expected_version,
            case.expected_section,
        )
        if case.expected_document_id is None:
            if any(value is not None for value in expected_key[1:]):
                errors.append(f"{case.label}: unsupported case has partial expected policy")
            if case.expect_supported_answer:
                errors.append(f"{case.label}: supported case has no expected policy")
        else:
            record = records.get(expected_key)
            if record is None:
                errors.append(f"{case.label}: expected policy is absent from corpus")
            else:
                if record.status != "published":
                    errors.append(f"{case.label}: expected policy is not published")
                if case.audience == "customer" and record.visibility != "public":
                    errors.append(f"{case.label}: customer expected policy is not public")
                if not record.text.strip():
                    errors.append(f"{case.label}: expected policy has no text")

        if case.forbidden_document_id is not None and case.forbidden_document_id not in records_by_document:
            errors.append(
                f"{case.label}: forbidden document is absent from corpus"
            )
        if case.forbidden_version is not None:
            if case.expected_document_id is None:
                errors.append(
                    f"{case.label}: forbidden version needs an expected document"
                )
            elif case.forbidden_version not in records_by_document.get(
                case.expected_document_id, set()
            ):
                errors.append(f"{case.label}: forbidden version is absent from corpus")

    return tuple(errors)


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
            "accepted_evidence_recall_at_3": self.recall_at_3,
            "Recall@3": self.recall_at_3,
            "wrong_version_exposure": self.wrong_version_exposure,
            "citation_visibility_accuracy": self.citation_visibility_accuracy,
            "unsupported_answer_behavior": self.unsupported_answer_behavior,
            "cases": [case.model_dump(mode="json") for case in self.cases],
        }


class RawCandidatePolicyRetriever(Protocol):
    """Semantic retriever boundary that exposes access-filtered raw ranking."""

    def retrieve_published_policy_candidates(
        self,
        query: str,
        audience: PolicyAudience = "customer",
        top_k: int = 3,
    ) -> Sequence[PolicyEvidence]:
        """Return ranked candidates before the semantic confidence gate."""


class RawRankingCaseResult(BaseModel):
    """Ranking and 0.60-gate facts, before answer evidence is accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    expected_rank: int | None
    top_similarity_score: float | None
    semantic_gate_accepted: bool
    citation_access_control_valid: bool
    wrong_version_exposed: bool


class RawRankingEvaluationReport(BaseModel):
    """Keep raw semantic ranking distinct from answer-evidence acceptance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query_count: int
    supported_query_count: int
    raw_recall_at_3: float
    raw_mrr: float
    supported_semantic_gate_acceptance: float
    citation_access_control_accuracy: float
    wrong_version_exposure: float
    cases: list[RawRankingCaseResult]

    def as_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class AnswerContractCaseResult(BaseModel):
    """Outcome of the customer-facing grounded-answer contract for one case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    answer_contract_valid: bool
    evidence_sufficient: bool
    citation_access_control_valid: bool
    evidence_access_control_valid: bool
    wrong_version_exposed: bool
    retrieval_mode: str


class AnswerContractEvaluationReport(BaseModel):
    """Keep answer usefulness separate from retrieval candidate ranking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query_count: int
    supported_query_count: int
    supported_answer_accuracy: float
    unsupported_answer_behavior: float
    unsupported_false_acceptance_rate: float
    citation_access_control_accuracy: float
    evidence_access_control_accuracy: float
    wrong_version_exposure: float
    cases: list[AnswerContractCaseResult]

    def as_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


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


def _expected_rank(
    evidence: Sequence[PolicyEvidence], case: EvaluationCase
) -> int | None:
    if case.expected_document_id is None:
        return None
    for index, item in enumerate(evidence[:3], start=1):
        if _matches_expected(item, case) and _visibility_valid(item, case.audience):
            return index
    return None


def _wrong_version_exposed(
    evidence: Sequence[PolicyEvidence], case: EvaluationCase
) -> bool:
    return any(
        (
            case.forbidden_document_id is not None
            and item.document_id == case.forbidden_document_id
        )
        or (
            case.expected_document_id is not None
            and case.forbidden_version is not None
            and item.document_id == case.expected_document_id
            and item.document_version == case.forbidden_version
        )
        for item in evidence
    )


def _citation_access_control_valid(
    evidence: Sequence[PolicyEvidence], audience: PolicyAudience
) -> bool:
    return all(
        item.status == "published"
        and bool(item.release_id)
        and bool(item.document_version)
        and bool(item.section)
        and _visibility_valid(item, audience)
        for item in evidence
    )


def evaluate_raw_semantic_ranking(
    cases: Sequence[EvaluationCase] = DEFAULT_EVALUATION_CASES,
    *,
    policy_retriever: RawCandidatePolicyRetriever,
) -> RawRankingEvaluationReport:
    """Measure raw semantic top-3 ranking before the answer confidence gate."""

    if not cases:
        raise ValueError("at least one evaluation case is required")

    results: list[RawRankingCaseResult] = []
    supported_total = 0
    recall_hits = 0
    reciprocal_ranks: list[float] = []
    supported_gate_accepts = 0
    citation_valid_count = 0
    version_sensitive_count = 0
    wrong_version_count = 0

    for case in cases:
        retrieved = list(
            policy_retriever.retrieve_published_policy_candidates(
                case.query,
                audience=case.audience,
                top_k=3,
            )
        )
        rank = _expected_rank(retrieved, case)
        if case.expected_document_id is not None:
            supported_total += 1
            recall_hits += int(rank is not None)
            reciprocal_ranks.append(1.0 / rank if rank is not None else 0.0)
            supported_gate_accepts += int(is_sufficient_semantic_match(retrieved))

        citation_valid = _citation_access_control_valid(retrieved, case.audience)
        citation_valid_count += int(citation_valid)
        wrong_version = _wrong_version_exposed(retrieved, case)
        if case.forbidden_version is not None or case.forbidden_document_id is not None:
            version_sensitive_count += 1
            wrong_version_count += int(wrong_version)

        results.append(
            RawRankingCaseResult(
                label=case.label,
                expected_rank=rank,
                top_similarity_score=(retrieved[0].score if retrieved else None),
                semantic_gate_accepted=is_sufficient_semantic_match(retrieved),
                citation_access_control_valid=citation_valid,
                wrong_version_exposed=wrong_version,
            )
        )

    return RawRankingEvaluationReport(
        query_count=len(cases),
        supported_query_count=supported_total,
        raw_recall_at_3=recall_hits / supported_total if supported_total else 0.0,
        raw_mrr=mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        supported_semantic_gate_acceptance=(
            supported_gate_accepts / supported_total if supported_total else 0.0
        ),
        citation_access_control_accuracy=citation_valid_count / len(cases),
        wrong_version_exposure=(
            wrong_version_count / version_sensitive_count
            if version_sensitive_count
            else 0.0
        ),
        cases=results,
    )


def evaluate_policy_retrieval(
    cases: Sequence[EvaluationCase] = DEFAULT_EVALUATION_CASES,
    *,
    corpus: Sequence[PolicyRecord] = POLICY_CORPUS,
    policy_retriever: PolicyRetriever | None = None,
) -> RetrievalEvaluationReport:
    """Evaluate thresholded retrieval and resulting answer contract.

    The default remains the deterministic lexical baseline. Supplying the
    application retrieval boundary lets the same frozen labels evaluate a
    semantic/pgvector backend without duplicating policy-access assertions.
    For pre-gate ranking, use :func:`evaluate_raw_semantic_ranking` instead.
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

        wrong_version = _wrong_version_exposed(retrieved, case)
        if case.forbidden_version is not None or case.forbidden_document_id is not None:
            version_sensitive_count += 1
            wrong_version_count += int(wrong_version)

        citation_valid = _citation_access_control_valid(retrieved, case.audience)
        if case.expected_document_id is not None:
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
        else:
            # Retrieval candidates are not customer-facing citations. A weak
            # public candidate is safe when the answer contract discards it
            # and returns a handoff; injected unauthorized evidence remains
            # invalid through ``citation_valid`` above.
            citation_valid = citation_valid and not answer.evidence
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


def evaluate_answer_contract(
    cases: Sequence[EvaluationCase] = DEFAULT_EVALUATION_CASES,
    *,
    corpus: Sequence[PolicyRecord] = POLICY_CORPUS,
    policy_retriever: PolicyRetriever | None = None,
) -> AnswerContractEvaluationReport:
    """Evaluate the actual safe answer path, including configured fallback.

    This intentionally does not substitute a snapshot retriever.  The
    customer-facing result—including the existing lexical fallback after a
    semantic-backend failure, when applicable—rather than the raw candidate
    list is what this report measures.
    """

    if not cases:
        raise ValueError("at least one evaluation case is required")

    from backend.app.ai.answer import answer_from_published_policy

    results: list[AnswerContractCaseResult] = []
    supported_total = 0
    supported_valid = 0
    unsupported_total = 0
    unsupported_valid = 0
    unsupported_false_accepts = 0
    citation_valid_count = 0
    evidence_access_valid_count = 0
    wrong_version_count = 0
    version_sensitive_count = 0

    for case in cases:
        answer = answer_from_published_policy(
            case.query,
            audience=case.audience,
            corpus=corpus,
            policy_retriever=policy_retriever,
        )
        primary_matches_expected = bool(answer.evidence) and _matches_expected(
            answer.evidence[0], case
        )
        evidence_valid = all(
            evidence.status == "published"
            and bool(evidence.release_id)
            and _visibility_valid(evidence, case.audience)
            for evidence in answer.evidence
        )
        evidence_sufficient = (
            answer.grounded
            and answer.answer is not None
            and not answer.needs_handoff
            and bool(answer.evidence)
        )
        if case.expect_supported_answer:
            supported_total += 1
            answer_valid = (
                answer.grounded
                and answer.answer is not None
                and not answer.needs_handoff
                and primary_matches_expected
                and evidence_valid
            )
            supported_valid += int(answer_valid)
            citation_valid = answer_valid
        else:
            unsupported_total += 1
            answer_valid = (
                not answer.grounded
                and answer.answer is None
                and answer.needs_handoff
                and not answer.evidence
            )
            unsupported_valid += int(answer_valid)
            citation_valid = answer_valid and evidence_valid
            unsupported_false_accepts += int(
                answer.grounded or answer.answer is not None or bool(answer.evidence)
            )

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
            for evidence in answer.evidence
        )
        if case.forbidden_document_id is not None or case.forbidden_version is not None:
            version_sensitive_count += 1
            wrong_version_count += int(wrong_version)
        citation_valid_count += int(citation_valid)
        evidence_access_valid_count += int(evidence_valid)
        results.append(
            AnswerContractCaseResult(
                label=case.label,
                answer_contract_valid=answer_valid,
                evidence_sufficient=evidence_sufficient,
                citation_access_control_valid=citation_valid,
                evidence_access_control_valid=evidence_valid,
                wrong_version_exposed=wrong_version,
                retrieval_mode=answer.retrieval_mode,
            )
        )

    return AnswerContractEvaluationReport(
        query_count=len(cases),
        supported_query_count=supported_total,
        supported_answer_accuracy=(
            supported_valid / supported_total if supported_total else 0.0
        ),
        unsupported_answer_behavior=(
            unsupported_valid / unsupported_total if unsupported_total else 0.0
        ),
        unsupported_false_acceptance_rate=(
            unsupported_false_accepts / unsupported_total if unsupported_total else 0.0
        ),
        citation_access_control_accuracy=citation_valid_count / len(cases),
        evidence_access_control_accuracy=evidence_access_valid_count / len(cases),
        wrong_version_exposure=(
            wrong_version_count / version_sensitive_count
            if version_sensitive_count
            else 0.0
        ),
        cases=results,
    )


__all__ = [
    "AnswerContractCaseResult",
    "AnswerContractEvaluationReport",
    "DEFAULT_EVALUATION_CASES",
    "DEVELOPMENT_EVALUATION_CASES",
    "DEVELOPMENT_EVALUATION_SET_VERSION",
    "EvaluationCase",
    "M11A_EVALUATION_CASES",
    "RawCandidatePolicyRetriever",
    "RawRankingCaseResult",
    "RawRankingEvaluationReport",
    "RetrievalEvaluationReport",
    "evaluate_raw_semantic_ranking",
    "evaluate_policy_retrieval",
    "evaluate_answer_contract",
    "validate_evaluation_case_labels",
]
