"""Condition-level evaluation for grounded policy answers.

This module is an evaluation protocol, not a production policy engine. Cases
carry independently authored expectations for policy evidence and authorized
order facts. The evaluator reports whether those expectations are established,
contradicted, or still unknown after the existing retrieval and answer
boundary run.
"""

from __future__ import annotations

from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict

from backend.app.ai.answer import PolicyRetriever, answer_from_published_policy

from .corpus import POLICY_CORPUS
from .models import PolicyAudience, PolicyEvidence, PolicyRecord
from .retrieval import is_sufficient_policy_match, retrieve_published_policy
from .semantic import is_sufficient_semantic_match


ConditionState = Literal["satisfied", "contradicted", "unknown"]
ConditionSource = Literal["policy", "order"]


class PolicyReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    document_version: str
    section: str


class AuthorizedOrderContext(BaseModel):
    """Synthetic, already-authorized facts supplied to an evaluation case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str
    order_id: str
    authorized: bool
    facts: tuple[tuple[str, str], ...] = ()

    def fact(self, key: str) -> str | None:
        return dict(self.facts).get(key)


class ConditionExpectation(BaseModel):
    """One narrow, predeclared condition expected by a development case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    source: ConditionSource
    expected_state: ConditionState
    evidence_phrases: tuple[str, ...] = ()
    contradiction_phrases: tuple[str, ...] = ()
    fact_key: str | None = None
    fact_value: str | None = None


