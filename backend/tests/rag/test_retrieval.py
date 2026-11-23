from dataclasses import replace

from backend.app.rag import (
    DEFAULT_EVALUATION_CASES,
    EvaluationCase,
    PolicyEvidence,
    evaluate_raw_semantic_ranking,
    evaluate_policy_retrieval,
    retrieve_published_policy,
)
from backend.app.rag.evaluation import evaluate_answer_contract
from backend.app.rag.corpus import POLICY_CORPUS
from backend.app.rag.evaluation import (
    DEVELOPMENT_EVALUATION_CASES,
    DEVELOPMENT_EVALUATION_SET_VERSION,
    FRESH_DEVELOPMENT_EVALUATION_CASES,
    FRESH_DEVELOPMENT_EVALUATION_SET_VERSION,
    M11A_EVALUATION_CASES,
    validate_evaluation_case_labels,
)
from backend.app.rag.benchmark import CHALLENGING_BENCHMARK_CASES


def test_corpus_contains_required_version_and_visibility_cases() -> None:
    identifiers = {
        (record.document_id, record.document_version, record.status, record.visibility)
        for record in POLICY_CORPUS
    }

    assert ("shipping-policy", "v1", "published", "public") in identifiers
    assert ("delivery-policy", "v2", "published", "public") in identifiers
    assert ("delivery-policy", "v1", "unpublished", "public") in identifiers
    assert ("missing-package-policy", "v1", "published", "public") in identifiers
    assert ("product-damage-policy", "v1", "published", "public") in identifiers
    assert ("fulfillment-policy", "v1", "published", "public") in identifiers
    assert ("order-cancellation-policy", "v1", "published", "public") in identifiers
    assert ("returns-policy", "v1", "published", "public") in identifiers
    assert ("returns-policy", "v0", "unpublished", "public") in identifiers
    assert ("refund-eligibility-policy", "v1", "published", "public") in identifiers
    assert ("refund-processing-policy", "v1", "published", "public") in identifiers
    assert ("warranty-policy", "v1", "published", "public") in identifiers
    assert ("warranty-policy", "v1", "published", "internal") in identifiers
    assert ("human-support-policy", "v1", "published", "public") in identifiers
    assert ("refund-review-policy", "v1", "published", "internal") in identifiers


def test_customer_retrieval_returns_published_public_v2_with_contract_fields() -> None:
    results = retrieve_published_policy("shipment delayed", top_k=1)

    assert len(results) == 1
    assert results[0].model_dump(mode="json") == {
        "document_id": "delivery-policy",
        "document_version": "v2",
        "section": "Delayed shipments",
        "release_id": "release_2026_11_01",
        "visibility": "public",
        "score": 2.0,
        "text": (
            "If a shipment is delayed, customers may contact support for an "
            "updated estimate."
        ),
    }


def test_customer_cannot_receive_unpublished_or_internal_evidence() -> None:
    old_version_query = retrieve_published_policy(
        "shipment delayed contact support", audience="customer", top_k=3
    )
    internal_query = retrieve_published_policy(
        "approver authorization", audience="customer", top_k=3
    )

    assert all(
        not (
            result.document_id == "delivery-policy"
            and result.document_version == "v1"
        )
        for result in old_version_query
    )
    assert all(result.document_id != "refund-review-policy" for result in internal_query)
    assert internal_query == []


def test_customer_retrieval_covers_warranty_and_return_eligibility() -> None:
    warranty = retrieve_published_policy(
        "warranty accidental damage", audience="customer", top_k=1
    )
    returns = retrieve_published_policy(
        "return unused packaging 30 days", audience="customer", top_k=1
    )

    assert (warranty[0].document_id, warranty[0].section) == (
        "warranty-policy",
        "Product warranty coverage",
    )
    assert (returns[0].document_id, returns[0].document_version, returns[0].section) == (
        "returns-policy",
        "v1",
        "Return window",
    )


def test_staff_can_retrieve_published_internal_policy() -> None:
    results = retrieve_published_policy(
        "refund review approver authorization", audience="support_agent"
    )

    assert results[0].document_id == "refund-review-policy"
    assert results[0].visibility == "internal"


