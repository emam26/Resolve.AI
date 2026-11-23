from backend.app.ai import answer_from_published_policy
from backend.app.rag.corpus import POLICY_CORPUS
from backend.app.rag.models import PolicyEvidence, PolicyRecord
from backend.app.rag.semantic import InMemorySemanticRetriever


class RecordingPolicyRetriever:
    def __init__(self, evidence: list[PolicyEvidence]) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, str, int]] = []

    def retrieve_published_policy(
        self, query: str, audience: str = "customer", top_k: int = 3
    ) -> list[PolicyEvidence]:
        self.calls.append((query, audience, top_k))
        return self.evidence


class FailingPolicyRetriever:
    def retrieve_published_policy(
        self, query: str, audience: str = "customer", top_k: int = 3
    ) -> list[PolicyEvidence]:
        raise RuntimeError("semantic backend unavailable")


class LeakyPolicyRetriever:
    def retrieve_published_policy(
        self, query: str, audience: str = "customer", top_k: int = 3
    ) -> list[PolicyEvidence]:
        return [
            PolicyEvidence(
                document_id="delivery-policy",
                document_version="v1",
                section="Delayed shipments",
                release_id="release_2026_09_15",
                visibility="public",
                score=0.99,
                text=(
                    "If a shipment is delayed, customers should wait three "
                    "business days before contacting support."
                ),
                status="unpublished",
            )
        ]