class ConditionLevelCase(BaseModel):
    """Frozen label for condition-level policy evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    query: str
    issue_category: str
    audience: PolicyAudience
    order_context: AuthorizedOrderContext
    expected_policy: PolicyReference | None
    required_conditions: tuple[ConditionExpectation, ...]
    expect_supported_answer: bool
    required_abstention: bool
    permitted_supported_answer: str | None = None
    valid_citation_ids: tuple[str, ...] = ("evidence-1",)
    forbidden_document_ids: tuple[str, ...] = ()
    forbidden_versions: tuple[tuple[str, str], ...] = ()


class ConditionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    source: ConditionSource
    expected_state: ConditionState
    observed_state: ConditionState


class ConditionCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    policy_retrieved: bool
    relevant_evidence_retrieved: bool
    evidence_accepted: bool
    condition_statuses: tuple[ConditionStatus, ...]
    conditions_satisfied: tuple[str, ...]
    conditions_contradicted: tuple[str, ...]
    conditions_unknown: tuple[str, ...]
    answer_fully_supported: bool
    answer_incomplete: bool
    answer_contradictory: bool
    unsafe_information_or_action_attempted: bool
    safe_abstention: bool
    citation_valid: bool
    evidence_access_valid: bool
    wrong_version_exposed: bool


class ConditionLevelReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_count: int
    supported_case_count: int
    policy_retrieval_recall_at_3: float
    evidence_acceptance_rate: float
    condition_completeness: float
    supported_answer_accuracy: float
    unsupported_safety: float
    unsupported_false_acceptance_rate: float
    citation_validity: float
    evidence_access_validity: float
    wrong_version_exposure: float
    cases: tuple[ConditionCaseResult, ...]


def _reference_matches(evidence: PolicyEvidence, reference: PolicyReference) -> bool:
    return (
        evidence.document_id == reference.document_id
        and evidence.document_version == reference.document_version
        and evidence.section == reference.section
    )


def _visible(evidence: PolicyEvidence, audience: PolicyAudience) -> bool:
    return audience != "customer" or evidence.visibility == "public"


def _evidence_access_valid(
    evidence: Sequence[PolicyEvidence], audience: PolicyAudience
) -> bool:
    return all(
        item.status == "published"
        and bool(item.release_id)
        and bool(item.document_version)
        and bool(item.section)
        and _visible(item, audience)
        for item in evidence
    )


def _wrong_version_exposed(
    evidence: Sequence[PolicyEvidence], case: ConditionLevelCase
) -> bool:
    return any(
        item.document_id in case.forbidden_document_ids
        or (item.document_id, item.document_version) in case.forbidden_versions
        for item in evidence
    )


def _condition_state(
    condition: ConditionExpectation,
    evidence: Sequence[PolicyEvidence],
    order_context: AuthorizedOrderContext,
) -> ConditionState:
    if condition.source == "order":
        if not order_context.authorized or condition.fact_key is None:
            return "unknown"
        observed = order_context.fact(condition.fact_key)
        if observed is None or condition.fact_value is None:
            return "unknown"
        return "satisfied" if observed == condition.fact_value else "contradicted"

    if not evidence:
        return "unknown"
    text = " ".join(item.text for item in evidence).casefold()
    if any(phrase.casefold() in text for phrase in condition.contradiction_phrases):
        return "contradicted"
    if all(phrase.casefold() in text for phrase in condition.evidence_phrases):
        return "satisfied"
    return "unknown"


def _condition_statuses(
    case: ConditionLevelCase, evidence: Sequence[PolicyEvidence]
) -> tuple[ConditionStatus, ...]:
    return tuple(
        ConditionStatus(
            name=condition.name,
            source=condition.source,
            expected_state=condition.expected_state,
            observed_state=_condition_state(condition, evidence, case.order_context),
        )
        for condition in case.required_conditions
    )


def validate_condition_case_labels(
    cases: Sequence[ConditionLevelCase],
    *,
    corpus: Sequence[PolicyRecord] = POLICY_CORPUS,
) -> tuple[str, ...]:
    """Return label errors before a case is allowed into an evaluation run."""

    errors: list[str] = []
    records = {
        (record.document_id, record.document_version, record.section): record
        for record in corpus
    }
    for case in cases:
        if not case.query.strip():
            errors.append(f"{case.label}: query is empty")
        if not case.required_abstention and not case.expect_supported_answer:
            errors.append(f"{case.label}: unsupported case must require abstention")
        if case.expect_supported_answer and case.expected_policy is None:
            errors.append(f"{case.label}: supported case has no expected policy")
        record = (
            records.get(
                (
                    case.expected_policy.document_id,
                    case.expected_policy.document_version,
                    case.expected_policy.section,
                )
            )
            if case.expected_policy is not None
            else None
        )
        if case.expect_supported_answer and record is None:
            errors.append(f"{case.label}: expected policy is absent from corpus")
        if case.expect_supported_answer and record is not None:
            if record.status != "published":
                errors.append(f"{case.label}: expected policy is not published")
            if case.audience == "customer" and record.visibility != "public":
                errors.append(f"{case.label}: customer expected policy is not public")
            if not (record.answer_text or record.text):
                errors.append(f"{case.label}: expected policy has no answer text")
        if case.expected_policy is not None and any(
            forbidden_id == case.expected_policy.document_id
            for forbidden_id in case.forbidden_document_ids
        ):
            errors.append(f"{case.label}: expected policy is forbidden")
        if not case.valid_citation_ids:
            errors.append(f"{case.label}: no valid citation IDs declared")
        if not case.order_context.actor_id or not case.order_context.order_id:
            errors.append(f"{case.label}: incomplete order context identity")
        for condition in case.required_conditions:
            if condition.source == "policy":
                if condition.fact_key is not None or condition.fact_value is not None:
                    errors.append(f"{case.label}/{condition.name}: policy fact fields set")
                if condition.expected_state == "satisfied" and record is not None:
                    text = record.text.casefold()
                    if not all(
                        phrase.casefold() in text
                        for phrase in condition.evidence_phrases
                    ):
                        errors.append(
                            f"{case.label}/{condition.name}: evidence phrases absent"
                        )
            elif condition.fact_key is None or condition.fact_value is None:
                errors.append(f"{case.label}/{condition.name}: order fact is incomplete")
    return tuple(errors)


def evaluate_condition_cases(
    cases: Sequence[ConditionLevelCase],
    *,
    corpus: Sequence[PolicyRecord] = POLICY_CORPUS,
    policy_retriever: PolicyRetriever | None = None,
) -> ConditionLevelReport:
    """Evaluate retrieval, condition establishment, answer support, and safety."""

    label_errors = validate_condition_case_labels(cases, corpus=corpus)
    if label_errors:
        raise ValueError("invalid condition labels: " + "; ".join(label_errors))
    if not cases:
        raise ValueError("at least one condition case is required")

    results: list[ConditionCaseResult] = []
    supported_total = 0
    retrieved_count = 0
    accepted_count = 0
    complete_count = 0
    supported_valid_count = 0
    unsupported_total = 0
    unsupported_safe_count = 0
    unsupported_false_accepts = 0
    citation_valid_count = 0
    evidence_access_count = 0
    version_sensitive_count = 0
    wrong_version_count = 0

    for case in cases:
        if policy_retriever is None:
            retrieved = retrieve_published_policy(
                case.query, audience=case.audience, top_k=3, corpus=corpus
            )
            evidence_accepted = is_sufficient_policy_match(case.query, retrieved)
        else:
            retrieved = list(
                policy_retriever.retrieve_published_policy(
                    case.query, audience=case.audience, top_k=3
                )
            )
            evidence_accepted = is_sufficient_semantic_match(retrieved)

        policy_retrieved = case.expected_policy is not None and any(
            _reference_matches(item, case.expected_policy) for item in retrieved
        )
        relevant_evidence_retrieved = (
            case.expected_policy is not None
            and policy_retrieved
            and any(
                bool(item.text.strip())
                and _reference_matches(item, case.expected_policy)
                for item in retrieved
            )
        )
        statuses = _condition_statuses(case, retrieved)
        satisfied = tuple(
            item.name for item in statuses if item.observed_state == "satisfied"
        )
        contradicted = tuple(
            item.name for item in statuses if item.observed_state == "contradicted"
        )
        unknown = tuple(
            item.name for item in statuses if item.observed_state == "unknown"
        )
        access_valid = _evidence_access_valid(retrieved, case.audience)
        wrong_version = _wrong_version_exposed(retrieved, case)
        if case.forbidden_document_ids or case.forbidden_versions:
            version_sensitive_count += 1
            wrong_version_count += int(wrong_version)

        answer = answer_from_published_policy(
            case.query,
            audience=case.audience,
            corpus=corpus,
            policy_retriever=policy_retriever,
        )
        citation_valid = (
            not answer.evidence
            if not case.expect_supported_answer
            else bool(answer.evidence)
            and bool(answer.citation_ids)
            and set(answer.citation_ids).issubset(case.valid_citation_ids)
            and access_valid
        )
        expected_conditions_satisfied = all(
            item.observed_state == item.expected_state == "satisfied"
            for item in statuses
        )
        permitted_answer_valid = (
            case.permitted_supported_answer is None
            or (
                answer.answer is not None
                and case.permitted_supported_answer.casefold()
                in answer.answer.casefold()
            )
        )
        answer_fully_supported = (
            case.expect_supported_answer
            and answer.grounded
            and answer.answer is not None
            and not answer.needs_handoff
            and evidence_accepted
            and policy_retrieved
            and expected_conditions_satisfied
            and permitted_answer_valid
            and citation_valid
            and access_valid
            and not wrong_version
        )
        answer_contradictory = bool(contradicted) or wrong_version
        answer_incomplete = bool(answer.answer) and not answer_fully_supported
        unsafe = (
            bool(answer.evidence) and not access_valid
        ) or wrong_version or (
            not case.order_context.authorized and bool(answer.answer)
        )
        safe_abstention = (
            case.required_abstention
            and answer.answer is None
            and not answer.grounded
            and answer.needs_handoff
            and not answer.evidence
            and not unsafe
        )

        supported_total += int(case.expect_supported_answer)
        retrieved_count += int(case.expect_supported_answer and policy_retrieved)
        accepted_count += int(case.expect_supported_answer and evidence_accepted)
        complete_count += int(
            case.expect_supported_answer and expected_conditions_satisfied
        )
        supported_valid_count += int(answer_fully_supported)
        if not case.expect_supported_answer:
            unsupported_total += 1
            unsupported_safe_count += int(safe_abstention)
            unsupported_false_accepts += int(
                bool(answer.answer) or answer.grounded or bool(answer.evidence)
            )
        citation_valid_count += int(citation_valid)
        evidence_access_count += int(access_valid)

        results.append(
            ConditionCaseResult(
                label=case.label,
                policy_retrieved=policy_retrieved,
                relevant_evidence_retrieved=relevant_evidence_retrieved,
                evidence_accepted=evidence_accepted,
                condition_statuses=statuses,
                conditions_satisfied=satisfied,
                conditions_contradicted=contradicted,
                conditions_unknown=unknown,
                answer_fully_supported=answer_fully_supported,
                answer_incomplete=answer_incomplete,
                answer_contradictory=answer_contradictory,
                unsafe_information_or_action_attempted=unsafe,
                safe_abstention=safe_abstention,
                citation_valid=citation_valid,
                evidence_access_valid=access_valid,
                wrong_version_exposed=wrong_version,
            )
        )

    return ConditionLevelReport(
        query_count=len(cases),
        supported_case_count=supported_total,
        policy_retrieval_recall_at_3=retrieved_count / supported_total
        if supported_total
        else 0.0,
        evidence_acceptance_rate=accepted_count / supported_total
        if supported_total
        else 0.0,
        condition_completeness=complete_count / supported_total
        if supported_total
        else 0.0,
        supported_answer_accuracy=supported_valid_count / supported_total
        if supported_total
        else 0.0,
        unsupported_safety=unsupported_safe_count / unsupported_total
        if unsupported_total
        else 0.0,
        unsupported_false_acceptance_rate=unsupported_false_accepts / unsupported_total
        if unsupported_total
        else 0.0,
        citation_validity=citation_valid_count / len(cases),
        evidence_access_validity=evidence_access_count / len(cases),
        wrong_version_exposure=wrong_version_count / version_sensitive_count
        if version_sensitive_count
        else 0.0,
        cases=tuple(results),
    )


def _context(*facts: tuple[str, str], authorized: bool = True) -> AuthorizedOrderContext:
    return AuthorizedOrderContext(
        actor_id="customer_001",
        order_id="commerce_order_demo_001",
        authorized=authorized,
        facts=facts,
    )


def _policy(
    name: str,
    *phrases: str,
    expected_state: ConditionState = "satisfied",
) -> ConditionExpectation:
    return ConditionExpectation(
        name=name,
        source="policy",
        expected_state=expected_state,
        evidence_phrases=phrases,
    )


def _order(
    name: str,
    key: str,
    value: str,
    *,
    expected_state: ConditionState = "satisfied",
) -> ConditionExpectation:
    return ConditionExpectation(
        name=name,
        source="order",
        expected_state=expected_state,
        fact_key=key,
        fact_value=value,
    )


def _case(
    label: str,
    query: str,
    category: str,
    policy: tuple[str, str, str] | None,
    conditions: ConditionExpectation | tuple[ConditionExpectation, ...],
    *,
    facts: tuple[tuple[str, str], ...] = (),
    supported: bool = True,
    forbidden_documents: tuple[str, ...] = (),
    forbidden_versions: tuple[tuple[str, str], ...] = (),
    authorized: bool = True,
) -> ConditionLevelCase:
    normalized_conditions = (
        (conditions,) if isinstance(conditions, ConditionExpectation) else conditions
    )
    reference = PolicyReference(
        document_id=policy[0], document_version=policy[1], section=policy[2]
    ) if policy else None
    answer = None
    if reference:
        record = next(
            item
            for item in POLICY_CORPUS
            if (
                item.document_id == reference.document_id
                and item.document_version == reference.document_version
                and item.section == reference.section
            )
        )
        answer = record.answer_text or record.text
    return ConditionLevelCase(
        label=label,
        query=query,
        issue_category=category,
        audience="customer",
        order_context=_context(*facts, authorized=authorized),
        expected_policy=reference,
        required_conditions=normalized_conditions,
        expect_supported_answer=supported,
        required_abstention=not supported,
        permitted_supported_answer=answer if supported else None,
        forbidden_document_ids=forbidden_documents,
        forbidden_versions=forbidden_versions,
    )


CONDITION_LEVEL_DEVELOPMENT_CASES: tuple[ConditionLevelCase, ...] = (
    _case("shipping_acceptance", "When does delivery timing begin?", "shipping_estimate", ("shipping-policy", "v1", "Shipping estimates"), (_policy("carrier_acceptance", "carrier acceptance"), _policy("estimate_not_guarantee", "delivery dates are estimates"))),
    _case("shipping_checkout", "Are the delivery dates guaranteed?", "shipping_estimate", ("shipping-policy", "v1", "Shipping estimates"), (_policy("checkout_estimate", "shown at checkout"), _policy("not_guaranteed", "not guarantees"))),
    _case("delay_updated_estimate", "My shipment is delayed; can support update the estimate?", "delivery_delay", ("delivery-policy", "v2", "Delayed shipments"), (_policy("delay_contact", "shipment is delayed", "contact support"), _policy("updated_estimate", "updated estimate"))),
    _case("delay_contact", "Where do I ask about a late shipment?", "delivery_delay", ("delivery-policy", "v2", "Delayed shipments"), (_policy("delay_contact", "shipment is delayed", "contact support"))),
    _case("followup_no_movement", "How long without carrier movement before investigation?", "delivery_followup", ("delivery-policy", "v2", "Late delivery follow-up"), (_policy("movement_window", "carrier movement stops for three business days"), _policy("investigation", "delivery investigation"))),
    _case("followup_compensation", "Does a delivery investigation guarantee compensation?", "delivery_followup", ("delivery-policy", "v2", "Late delivery follow-up"), (_policy("compensation", "compensation is not guaranteed"))),
    _case("missing_scan", "Tracking says delivered but the package is missing.", "missing_package", ("missing-package-policy", "v1", "Missing packages"), (_policy("delivery_scan", "tracking shows delivered", "delivery scan"), _policy("report_window", "within seven calendar days"))),
    _case("missing_secure_locations", "What should I check before reporting a missing delivery?", "missing_package", ("missing-package-policy", "v1", "Missing packages"), (_policy("check_locations", "secure locations and household members"), _policy("no_compensation", "automatic compensation decision"))),
    _case("not_received_trace", "The carrier marked it delivered but I cannot locate it.", "delivered_not_received", ("missing-package-policy", "v1", "Delivered but not received"), (_policy("carrier_trace", "carrier trace"), _policy("retain_evidence", "should not discard packaging or delivery evidence"))),
    _case("not_received_report", "Should I keep evidence for a delivered package I never received?", "delivered_not_received", ("missing-package-policy", "v1", "Delivered but not received"), (_policy("report_problem", "report the problem within seven days"), _policy("delivery_evidence", "delivery evidence"))),
    _case("damage_photos", "My item arrived damaged; what should I keep?", "damaged_item", ("product-damage-policy", "v1", "Damaged items"), (_policy("keep_packaging", "keep the item and packaging"), _policy("photos", "with photos"))),
    _case("damage_deadline", "How soon must I report a damaged product?", "damaged_item", ("product-damage-policy", "v1", "Damaged items"), (_policy("damage_window", "within 14 calendar days"), _policy("support_review", "contact support"))),
    _case("wrong_item_keep", "I received the wrong item. What do I do with it?", "wrong_item", ("fulfillment-policy", "v1", "Wrong items"), (_policy("keep_wrong_item", "keep it"), _policy("wrong_order_details", "order details"))),
    _case("wrong_item_return", "Can I send the wrong item back without instructions?", "wrong_item", ("fulfillment-policy", "v1", "Wrong items"), (_policy("authorized_return", "authorized return"), _policy("no_uninstructed_return", "do not ship it back without instructions"))),
    _case("partial_delivery", "Why did my order arrive in separate deliveries?", "partial_delivery", ("fulfillment-policy", "v1", "Partial order deliveries"), (_policy("separate_deliveries", "separate deliveries"), _policy("missing_expected", "expected item is missing"))),
    _case("partial_credit", "Does a split delivery automatically approve a credit?", "partial_delivery", ("fulfillment-policy", "v1", "Partial order deliveries"), (_policy("credit_not_automatic", "not by itself a credit approval"), _policy("order_lines", "original order lines"))),
    _case("cancel_before_carrier", "Can I cancel before the carrier fulfills the order?", "cancellation", ("order-cancellation-policy", "v1", "Order cancellations"), (_policy("before_fulfillment", "before an order enters carrier fulfillment"), _policy("not_guaranteed", "cancellation is not guaranteed"))),
    _case("cancel_after_acceptance", "Can cancellation be promised after carrier acceptance?", "cancellation", ("order-cancellation-policy", "v1", "Order cancellations"), (_policy("after_acceptance", "cannot be promised after the carrier has accepted the order"),)),
    _case("return_window", "What is the return deadline after delivery?", "return", ("returns-policy", "v1", "Return window"), (_policy("return_deadline", "within 30 calendar days after delivery"), _policy("unused_item", "Items must be unused"),)),
    _case("return_packaging", "Can an unused item with its packaging be returned?", "return", ("returns-policy", "v1", "Return window"), (_policy("unused_item", "Items must be unused"), _policy("packaging", "original packaging"),)),
    _case("refund_damage", "When may a credit be considered for verified damage?", "refund_eligibility", ("refund-eligibility-policy", "v1", "Refund eligibility"), (_policy("damaged_item", "verified damaged item"), _policy("verify_evidence", "verify the order and evidence"))),
    _case("refund_fulfillment", "Can a confirmed fulfillment error qualify for a refund?", "refund_eligibility", ("refund-eligibility-policy", "v1", "Refund eligibility"), (_policy("fulfillment_error", "confirmed fulfillment error"), _policy("not_guaranteed", "not a guarantee of payment"))),
    _case("processing_start", "When does return credit processing begin?", "refund_processing", ("refund-processing-policy", "v1", "Return credit processing"), (_policy("received_reviewed", "eligible return is received and reviewed"), _policy("processing_begins", "processing begins"))),
    _case("processing_posting", "Can bank posting times vary after a return credit?", "refund_processing", ("refund-processing-policy", "v1", "Return credit processing"), (_policy("bank_variance", "bank posting times may vary"), _policy("status", "confirm the current processing status"))),
    _case("warranty_duration", "How long is the limited product warranty?", "warranty", ("warranty-policy", "v1", "Product warranty coverage"), (_policy("warranty_term", "12-month limited warranty"), _policy("normal_use", "normal intended use"))),
    _case("warranty_exclusions", "Does accidental damage qualify for warranty coverage?", "warranty", ("warranty-policy", "v1", "Product warranty coverage"), (_policy("accidental_exclusion", "Accidental damage", "excluded"), _policy("misuse_exclusion", "misuse", "excluded"))),
    _case("human_insufficient", "Who can help when policy evidence is insufficient?", "human_support", ("human-support-policy", "v1", "Human support escalation"), (_policy("insufficient_evidence", "policy evidence are insufficient"), _policy("human_support", "Contact human support"))),
    _case("human_tracking", "What if the order tracking details are not enough?", "human_support", ("human-support-policy", "v1", "Human support escalation"), (_policy("tracking_insufficient", "tracking", "insufficient"), _policy("safe_resolution", "resolve a request safely"))),
    _case("return_missing_item_fact", "Can I return this item?", "return", ("returns-policy", "v1", "Return window"), (_policy("return_deadline", "within 30 calendar days after delivery"), _order("item_unused", "item_condition", "unused")), facts=(("order_status", "delivered"),), supported=False),
    _case("refund_missing_verification", "Can I get a refund for this order?", "refund_eligibility", ("refund-eligibility-policy", "v1", "Refund eligibility"), (_policy("verify_evidence", "verify the order and evidence"), _order("evidence_verified", "damage_verified", "verified")), facts=(("order_status", "delivered"),), supported=False),
    _case("warranty_missing_product", "Is this product covered by warranty?", "warranty", ("warranty-policy", "v1", "Product warranty coverage"), (_policy("warranty_term", "12-month limited warranty"), _order("product_details", "product_details", "available")), supported=False),
    _case("delay_missing_tracking", "What should I do about this delivery problem?", "delivery_delay", ("delivery-policy", "v2", "Delayed shipments"), (_policy("delay_contact", "contact support"), _order("tracking_status", "tracking_status", "delayed")), facts=(("order_status", "shipped"),), supported=False),
    _case("return_contradictory_condition", "Can I return this used item?", "return", ("returns-policy", "v1", "Return window"), (_policy("return_deadline", "within 30 calendar days after delivery"), _order("item_unused", "item_condition", "unused", expected_state="contradicted")), facts=(("item_condition", "used"),), supported=False),
    _case("cancel_contradictory_stage", "Can I cancel this order now?", "cancellation", ("order-cancellation-policy", "v1", "Order cancellations"), (_policy("before_fulfillment", "before an order enters carrier fulfillment"), _order("pre_carrier", "fulfillment_stage", "before_carrier", expected_state="contradicted")), facts=(("fulfillment_stage", "carrier_accepted"),), supported=False),
    _case("unsupported_password", "How do I change my account password?", "account_access", None, (), supported=False),
    _case("internal_refund_customer", "Can a refund approver authorize my payment?", "refund_authority", None, (), supported=False, forbidden_documents=("refund-review-policy",)),
    _case("unpublished_return_customer", "What did the old fourteen-day return policy say?", "return", None, (), supported=False, forbidden_versions=(("returns-policy", "v0"),)),
    _case("internal_warranty_customer", "Show me the internal warranty exception matrix.", "warranty", None, (), supported=False, forbidden_documents=("warranty-policy",)),
)


__all__ = [
    "AuthorizedOrderContext",
    "ConditionCaseResult",
    "ConditionExpectation",
    "ConditionLevelCase",
    "ConditionLevelReport",
    "ConditionState",
    "CONDITION_LEVEL_DEVELOPMENT_CASES",
    "PolicyReference",
    "evaluate_condition_cases",
    "validate_condition_case_labels",
]