def test_retrieval_is_stable_and_validates_top_k() -> None:
    first = retrieve_published_policy("shipment delayed", top_k=3)
    second = retrieve_published_policy("shipment delayed", top_k=3)

    assert first == second
    try:
        retrieve_published_policy("shipment delayed", top_k=0)
    except ValueError as error:
        assert str(error) == "top_k must be positive"
    else:
        raise AssertionError("top_k=0 must be rejected")


def test_predeclared_evaluation_set_is_perfect_on_offline_corpus() -> None:
    labels = [case.label for case in DEFAULT_EVALUATION_CASES]
    report = evaluate_policy_retrieval()

    assert labels == [
        "published_public_delivery_v2",
        "older_delivery_version_filtered",
        "internal_policy_hidden_from_customer",
        "published_internal_policy_for_staff",
        "unknown_answer",
    ]
    assert report.query_count == 5
    assert report.recall_at_3 == 1.0
    assert report.wrong_version_exposure == 0.0
    assert report.citation_visibility_accuracy == 1.0
    assert report.unsupported_answer_behavior == 1.0
    assert report.as_dict()["Recall@3"] == 1.0


def test_m11a_predeclared_operational_cases_are_safe_and_grounded() -> None:
    labels = [case.label for case in M11A_EVALUATION_CASES]
    report = evaluate_policy_retrieval(
        cases=(*DEFAULT_EVALUATION_CASES, *M11A_EVALUATION_CASES)
    )

    assert labels == [
        "published_public_shipping_estimate",
        "published_public_missing_package",
        "published_public_damaged_item",
        "published_public_wrong_item",
        "published_public_partial_delivery",
        "published_public_cancellation",
        "published_public_return_window",
        "published_public_return_credit_processing",
        "published_public_human_escalation",
        "published_public_delivered_not_received",
        "published_public_late_delivery_followup",
        "published_public_return_exceptions",
        "published_public_refund_eligibility",
        "published_public_product_warranty",
    ]
    assert report.query_count == 19
    assert report.recall_at_3 == 1.0
    assert report.wrong_version_exposure == 0.0
    assert report.citation_visibility_accuracy == 1.0
    assert report.unsupported_answer_behavior == 1.0


def test_development_set_is_versioned_valid_and_covers_required_case_types() -> None:
    labels = [case.label for case in DEVELOPMENT_EVALUATION_CASES]

    assert DEVELOPMENT_EVALUATION_SET_VERSION == "rag-development-v1"
    assert len(labels) == len(set(labels)) == 15
    assert validate_evaluation_case_labels(DEVELOPMENT_EVALUATION_CASES) == ()
    assert set(labels).isdisjoint(
        case.label for case in (*DEFAULT_EVALUATION_CASES, *M11A_EVALUATION_CASES)
    )
    assert {case.query for case in DEVELOPMENT_EVALUATION_CASES}.isdisjoint(
        case.query
        for case in (
            *DEFAULT_EVALUATION_CASES,
            *M11A_EVALUATION_CASES,
            *CHALLENGING_BENCHMARK_CASES,
        )
    )
    assert sum(label.startswith("dev_paraphrase_") for label in labels) == 3
    assert sum(label.startswith("dev_hard_negative_") for label in labels) == 3
    assert sum(label.startswith("dev_ambiguous_") for label in labels) == 2
    assert sum(label.startswith("dev_wrong_version_") for label in labels) == 2
    assert sum(label.startswith("dev_internal_customer_") for label in labels) == 2
    assert sum(label.startswith("dev_unsupported_") for label in labels) == 3
    assert sum(case.expect_supported_answer for case in DEVELOPMENT_EVALUATION_CASES) == 8
    assert sum(not case.expect_supported_answer for case in DEVELOPMENT_EVALUATION_CASES) == 7


