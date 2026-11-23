from __future__ import annotations

from scripts.evaluate_structured_answers import run_case
from backend.app.commerce.structured_evaluation import (
    STRUCTURED_EVALUATION_CASES,
    evaluate_structured_cases,
    validate_structured_cases,
)


def test_structured_benchmark_is_frozen_and_covers_required_categories() -> None:
    validate_structured_cases()
    assert len(STRUCTURED_EVALUATION_CASES) == 111
    assert {case.category for case in STRUCTURED_EVALUATION_CASES} == {
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
    }


def test_structured_benchmark_passes_the_finite_investigation_pipeline() -> None:
    report = evaluate_structured_cases(run_case)

    assert report.query_count == 111
    assert report.intent_accuracy == 1.0
    assert report.tool_authorization_accuracy == 1.0
    assert report.field_value_accuracy == 1.0
    assert report.final_answer_accuracy == 1.0
    assert report.missing_information_safety == 1.0
    assert report.combined_database_policy_accuracy == 1.0
    assert report.unauthorized_disclosures == 0
    assert report.unauthorized_actions == 0
    assert report.failures == ()
    assert report.latency_p95_ms >= report.latency_p50_ms