class FixedCorpusEmbeddingProvider:
    """Map the frozen synthetic corpus and queries to deterministic unit axes."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            axis = (
                3
                if "approver" in lowered or "authorization" in lowered
                else 1
                if "refund" in lowered
                else 2
                if "return" in lowered
                else 0
            )
            vector = [0.0] * 384
            vector[axis] = 1.0
            vectors.append(vector)
        return vectors


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


def test_operational_answers_preserve_material_policy_conditions() -> None:
    expectations = {
        ("delivery-policy", "Late delivery follow-up"): (
            "three business days",
            "not guaranteed",
        ),
        ("missing-package-policy", "Missing packages"): (
            "within seven days",
            "does not guarantee compensation",
        ),
        ("product-damage-policy", "Damaged items"): (
            "within 14 days",
            "do not discard",
        ),
        ("fulfillment-policy", "Wrong items"): (
            "within 14 days",
            "do not ship it back",
        ),
        ("fulfillment-policy", "Partial order deliveries"): (
            "order lines",
            "not credit approval",
        ),
        ("order-cancellation-policy", "Order cancellations"): (
            "before carrier fulfillment",
            "not guaranteed",
        ),
        ("returns-policy", "Return window"): (
            "30 days",
            "support must confirm eligibility",
        ),
        ("refund-processing-policy", "Return credit processing"): (
            "ineligible request",
        ),
        ("warranty-policy", "Product warranty coverage"): (
            "12-month",
            "repair",
        ),
    }

    for (document_id, section), fragments in expectations.items():
        record = next(
            item
            for item in POLICY_CORPUS
            if item.document_id == document_id and item.section == section
        )
        response = answer_from_published_policy(section, corpus=(record,))
        assert response.grounded is True
        assert response.answer is not None
        lowered = response.answer.casefold()
        assert all(fragment in lowered for fragment in fragments)


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


def test_injected_policy_retriever_supplies_grounded_answer_and_receives_context() -> None:
    semantic_record = PolicyRecord(
        document_id="semantic-delivery",
        document_version="v3",
        section="Delivery exceptions",
        release_id="release_semantic_test",
        status="published",
        visibility="public",
        text="Semantic policy evidence says to contact support for an update.",
        answer_text="Semantic policy evidence says to contact support for an update.",
    )
    retriever = RecordingPolicyRetriever(
        [
            PolicyEvidence(
                document_id="semantic-delivery",
                document_version="v3",
                section="Delivery exceptions",
                release_id="release_semantic_test",
                visibility="public",
                score=0.91,
                text="Semantic policy evidence says to contact support for an update.",
            )
        ]
    )

    response = answer_from_published_policy(
        "late parcel estimate",
        audience="customer",
        top_k=1,
        corpus=(semantic_record,),
        policy_retriever=retriever,
    )

    assert response.answer == (
        "Semantic policy evidence says to contact support for an update."
    )
    assert response.grounded is True
    assert response.needs_handoff is False
    assert retriever.calls == [("late parcel estimate", "customer", 1)]


def test_injected_policy_retriever_failure_falls_back_to_lexical_baseline() -> None:
    response = answer_from_published_policy(
        "shipment delayed",
        policy_retriever=FailingPolicyRetriever(),
    )

    assert response.answer == (
        "If a shipment is delayed, contact support for an updated estimate."
    )
    assert response.evidence[0].document_version == "v2"
    assert response.grounded is True


def test_low_score_candidate_needs_explicit_applicability_proof() -> None:
    evidence = PolicyEvidence(
        document_id="returns-policy",
        document_version="v1",
        section="Return window",
        release_id="release_2026_11_01",
        visibility="public",
        score=0.54,
        text=(
            "A return request must be submitted within 30 calendar days after "
            "delivery. Items must be unused, with tags and original packaging."
        ),
    )

    class CandidateRetriever:
        def retrieve_published_policy(
            self, query: str, audience: str = "customer", top_k: int = 3
        ) -> list[PolicyEvidence]:
            del query, audience, top_k
            return []

        def retrieve_published_policy_candidates(
            self, query: str, audience: str = "customer", top_k: int = 3
        ) -> list[PolicyEvidence]:
            del audience, top_k
            del query
            return [evidence]

    retriever = CandidateRetriever()
    supported = answer_from_published_policy(
        "return 30 days unused",
        policy_retriever=retriever,
    )
    unsupported = answer_from_published_policy(
        "I need money back",
        policy_retriever=retriever,
    )

    assert supported.grounded is True
    assert supported.evidence[0].score == 0.54
    assert unsupported.grounded is False
    assert unsupported.answer is None
    assert unsupported.evidence == []


def test_low_score_candidates_cannot_bypass_publication_or_audience_filters() -> None:
    def evidence(*, visibility: str, status: str) -> PolicyEvidence:
        return PolicyEvidence(
            document_id="returns-policy",
            document_version="v1",
            section="Return window",
            release_id="release_2026_11_01",
            visibility=visibility,
            score=0.54,
            text=(
                "A return request must be submitted within 30 calendar days. "
                "Items must be unused with original packaging."
            ),
            status=status,
        )

    class LeakyCandidateRetriever:
        def retrieve_published_policy(
            self, query: str, audience: str = "customer", top_k: int = 3
        ) -> list[PolicyEvidence]:
            del query, audience, top_k
            return []

        def retrieve_published_policy_candidates(
            self, query: str, audience: str = "customer", top_k: int = 3
        ) -> list[PolicyEvidence]:
            del query, audience, top_k
            return [
                evidence(visibility="internal", status="published"),
                evidence(visibility="public", status="unpublished"),
            ]

    response = answer_from_published_policy(
        "return 30 days unused",
        policy_retriever=LeakyCandidateRetriever(),
    )

    assert response.grounded is False
    assert response.answer is None
    assert response.evidence == []
    assert response.needs_handoff is True


def test_answer_boundary_rejects_unpublished_injected_evidence() -> None:
    response = answer_from_published_policy(
        "shipment delayed",
        policy_retriever=LeakyPolicyRetriever(),
    )

    assert response.answer is None
    assert response.evidence == []
    assert response.needs_handoff is True


def test_injected_semantic_retriever_keeps_published_and_audience_filters() -> None:
    retriever = InMemorySemanticRetriever(
        POLICY_CORPUS,
        FixedCorpusEmbeddingProvider(),
    )

    customer_delivery = answer_from_published_policy(
        "shipment delayed",
        audience="customer",
        policy_retriever=retriever,
    )
    customer_refund = answer_from_published_policy(
        "refund review authorization",
        audience="customer",
        policy_retriever=retriever,
    )
    staff_refund = answer_from_published_policy(
        "refund review authorization",
        audience="support_agent",
        policy_retriever=retriever,
    )

    assert customer_delivery.grounded is True
    assert customer_delivery.evidence[0].document_version == "v2"
    assert customer_delivery.evidence[0].visibility == "public"
    assert customer_refund.answer is None
    assert customer_refund.evidence == []
    assert customer_refund.needs_handoff is True
    assert staff_refund.grounded is True
    assert staff_refund.evidence[0].document_id == "refund-review-policy"
    assert staff_refund.evidence[0].visibility == "internal"