def test_development_set_reports_explicit_per_case_retrieval_and_answer_metrics() -> None:
    retrieval_report = evaluate_policy_retrieval(cases=DEVELOPMENT_EVALUATION_CASES)
    answer_report = evaluate_answer_contract(cases=DEVELOPMENT_EVALUATION_CASES)

    labels = [case.label for case in DEVELOPMENT_EVALUATION_CASES]
    assert [case.label for case in retrieval_report.cases] == labels
    assert [case.label for case in answer_report.cases] == labels
    assert retrieval_report.query_count == answer_report.query_count == 15
    assert retrieval_report.unsupported_answer_behavior == 1.0
    assert answer_report.unsupported_answer_behavior == 1.0
    assert answer_report.unsupported_false_acceptance_rate == 0.0
    assert answer_report.evidence_access_control_accuracy == 1.0
    assert answer_report.wrong_version_exposure == 0.0
    assert all(case.retrieval_mode == "lexical" for case in answer_report.cases)
    assert all(
        isinstance(case.answer_contract_valid, bool)
        and isinstance(case.evidence_sufficient, bool)
        and isinstance(case.citation_access_control_valid, bool)
        and isinstance(case.evidence_access_control_valid, bool)
        and isinstance(case.wrong_version_exposed, bool)
        for case in answer_report.cases
    )


def test_development_labels_fail_closed_when_expected_corpus_version_changes() -> None:
    changed = replace(DEVELOPMENT_EVALUATION_CASES[0], expected_version="v9")

    errors = validate_evaluation_case_labels((changed,))

    assert errors == (
        "dev_paraphrase_delivery_estimate: expected policy is absent from corpus",
    )


def test_fresh_development_set_is_disjoint_and_label_valid() -> None:
    labels = [case.label for case in FRESH_DEVELOPMENT_EVALUATION_CASES]
    historical_cases = (
        *DEFAULT_EVALUATION_CASES,
        *M11A_EVALUATION_CASES,
        *DEVELOPMENT_EVALUATION_CASES,
        *CHALLENGING_BENCHMARK_CASES,
    )

    assert FRESH_DEVELOPMENT_EVALUATION_SET_VERSION == "rag-development-v2"
    assert len(labels) == len(set(labels)) == 16
    assert validate_evaluation_case_labels(FRESH_DEVELOPMENT_EVALUATION_CASES) == ()
    assert set(labels).isdisjoint(case.label for case in historical_cases)
    assert {case.query for case in FRESH_DEVELOPMENT_EVALUATION_CASES}.isdisjoint(
        case.query for case in historical_cases
    )
    assert sum(label.startswith("fresh_paraphrase_") for label in labels) == 3
    assert sum(label.startswith("fresh_hard_negative_") for label in labels) == 3
    assert sum(label.startswith("fresh_wrong_version_") for label in labels) == 2
    assert sum(label.startswith("fresh_staff_") for label in labels) == 1
    assert sum(label.startswith("fresh_customer_internal_") for label in labels) == 2
    assert sum(label.startswith("fresh_ambiguous_") for label in labels) == 2
    assert sum(label.startswith("fresh_unsupported_") for label in labels) == 3
    assert sum(case.expect_supported_answer for case in FRESH_DEVELOPMENT_EVALUATION_CASES) == 9
    assert sum(not case.expect_supported_answer for case in FRESH_DEVELOPMENT_EVALUATION_CASES) == 7


def test_fresh_development_metrics_keep_ranking_and_answer_contract_separate() -> None:
    retrieval_report = evaluate_policy_retrieval(cases=FRESH_DEVELOPMENT_EVALUATION_CASES)
    answer_report = evaluate_answer_contract(cases=FRESH_DEVELOPMENT_EVALUATION_CASES)

    assert retrieval_report.query_count == answer_report.query_count == 16
    assert answer_report.unsupported_answer_behavior == 1.0
    assert answer_report.unsupported_false_acceptance_rate == 0.0
    assert 0.0 <= answer_report.citation_access_control_accuracy <= 1.0
    assert answer_report.evidence_access_control_accuracy == 1.0
    assert answer_report.wrong_version_exposure == 0.0
    assert 0.0 <= retrieval_report.recall_at_3 <= 1.0
    assert 0.0 <= retrieval_report.citation_visibility_accuracy <= 1.0
    assert 0.0 <= retrieval_report.wrong_version_exposure <= 1.0
    assert 0.0 <= answer_report.supported_answer_accuracy <= 1.0
    assert retrieval_report.as_dict()["Recall@3"] == retrieval_report.recall_at_3
    assert isinstance(answer_report.supported_answer_accuracy, float)


