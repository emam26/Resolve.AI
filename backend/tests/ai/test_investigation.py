from __future__ import annotations

import pytest

from backend.app.ai.investigation import (
    MockInvestigationModel,
    ModelDecision,
    OrderFacts,
    run_investigation,
)
from backend.app.rag.models import PolicyEvidence


class FakeFactsTool:
    def __init__(self, facts: OrderFacts | None = None, *, error: bool = False) -> None:
        self.facts = facts
        self.error = error

    def get_order_facts(self, order_id: str) -> OrderFacts | None:
        if self.error:
            raise RuntimeError("database unavailable")
        if self.facts is None or self.facts.order_id != order_id:
            return None
        return self.facts


class FakePolicyRetriever:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, int]] = []

    def retrieve_published_policy(
        self, query: str, audience: str = "customer", top_k: int = 3
    ) -> list[PolicyEvidence]:
        if self.fail:
            raise RuntimeError("semantic backend unavailable")
        self.calls.append((query, audience, top_k))
        return [
            PolicyEvidence(
                document_id="delivery-policy",
                document_version="v2",
                section="Delayed shipments",
                release_id="release_2026_11_01",
                visibility="public",
                score=0.92,
                text=(
                    "If a shipment is delayed, customers may contact support for an "
                    "updated estimate."
                ),
            )
        ]


def test_policy_question_uses_existing_grounded_answer_and_trace() -> None:
    model = MockInvestigationModel(
        {"shipment delayed": ModelDecision(intent="policy_question")}
    )
    result = run_investigation(
        "shipment delayed",
        model=model,
        facts_tool=FakeFactsTool(),
        conversation_state="AI_ACTIVE",
    )

    assert result.outcome == "ANSWER"
    assert result.answer == (
        "If a shipment is delayed, contact support for an updated estimate."
    )
    assert result.evidence[0].document_version == "v2"
    assert result.trace == ["classify", "answer_policy"]


def test_policy_question_uses_injected_retriever_through_workflow() -> None:
    retriever = FakePolicyRetriever()
    result = run_investigation(
        "late parcel estimate",
        model=MockInvestigationModel(
            {"late parcel estimate": ModelDecision(intent="policy_question")}
        ),
        facts_tool=FakeFactsTool(),
        conversation_state="AI_ACTIVE",
        policy_retriever=retriever,
    )

    assert result.outcome == "ANSWER"
    assert result.answer == (
        "If a shipment is delayed, contact support for an updated estimate."
    )
    assert result.evidence[0].document_version == "v2"
    assert retriever.calls == [("late parcel estimate", "customer", 3)]
    assert result.trace == ["classify", "answer_policy"]


def test_policy_retriever_failure_falls_back_through_workflow() -> None:
    result = run_investigation(
        "shipment delayed",
        model=MockInvestigationModel(
            {"shipment delayed": ModelDecision(intent="policy_question")}
        ),
        facts_tool=FakeFactsTool(),
        conversation_state="AI_ACTIVE",
        policy_retriever=FakePolicyRetriever(fail=True),
    )

    assert result.outcome == "ANSWER"
    assert result.answer == (
        "If a shipment is delayed, contact support for an updated estimate."
    )
    assert result.evidence[0].document_version == "v2"


def test_order_status_uses_only_typed_verified_facts() -> None:
    model = MockInvestigationModel(
        {"where is my order": ModelDecision(intent="order_status")}
    )
    facts = OrderFacts(
        order_id="order_1001",
        status="delayed",
        shipment_status="delayed",
        estimated_delivery="2026-11-24",
    )
    result = run_investigation(
        "where is my order",
        model=model,
        facts_tool=FakeFactsTool(facts),
        conversation_state="AI_ACTIVE",
        order_id="order_1001",
    )

    assert result.outcome == "ANSWER"
    assert result.answer == (
        "Order order_1001 is delayed; shipment is delayed. "
        "Estimated delivery: 2026-11-24."
    )
    assert result.evidence == []
    assert result.trace == ["classify", "fetch_order_facts", "answer_order"]


def test_non_ai_conversation_state_blocks_model_and_tools() -> None:
    result = run_investigation(
        "shipment delayed",
        model=MockInvestigationModel(
            {"shipment delayed": ModelDecision(intent="policy_question")}
        ),
        facts_tool=FakeFactsTool(error=True),
        conversation_state="HUMAN_ACTIVE",
    )

    assert result.outcome == "HANDOFF"
    assert result.answer is None
    assert result.handoff_reason == "conversation_not_ai_active"
    assert result.trace == ["blocked_conversation_state"]


def test_refund_and_unknown_requests_handoff_without_answer() -> None:
    for intent, reason in (
        ("refund_request", "refund_requires_human_review"),
        ("unknown", "unsupported_investigation_intent"),
    ):
        result = run_investigation(
            "please help",
            model=MockInvestigationModel(
                {"please help": ModelDecision(intent=intent)}  # type: ignore[arg-type]
            ),
            facts_tool=FakeFactsTool(),
            conversation_state="AI_ACTIVE",
        )
        assert result.outcome == "HANDOFF"
        assert result.answer is None
        assert result.evidence == []
        assert result.handoff_reason == reason


def test_missing_facts_and_tool_errors_fail_closed() -> None:
    model = MockInvestigationModel(
        {"where is my order": ModelDecision(intent="order_status")}
    )
    missing = run_investigation(
        "where is my order",
        model=model,
        facts_tool=FakeFactsTool(),
        conversation_state="AI_ACTIVE",
        order_id="order_missing",
    )
    failed = run_investigation(
        "where is my order",
        model=model,
        facts_tool=FakeFactsTool(error=True),
        conversation_state="AI_ACTIVE",
        order_id="order_1001",
    )

    assert missing.handoff_reason == "order_facts_unavailable"
    assert failed.handoff_reason == "workflow_error"
    assert missing.answer is None and failed.answer is None


def test_order_facts_reuse_existing_status_contracts() -> None:
    with pytest.raises(ValueError):
        OrderFacts(
            order_id="order_1001",
            status="invented_status",  # type: ignore[arg-type]
            shipment_status="delayed",
        )
