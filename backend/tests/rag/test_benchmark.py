from backend.app.rag.benchmark import (
    BENCHMARK_EVALUATION_CASES,
    BenchmarkMethod,
    CHALLENGING_BENCHMARK_CASES,
    evaluate_benchmark_method,
)
from backend.app.rag.models import PolicyEvidence


def test_benchmark_labels_are_frozen_and_cover_requested_challenges() -> None:
    labels = {case.label for case in CHALLENGING_BENCHMARK_CASES}

    assert len(BENCHMARK_EVALUATION_CASES) == 15
    assert len(CHALLENGING_BENCHMARK_CASES) == 10
    assert {
        "paraphrase_late_parcel",
        "vocabulary_mismatch_delivery",
        "ambiguous_late_order",
        "outdated_wait_instruction",
        "publication_restricted_delay_policy",
        "paraphrase_return_window",
        "vocabulary_mismatch_return_window",
        "irrelevant_account_question",
        "internal_refund_question",
        "unsupported_tracking_question",
    } == labels
    assert sum(case.expected_document_id is not None for case in CHALLENGING_BENCHMARK_CASES) == 7


def test_benchmark_separates_recall_from_top_ranked_answer_contract() -> None:
    case = BENCHMARK_EVALUATION_CASES[0]

    def misordered(
        query: str, audience: str, top_k: int
    ) -> list[PolicyEvidence]:
        del query, audience, top_k
        return [
            PolicyEvidence(
                document_id="returns-policy",
                document_version="v1",
                section="Return window",
                release_id="release_2026_10_10",
                visibility="public",
                score=0.9,
                text="Unused items may be returned within 30 days of delivery.",
            ),
            PolicyEvidence(
                document_id="delivery-policy",
                document_version="v2",
                section="Delayed shipments",
                release_id="release_2026_11_01",
                visibility="public",
                score=0.8,
                text="If a shipment is delayed, customers may contact support for an updated estimate.",
            ),
        ]

    report = evaluate_benchmark_method(
        BenchmarkMethod("fake", misordered), cases=(case,), latency_repeats=1
    )

    assert report.recall_at_3 == 1.0
    assert report.mrr == 0.5
    assert report.answer_contract_accuracy == 0.0


def test_benchmark_counts_empty_unsupported_results_as_safe_handoff() -> None:
    case = next(
        case
        for case in CHALLENGING_BENCHMARK_CASES
        if case.label == "irrelevant_account_question"
    )

    def empty(
        query: str, audience: str, top_k: int
    ) -> list[PolicyEvidence]:
        del query, audience, top_k
        return []

    report = evaluate_benchmark_method(
        BenchmarkMethod("fake", empty), cases=(case,), latency_repeats=1
    )

    assert report.answer_contract_accuracy == 1.0
    assert report.unsupported_answer_behavior == 1.0