def test_evaluation_uses_injected_retriever_for_semantic_path() -> None:
    class InjectedRetriever:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        def retrieve_published_policy(
            self, query: str, audience: str = "customer", top_k: int = 3
        ) -> list[PolicyEvidence]:
            self.calls.append((query, audience, top_k))
            if query == "supported query":
                return [
                    PolicyEvidence(
                        document_id="delivery-policy",
                        document_version="v2",
                        section="Delayed shipments",
                        release_id="release_2026_11_01",
                        visibility="public",
                        score=0.9,
                        text="grounded delivery evidence",
                    )
                ]
            return []

    retriever = InjectedRetriever()
    report = evaluate_policy_retrieval(
        cases=(
            EvaluationCase(
                label="supported",
                query="supported query",
                audience="customer",
                expected_document_id="delivery-policy",
                expected_version="v2",
                expected_section="Delayed shipments",
                expect_supported_answer=True,
            ),
            EvaluationCase(
                label="unsupported",
                query="unsupported query",
                audience="customer",
                expected_document_id=None,
                expected_version=None,
                expected_section=None,
                expect_supported_answer=False,
            ),
        ),
        policy_retriever=retriever,
    )

    assert report.recall_at_3 == 1.0
    assert report.citation_visibility_accuracy == 1.0
    assert report.unsupported_answer_behavior == 1.0
    assert retriever.calls == [
        ("supported query", "customer", 3),
        ("unsupported query", "customer", 3),
    ]


def test_raw_semantic_evaluation_keeps_ranking_separate_from_gate_acceptance() -> None:
    class RawCandidateRetriever:
        def retrieve_published_policy_candidates(
            self, query: str, audience: str = "customer", top_k: int = 3
        ) -> list[PolicyEvidence]:
            del audience, top_k
            if query == "supported query":
                return [
                    PolicyEvidence(
                        document_id="delivery-policy",
                        document_version="v2",
                        section="Delayed shipments",
                        release_id="release_2026_11_01",
                        visibility="public",
                        score=0.54,
                        text="grounded delivery evidence",
                    )
                ]
            return [
                PolicyEvidence(
                    document_id="delivery-policy",
                    document_version="v2",
                    section="Delayed shipments",
                    release_id="release_2026_11_01",
                    visibility="public",
                    score=0.40,
                    text="weak candidate",
                )
            ]

    report = evaluate_raw_semantic_ranking(
        cases=(
            EvaluationCase(
                label="supported",
                query="supported query",
                audience="customer",
                expected_document_id="delivery-policy",
                expected_version="v2",
                expected_section="Delayed shipments",
                expect_supported_answer=True,
            ),
            EvaluationCase(
                label="unsupported",
                query="unsupported query",
                audience="customer",
                expected_document_id=None,
                expected_version=None,
                expected_section=None,
                expect_supported_answer=False,
            ),
        ),
        policy_retriever=RawCandidateRetriever(),
    )

    assert report.raw_recall_at_3 == 1.0
    assert report.raw_mrr == 1.0
    assert report.supported_semantic_gate_acceptance == 0.0
    assert report.citation_access_control_accuracy == 1.0
    assert report.cases[0].expected_rank == 1
    assert report.cases[0].top_similarity_score == 0.54
    assert report.cases[0].semantic_gate_accepted is False


def test_evaluation_rejects_unpublished_and_internal_injected_evidence() -> None:
    class UnsafeRetriever:
        def retrieve_published_policy(
            self, query: str, audience: str = "customer", top_k: int = 3
        ) -> list[PolicyEvidence]:
            del audience, top_k
            if query == "unpublished":
                return [
                    PolicyEvidence(
                        document_id="delivery-policy",
                        document_version="v2",
                        section="Delayed shipments",
                        release_id="release_2026_11_01",
                        visibility="public",
                        score=0.9,
                        text="unpublished evidence",
                        status="unpublished",
                    )
                ]
            return [
                PolicyEvidence(
                    document_id="refund-review-policy",
                    document_version="v1",
                    section="Refund review",
                    release_id="release_2026_11_01",
                    visibility="internal",
                    score=0.9,
                    text="internal evidence",
                )
            ]

    report = evaluate_policy_retrieval(
        cases=(
            EvaluationCase(
                label="unpublished",
                query="unpublished",
                audience="customer",
                expected_document_id="delivery-policy",
                expected_version="v2",
                expected_section="Delayed shipments",
                expect_supported_answer=True,
            ),
            EvaluationCase(
                label="internal",
                query="internal",
                audience="customer",
                expected_document_id="refund-review-policy",
                expected_version="v1",
                expected_section="Refund review",
                expect_supported_answer=True,
            ),
        ),
        policy_retriever=UnsafeRetriever(),
    )

    assert report.recall_at_3 == 0.0
    assert report.citation_visibility_accuracy == 0.0


