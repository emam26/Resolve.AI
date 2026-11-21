from backend.app.rag import (
    DEFAULT_EVALUATION_CASES,
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
