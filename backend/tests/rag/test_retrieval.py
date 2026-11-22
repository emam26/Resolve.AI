from backend.app.rag import (
    DEFAULT_EVALUATION_CASES,
    EvaluationCase,
    PolicyEvidence,
    evaluate_policy_retrieval,
    retrieve_published_policy,
)
from backend.app.rag.corpus import POLICY_CORPUS


def test_corpus_contains_required_version_and_visibility_cases() -> None:
    identifiers = {
        (record.document_id, record.document_version, record.status, record.visibility)
        for record in POLICY_CORPUS
    }

    assert ("delivery-policy", "v2", "published", "public") in identifiers
    assert ("delivery-policy", "v1", "unpublished", "public") in identifiers
    assert ("refund-review-policy", "v1", "published", "internal") in identifiers


def test_customer_retrieval_returns_published_public_v2_with_contract_fields() -> None:
    results = retrieve_published_policy("shipment delayed")

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
        "refund review approver authorization", audience="customer", top_k=3
    )

    assert all(result.document_version != "v1" for result in old_version_query)
    assert all(result.document_id != "refund-review-policy" for result in internal_query)
    assert internal_query == []


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
