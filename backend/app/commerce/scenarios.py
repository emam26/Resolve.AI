"""Deterministic ResolveAI operational scenarios over imported source orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


SCENARIO_CLOCK = datetime(2026, 1, 3, 12, 0, 0)
DEMO_SOURCE_USER_ID = 3398
DEMO_ACTOR_ID = "customer_001"
SCENARIO_PROVENANCE = "resolveai_generated_m11a"
SOURCE_TICKET_PROVENANCE = "ecommerce_sample_database_v2"


@dataclass(frozen=True)
class SupportScenarioBlueprint:
    """A customer/order pairing selected from the imported deterministic subset."""

    case_id: str
    source_order_id: int
    scenario_type: str
    status: str
    permitted_outcome: str
    customer_message: str
    support_message: str
    active_at_scenario_clock: bool = False
    refund_state: str | None = None


# Every order is part of ``orders.id <= 3620`` in the verified official source
# archive.  The importer checks its owner and transactional dependencies before
# inserting a scenario, rather than assuming these constants are still valid.
SUPPORT_SCENARIO_BLUEPRINTS: tuple[SupportScenarioBlueprint, ...] = (
    SupportScenarioBlueprint(
        case_id="case-delayed-delivery-001",
        source_order_id=92,
        scenario_type="delayed_delivery",
        status="HANDOFF_QUEUED",
        permitted_outcome="HUMAN_ESCALATION",
        customer_message="My shipment is taking longer than the promised delivery estimate.",
        support_message="A carrier delay is recorded; a support agent should confirm the revised estimate.",
        active_at_scenario_clock=True,
    ),
    SupportScenarioBlueprint(
        case_id="case-missing-package-001",
        source_order_id=2263,
        scenario_type="missing_package",
        status="HUMAN_ACTIVE",
        permitted_outcome="CARRIER_TRACE_OR_HUMAN_ESCALATION",
        customer_message="Tracking says delivered, but the package is missing.",
        support_message="Support should document the report and begin the carrier-trace process.",
    ),
    SupportScenarioBlueprint(
        case_id="case-delivered-not-received-001",
        source_order_id=2480,
        scenario_type="delivered_not_received",
        status="RESOLVED",
        permitted_outcome="HUMAN_ESCALATION",
        customer_message="The delivery was marked complete but I did not receive the order.",
        support_message="The support review was completed without creating a payment transaction.",
    ),
    SupportScenarioBlueprint(
        case_id="case-wrong-item-001",
        source_order_id=1062,
        scenario_type="wrong_item",
        status="RESOLVED",
        permitted_outcome="RETURN_OR_REPLACEMENT_REVIEW",
        customer_message="The item in my package does not match my order.",
        support_message="Support documented the mismatch and provided the return-or-replacement path.",
    ),
    SupportScenarioBlueprint(
        case_id="case-damaged-item-001",
        source_order_id=867,
        scenario_type="damaged_item",
        status="RESOLVED",
        permitted_outcome="REFUND_REVIEW_ONLY",
        customer_message="One of the delivered items arrived damaged.",
        support_message="Support collected the damage report for a human refund review.",
        refund_state="PENDING_REVIEW",
    ),
    SupportScenarioBlueprint(
        case_id="case-partial-shipment-001",
        source_order_id=3438,
        scenario_type="partial_shipment",
        status="HUMAN_ACTIVE",
        permitted_outcome="HUMAN_ESCALATION",
        customer_message="Only part of my order arrived.",
        support_message="Support should compare the delivered shipment with the order lines.",
    ),
    SupportScenarioBlueprint(
        case_id="case-cancellation-request-001",
        source_order_id=3301,
        scenario_type="cancellation_request",
        status="RESOLVED",
        permitted_outcome="CANCELLATION_POLICY_REVIEW",
        customer_message="Can I cancel this order now?",
        support_message="The cancellation request was evaluated against its shipment stage.",
    ),
    SupportScenarioBlueprint(
        case_id="case-return-request-001",
        source_order_id=410,
        scenario_type="return_request",
        status="HANDOFF_QUEUED",
        permitted_outcome="RETURN_POLICY_REVIEW",
        customer_message="I would like to return an unused item from this order.",
        support_message="A support agent must confirm the return conditions before action.",
    ),
    SupportScenarioBlueprint(
        case_id="case-refund-status-001",
        source_order_id=2888,
        scenario_type="refund_status",
        status="RESOLVED",
        permitted_outcome="REFUND_REVIEW_ONLY",
        customer_message="What is the status of my refund review?",
        support_message="The review is approved for external follow-up; no payment was executed here.",
        refund_state="APPROVED_EXTERNAL_ACTION_REQUIRED",
    ),
    SupportScenarioBlueprint(
        case_id="case-duplicate-refund-001",
        source_order_id=1684,
        scenario_type="duplicate_refund_request",
        status="RESOLVED",
        permitted_outcome="IDEMPOTENT_REFUND_REVIEW",
        customer_message="I submitted a refund request twice and need an update.",
        support_message="Support retained one review record and rejected duplicate creation.",
        refund_state="REJECTED",
    ),
)


__all__ = [
    "DEMO_ACTOR_ID",
    "DEMO_SOURCE_USER_ID",
    "SCENARIO_CLOCK",
    "SCENARIO_PROVENANCE",
    "SOURCE_TICKET_PROVENANCE",
    "SUPPORT_SCENARIO_BLUEPRINTS",
    "SupportScenarioBlueprint",
]