def test_evaluation_rejects_wrong_top_ranked_policy() -> None:
    class MisorderedRetriever:
        def retrieve_published_policy(
            self, query: str, audience: str = "customer", top_k: int = 3
        ) -> list[PolicyEvidence]:
            del query, audience, top_k
            return [
                PolicyEvidence(
                    document_id="returns-policy",
                    document_version="v1",
                    section="Return window",
                    release_id="release_2026_10_10",
                    visibility="public",
                    score=0.95,
                    text="Unused items may be returned within 30 days of delivery.",
                ),
                PolicyEvidence(
                    document_id="delivery-policy",
                    document_version="v2",
                    section="Delayed shipments",
                    release_id="release_2026_11_01",
                    visibility="public",
                    score=0.9,
                    text="grounded delivery evidence",
                ),
            ]

    report = evaluate_policy_retrieval(
        cases=(
            EvaluationCase(
                label="misordered",
                query="misordered query",
                audience="customer",
                expected_document_id="delivery-policy",
                expected_version="v2",
                expected_section="Delayed shipments",
                expect_supported_answer=True,
            ),
        ),
        policy_retriever=MisorderedRetriever(),
    )

    assert report.recall_at_3 == 1.0
    assert report.citation_visibility_accuracy == 0.0


def test_answer_contract_evaluation_measures_actual_semantic_result() -> None:
    class SupportedRetriever:
        def retrieve_published_policy(
            self, query: str, audience: str = "customer", top_k: int = 3
        ) -> list[PolicyEvidence]:
            del query, audience, top_k
            return [
                PolicyEvidence(
                    document_id="returns-policy",
                    document_version="v1",
                    section="Return window",
                    release_id="release_2026_11_01",
                    visibility="public",
                    score=0.8,
                    text="A return request must be submitted within 30 calendar days after delivery.",
                )
            ]

    case = EvaluationCase(
        label="semantic_answer_contract",
        query="return 30 days unused",
        audience="customer",
        expected_document_id="returns-policy",
        expected_version="v1",
        expected_section="Return window",
        expect_supported_answer=True,
    )

    report = evaluate_answer_contract(
        cases=(case,), policy_retriever=SupportedRetriever()
    )

    assert report.supported_answer_accuracy == 1.0
    assert report.citation_access_control_accuracy == 1.0
    assert report.cases[0].retrieval_mode == "semantic"


def test_answer_contract_reports_unsupported_false_acceptance_separately() -> None:
    class UnsafeRetriever:
        def retrieve_published_policy(
            self, query: str, audience: str = "customer", top_k: int = 3
        ) -> list[PolicyEvidence]:
            del query, audience, top_k
            return [
                PolicyEvidence(
                    document_id="returns-policy",
                    document_version="v1",
                    section="Return window",
                    release_id="release_2026_11_01",
                    visibility="public",
                    score=0.9,
                    text="A return request must be submitted within 30 calendar days after delivery.",
                )
            ]

    report = evaluate_answer_contract(
        cases=(
            EvaluationCase(
                label="unsupported",
                query="How do I change my account password?",
                audience="customer",
                expected_document_id=None,
                expected_version=None,
                expected_section=None,
                expect_supported_answer=False,
            ),
        ),
        policy_retriever=UnsafeRetriever(),
    )

    assert report.unsupported_answer_behavior == 0.0
    assert report.unsupported_false_acceptance_rate == 1.0
    assert report.citation_access_control_accuracy == 0.0
    assert report.evidence_access_control_accuracy == 1.0
    assert report.cases[0].evidence_sufficient is True
