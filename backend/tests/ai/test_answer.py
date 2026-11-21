from backend.app.ai import answer_from_published_policy


def test_answer_shape_and_citation_for_published_public_delivery_policy() -> None:
    response = answer_from_published_policy("shipment delayed")

    assert response.model_dump(mode="json") == {
        "answer": "If a shipment is delayed, contact support for an updated estimate.",
        "evidence": [
            {
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
        ],
        "grounded": True,
        "needs_handoff": False,
    }


def test_unknown_query_never_invents_an_answer() -> None:
    response = answer_from_published_policy("explain moon cheese logistics")

    assert response.model_dump(mode="json") == {
        "answer": None,
        "evidence": [],
        "grounded": False,
        "needs_handoff": True,
    }


def test_weak_overlap_hands_off_instead_of_grounding_an_unrelated_policy() -> None:
    response = answer_from_published_policy("How do I contact support about a refund?")

    assert response.answer is None
    assert response.evidence == []
    assert response.grounded is False
    assert response.needs_handoff is True


def test_customer_internal_query_hands_off_without_internal_citation() -> None:
    response = answer_from_published_policy(
        "refund review approver authorization", audience="customer"
    )

    assert response.answer is None
    assert response.evidence == []
    assert response.grounded is False
    assert response.needs_handoff is True


def test_staff_answer_can_cite_published_internal_policy() -> None:
    response = answer_from_published_policy(
        "refund review approver authorization", audience="support_agent"
    )

    assert response.grounded is True
    assert response.needs_handoff is False
    assert response.evidence[0].visibility == "internal"
