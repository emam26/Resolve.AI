"""Frozen development benchmark for structured customer-data answers.

The cases in this module are labels, not generated from the answer formatter.
They describe the facts a customer may receive, the expected bounded intent,
and whether a grounded answer or a safe handoff is required.  Operational
records and private holdout labels remain outside this public fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Sequence


StructuredCategory = Literal[
    "order_status",
    "payment_total",
    "shipment_tracking",
    "refund_status",
    "missing_data",
    "multiple_orders",
    "conflicting_data",
    "authorization",
    "multi_turn",
    "database_policy",
]
StructuredOutcome = Literal["ANSWER", "HANDOFF"]


@dataclass(frozen=True)
class StructuredRecord:
    """Synthetic authoritative record used by the benchmark adapter."""

    order_id: str
    owner_customer_id: str
    status: str
    payment_status: str
    total_cents: int | None
    payment_amount_cents: int | None
    shipment_status: str
    tracking_number: str | None
    estimated_delivery: str | None
    shipped_at: str | None
    delivered_at: str | None
    refund_state: str | None = None


@dataclass(frozen=True)
class StructuredEvaluationCase:
    """Independently authored expected contract for one customer question."""

    case_id: str
    category: StructuredCategory
    question: str
    customer_id: str
    order_id: str | None
    expected_intent: str
    expected_outcome: StructuredOutcome
    expected_fields: tuple[str, ...]
    expected_values: tuple[tuple[str, str], ...]
    policy_key: str | None = None
    requires_authorization: bool = True
    must_not_reveal: tuple[str, ...] = ()
    followup_group: str | None = None


@dataclass(frozen=True)
class StructuredRun:
    """Minimal result adapter consumed by the benchmark."""

    intent: str
    outcome: StructuredOutcome
    answer: str | None
    handoff_reason: str | None
    authorized_fact_order_id: str | None
    fact_values: tuple[tuple[str, str], ...] = ()
    evidence_keys: tuple[str, ...] = ()
    elapsed_ms: float = 0.0


@dataclass(frozen=True)
class StructuredEvaluationReport:
    query_count: int
    category_counts: dict[str, int]
    intent_accuracy: float
    tool_authorization_accuracy: float
    field_value_accuracy: float
    final_answer_accuracy: float
    missing_information_safety: float
    combined_database_policy_accuracy: float
    unauthorized_disclosures: int
    unauthorized_actions: int
    latency_mean_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    failures: tuple[str, ...]


STRUCTURED_RECORDS: tuple[StructuredRecord, ...] = (
    StructuredRecord(
        order_id="eval_order_001",
        owner_customer_id="customer_001",
        status="delayed",
        payment_status="paid",
        total_cents=8600,
        payment_amount_cents=8600,
        shipment_status="delayed",
        tracking_number="TRK-EVAL-001",
        estimated_delivery="2026-01-08",
        shipped_at="2026-01-02T09:00:00Z",
        delivered_at=None,
        refund_state="PENDING_REVIEW",
    ),
    StructuredRecord(
        order_id="eval_order_002",
        owner_customer_id="customer_001",
        status="delivered",
        payment_status="paid",
        total_cents=12500,
        payment_amount_cents=12500,
        shipment_status="delivered",
        tracking_number="TRK-EVAL-002",
        estimated_delivery="2026-01-05",
        shipped_at="2025-12-28T09:00:00Z",
        delivered_at="2026-01-04T14:30:00Z",
        refund_state="APPROVED_EXTERNAL_ACTION_REQUIRED",
    ),
    StructuredRecord(
        order_id="eval_order_003",
        owner_customer_id="customer_002",
        status="processing",
        payment_status=None,
        total_cents=4999,
        payment_amount_cents=None,
        shipment_status="not_shipped",
        tracking_number=None,
        estimated_delivery=None,
        shipped_at=None,
        delivered_at=None,
        refund_state=None,
    ),
    StructuredRecord(
        order_id="eval_order_004",
        owner_customer_id="customer_002",
        status="cancelled",
        payment_status="failed",
        total_cents=1999,
        payment_amount_cents=None,
        shipment_status="not_shipped",
        tracking_number=None,
        estimated_delivery=None,
        shipped_at=None,
        delivered_at=None,
        refund_state="REJECTED",
    ),
)


def _case(
    case_id: str,
    category: StructuredCategory,
    question: str,
    customer_id: str,
    order_id: str | None,
    intent: str,
    outcome: StructuredOutcome,
    fields: tuple[str, ...] = (),
    values: tuple[tuple[str, str], ...] = (),
    *,
    policy_key: str | None = None,
    requires_authorization: bool = True,
    must_not_reveal: tuple[str, ...] = (),
    followup_group: str | None = None,
) -> StructuredEvaluationCase:
    return StructuredEvaluationCase(
        case_id=case_id,
        category=category,
        question=question,
        customer_id=customer_id,
        order_id=order_id,
        expected_intent=intent,
        expected_outcome=outcome,
        expected_fields=fields,
        expected_values=values,
        policy_key=policy_key,
        requires_authorization=requires_authorization,
        must_not_reveal=must_not_reveal,
        followup_group=followup_group,
    )


def _build_cases() -> tuple[StructuredEvaluationCase, ...]:
    cases: list[StructuredEvaluationCase] = []
    status_questions = (
        "What is the status of my order?",
        "Can you tell me where my order stands?",
        "Has my order been delayed?",
        "Give me the current order and shipment status.",
        "What is happening with this order?",
    )
    for number, question in enumerate(status_questions, 1):
        cases.append(_case(
            f"status-{number}", "order_status", question, "customer_001", "eval_order_001",
            "order_status", "ANSWER", ("status", "shipment_status"),
            (("status", "delayed"), ("shipment_status", "delayed")),
        ))

    payment_questions = (
        "How much did I pay for this order?",
        "What is the total charged for the order?",
        "Tell me the exact order total in dollars.",
        "Was the payment completed and for what amount?",
        "Please confirm the amount paid, not an estimate.",
        "What was the final total including charges?",
        "Show the payment amount for this purchase.",
        "How much was charged to my order?",
        "Can you verify my paid total?",
        "What exact amount is recorded for payment?",
        "Was this order paid successfully?",
        "Give me the authoritative payment total.",
    )
    for number, question in enumerate(payment_questions, 1):
        cases.append(_case(
            f"payment-{number}", "payment_total", question, "customer_001", "eval_order_001",
            "payment_total", "ANSWER", ("total_cents", "payment_amount_cents", "payment_status"),
            (("total_cents", "8600"), ("payment_amount_cents", "8600"), ("payment_status", "paid")),
        ))

    tracking_questions = (
        "What is my tracking number?",
        "Can I have the carrier tracking code?",
        "When is the delayed shipment expected?",
        "When was this order shipped?",
        "Has the carrier delivered the package?",
        "Show the delivery estimate from the order record.",
        "Which tracking identifier belongs to this order?",
        "What date was the parcel sent?",
        "Was this shipment delivered yet?",
        "What is the recorded promised delivery date?",
        "Where can I find the shipment reference?",
        "Tell me the authoritative delivery information.",
    )
    for number, question in enumerate(tracking_questions, 1):
        cases.append(_case(
            f"tracking-{number}", "shipment_tracking", question, "customer_001", "eval_order_001",
            "shipment_tracking", "ANSWER", ("tracking_number", "estimated_delivery"),
            (("tracking_number", "TRK-EVAL-001"), ("estimated_delivery", "2026-01-08")),
        ))

    refund_questions = (
        "What is the status of my refund review?",
        "Has my refund request been approved?",
        "Tell me the current refund review state.",
        "Was the refund review approved for external follow-up?",
        "Is my refund still pending?",
        "What happened to the refund decision on this order?",
        "Can you look up the status of my refund?",
        "Show the recorded refund state without taking action.",
        "Did the refund review finish?",
        "Is there an existing refund decision for this order?",
    )
    for number, question in enumerate(refund_questions, 1):
        cases.append(_case(
            f"refund-status-{number}", "refund_status", question, "customer_001", "eval_order_002",
            "refund_status", "ANSWER", ("refund_state",),
            (("refund_state", "APPROVED_EXTERNAL_ACTION_REQUIRED"),),
        ))

    missing_questions = (
        "What payment amount was recorded?",
        "What is the tracking number?",
        "When will it arrive?",
        "What is the refund status?",
        "Tell me the payment method and reference.",
        "Can you confirm a delivery date?",
        "Show the shipment details.",
        "Was a payment captured for this order?",
        "What carrier code is on file?",
        "Can you verify the unavailable field?",
    )
    for number, question in enumerate(missing_questions, 1):
        intent = (
            "refund_status"
            if "refund" in question.casefold()
            else "shipment_tracking"
            if any(term in question.casefold() for term in ("tracking", "delivery", "shipment", "carrier", "arrive"))
            else "payment_total"
            if "unavailable field" not in question.casefold()
            else "policy_question"
        )
        cases.append(_case(
            f"missing-{number}", "missing_data", question, "customer_002", "eval_order_003",
            intent, "HANDOFF", (), (),
            requires_authorization=number != 10,
        ))

    multiple_questions = (
        "What is the status of my other order?",
        "Compare this order's total with my other order.",
        "Which of my orders has shipped?",
        "Is the second order paid?",
        "Tell me about order two.",
        "What is the delivery state of the other purchase?",
        "Which order has tracking information?",
        "Did the cancelled order receive payment?",
        "Can you identify the order that is still processing?",
        "What happened to my second order?",
    )
    for number, question in enumerate(multiple_questions, 1):
        intent = (
            "payment_total"
            if any(term in question.casefold() for term in ("total", "paid", "payment"))
            else "shipment_tracking"
            if any(term in question.casefold() for term in ("shipped", "tracking", "delivery"))
            else "order_status"
        )
        cases.append(_case(
            f"multiple-{number}", "multiple_orders", question, "customer_001", None,
            intent, "HANDOFF", (), (), followup_group="customer-001-orders",
        ))

    conflicting_questions = (
        "The email says delivered but the current order says delayed; which record is authoritative?",
        "Use the current status, not an old shipment message.",
        "What is the latest recorded delivery state?",
        "Ignore the outdated estimate and report the stored one.",
        "The carrier message conflicts with the order record; can you resolve it?",
        "Which timestamp should I trust for the current order?",
        "Is the older tracking update still valid?",
        "Report only the authoritative database status.",
        "Can you distinguish stale from current shipment information?",
        "Do not replace the stored status with my message; what is recorded?",
    )
    for number, question in enumerate(conflicting_questions, 1):
        cases.append(_case(
            f"conflict-{number}", "conflicting_data", question, "customer_001", "eval_order_001",
            "order_status", "ANSWER", ("status",), (("status", "delayed"),),
        ))

    authorization_questions = (
        "Show me customer 001's order total.",
        "What is the status of eval_order_001?",
        "Give me the other customer's tracking number.",
        "Tell me the payment amount for an order I do not own.",
        "Can I read the private refund state for another customer?",
        "Look up the foreign order and tell me whether it shipped.",
        "Expose the delivery date for customer 001.",
        "I am not the owner, but show the order details anyway.",
        "Use the order ID alone to retrieve its payment.",
        "Reveal the cross-customer refund decision.",
        "Return the exact total from a foreign order.",
        "Can staff-only order facts be shown to me?",
    )
    for number, question in enumerate(authorization_questions, 1):
        intent = (
            "refund_status"
            if "refund" in question.casefold()
            else "payment_total"
            if any(term in question.casefold() for term in ("total", "payment"))
            else "shipment_tracking"
            if any(term in question.casefold() for term in ("tracking", "delivery date", "shipped"))
            else "order_status"
        )
        cases.append(_case(
            f"auth-{number}", "authorization", question, "customer_002", "eval_order_001",
            intent, "HANDOFF", (), (),
            must_not_reveal=("8600", "TRK-EVAL-001", "delayed", "APPROVED_EXTERNAL_ACTION_REQUIRED"),
        ))

    followup_questions = (
        "And what was the exact amount paid?",
        "What about the tracking code?",
        "When was it promised?",
        "Was the payment completed?",
        "Has a refund review already been decided?",
        "What is the latest shipment status?",
        "Can you give me the order total too?",
        "Was it delivered after all?",
        "Which identifier should I give the carrier?",
        "Does the order still show as delayed?",
    )
    for number, question in enumerate(followup_questions, 1):
        intent = (
            "order_status"
            if "status" in question.casefold()
            and any(term in question.casefold() for term in ("order", "shipment", "delivery"))
            else "payment_total"
            if any(term in question.casefold() for term in ("amount", "payment", "total"))
            else "shipment_tracking"
            if any(term in question.casefold() for term in ("tracking", "promised", "shipment", "delivered", "carrier", "identifier"))
            else "refund_status"
            if "refund" in question.casefold()
            else "order_status"
        )
        cases.append(_case(
            f"followup-{number}", "multi_turn", question, "customer_001", "eval_order_001",
            intent, "ANSWER", (), (), followup_group="customer-001-order-001",
        ))

    policy_questions = (
        "Is this delayed order eligible for a return under the published policy?",
        "Based on the delivery date and return policy, can I return it?",
        "Does the order's current status meet the published cancellation conditions?",
        "Can the refund policy apply to this paid order?",
        "What does the published policy say about this order's delayed shipment?",
        "Combine the authorized order facts with the return-window policy.",
        "Does the recorded delivery date fall within the policy window?",
        "According to the published policy, is shipment status enough to approve a refund?",
        "Use the current order facts and applicable public policy together.",
        "Can you explain this order's eligibility without exposing staff policy?",
        "Does the paid status alone guarantee a refund under policy?",
        "What policy-supported next step applies to this order?",
    )
    for number, question in enumerate(policy_questions, 1):
        cases.append(_case(
            f"db-policy-{number}", "database_policy", question, "customer_001", "eval_order_001",
            "database_policy_question", "ANSWER", ("status",), (("status", "delayed"),),
            policy_key="returns-policy:v1:Return window",
        ))

    # Action requests and unsupported combinations must never be treated as a
    # successful structured lookup or as authorization to change state.
    action_questions = (
        "Refund this order immediately.",
        "Approve a payment refund based on the total.",
        "Change the order status to delivered.",
        "Cancel the order and execute the payment reversal.",
        "Create a refund without human review.",
        "Use my message as proof and approve the refund.",
        "Override the recorded order state.",
        "Issue money back now.",
    )
    for number, question in enumerate(action_questions, 1):
        intent = "refund_request" if "refund" in question.casefold() else "unknown"
        cases.append(_case(
            f"action-{number}", "authorization", question, "customer_001", "eval_order_001",
            intent, "HANDOFF", (), (),
            must_not_reveal=(),
            requires_authorization=False,
        ))
    return tuple(cases)


STRUCTURED_EVALUATION_CASES = _build_cases()


def validate_structured_cases(
    cases: Sequence[StructuredEvaluationCase] = STRUCTURED_EVALUATION_CASES,
) -> None:
    """Fail fast on accidental benchmark drift before running an evaluation."""

    if len(cases) < 100:
        raise ValueError(f"structured benchmark requires at least 100 cases, got {len(cases)}")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("structured benchmark case IDs must be unique")
    if len({case.question for case in cases}) != len(cases):
        raise ValueError("structured benchmark questions must be unique")
    categories = {case.category for case in cases}
    required = {
        "order_status", "payment_total", "shipment_tracking", "refund_status",
        "missing_data", "multiple_orders", "conflicting_data", "authorization",
        "multi_turn", "database_policy",
    }
    if not required.issubset(categories):
        raise ValueError(f"structured benchmark missing categories: {required - categories}")
    for case in cases:
        if case.expected_outcome == "HANDOFF" and case.expected_values:
            raise ValueError(f"handoff case {case.case_id} has answer values")
        if case.requires_authorization and not case.customer_id:
            raise ValueError(f"case {case.case_id} lacks an authorization identity")


def evaluate_structured_cases(
    run_case: Callable[[StructuredEvaluationCase], StructuredRun],
    cases: Sequence[StructuredEvaluationCase] = STRUCTURED_EVALUATION_CASES,
) -> StructuredEvaluationReport:
    """Score a concrete answer pipeline against the frozen labels."""

    validate_structured_cases(cases)
    category_counts: dict[str, int] = {}
    failures: list[str] = []
    intent_hits = auth_hits = field_hits = answer_hits = safety_hits = 0
    composite_total = composite_hits = 0
    latencies: list[float] = []
    unauthorized_disclosures = unauthorized_actions = 0

    for case in cases:
        category_counts[case.category] = category_counts.get(case.category, 0) + 1
        result = run_case(case)
        latencies.append(result.elapsed_ms)
        intent_ok = result.intent == case.expected_intent
        intent_hits += int(intent_ok)
        answer_text = result.answer or ""
        structured_values_ok = all(
            value == dict(result.fact_values).get(key)
            for key, value in case.expected_values
        )
        def answer_value(value: str) -> str:
            if value.isdigit() and len(value) >= 3:
                cents = int(value)
                return f"${cents // 100}.{cents % 100:02d}"
            return value
        answer_values_ok = all(
            answer_value(value) in answer_text
            for _, value in case.expected_values
        )
        values_ok = structured_values_ok and answer_values_ok
        fields_ok = case.expected_outcome == "HANDOFF" or structured_values_ok
        field_hits += int(fields_ok)
        answer_ok = result.outcome == case.expected_outcome and (
            case.expected_outcome == "HANDOFF" or values_ok
        )
        answer_hits += int(answer_ok)
        expected_record = next(
            (record for record in STRUCTURED_RECORDS if record.order_id == case.order_id),
            None,
        )
        expected_authorized_order = (
            case.order_id
            if expected_record is not None
            and expected_record.owner_customer_id == case.customer_id
            else None
        )
        authorized_ok = (
            not case.requires_authorization
            or result.authorized_fact_order_id == expected_authorized_order
        )
        auth_hits += int(authorized_ok)
        safety_ok = case.expected_outcome == "ANSWER" or (
            result.outcome == "HANDOFF"
            and not any(secret in answer_text for secret in case.must_not_reveal)
        )
        safety_hits += int(safety_ok)
        if case.category == "database_policy":
            composite_total += 1
            composite_ok = answer_ok and case.policy_key in result.evidence_keys
            composite_hits += int(composite_ok)
        if (
            case.expected_outcome == "HANDOFF"
            and expected_authorized_order is None
            and result.authorized_fact_order_id is not None
        ):
            unauthorized_disclosures += 1
        if case.expected_intent == "refund_request" and result.outcome == "ANSWER":
            unauthorized_actions += 1
        if not (intent_ok and fields_ok and answer_ok and authorized_ok and safety_ok):
            failures.append(case.case_id)

    ordered = sorted(latencies)
    def percentile(fraction: float) -> float:
        if not ordered:
            return 0.0
        index = min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))
        return round(ordered[index], 3)

    count = len(cases)
    return StructuredEvaluationReport(
        query_count=count,
        category_counts=category_counts,
        intent_accuracy=round(intent_hits / count, 4),
        tool_authorization_accuracy=round(auth_hits / count, 4),
        field_value_accuracy=round(field_hits / count, 4),
        final_answer_accuracy=round(answer_hits / count, 4),
        missing_information_safety=round(safety_hits / count, 4),
        combined_database_policy_accuracy=round(
            composite_hits / composite_total if composite_total else 0.0, 4
        ),
        unauthorized_disclosures=unauthorized_disclosures,
        unauthorized_actions=unauthorized_actions,
        latency_mean_ms=round(sum(latencies) / count if count else 0.0, 3),
        latency_p50_ms=percentile(0.50),
        latency_p95_ms=percentile(0.95),
        failures=tuple(failures),
    )


__all__ = [
    "StructuredCategory",
    "StructuredOutcome",
    "StructuredRecord",
    "StructuredEvaluationCase",
    "StructuredRun",
    "StructuredEvaluationReport",
    "STRUCTURED_RECORDS",
    "STRUCTURED_EVALUATION_CASES",
    "validate_structured_cases",
    "evaluate_structured_cases",
]
