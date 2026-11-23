"""Small, controlled LangGraph investigation workflow.

The graph is deliberately finite and dependency-injected.  Model decisions
and order facts come from typed boundaries so tests never need a live model,
database, or arbitrary tool execution.
"""

from __future__ import annotations

from time import perf_counter
from typing import Literal, Mapping, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from backend.app.contracts import (
    ConversationState,
    GenerationMode,
    OrderStatus,
    ShipmentStatus,
)
from backend.app.ai.generation import PolicyAnswerProvider
from backend.app.diagnostics import log_event
from backend.app.rag.models import PolicyAudience, PolicyEvidence
from backend.app.ai.answer import PolicyRetriever, answer_from_published_policy


InvestigationIntent = Literal[
    "order_status",
    "payment_total",
    "shipment_tracking",
    "refund_status",
    "database_policy_question",
    "policy_question",
    "refund_request",
    "unknown",
]
RefundStatus = Literal["PENDING_REVIEW", "APPROVED_EXTERNAL_ACTION_REQUIRED", "REJECTED"]
InvestigationOutcome = Literal["ANSWER", "HANDOFF"]
RetrievalMode = Literal[
    "not_applicable",
    "lexical",
    "semantic",
    "lexical_fallback",
]


class OrderFacts(BaseModel):
    """Only the verified order fields that the graph is allowed to use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str
    status: OrderStatus
    shipment_status: ShipmentStatus
    estimated_delivery: str | None = None
    total_cents: int | None = None
    payment_amount_cents: int | None = None
    payment_status: Literal["pending", "paid", "failed"] | None = None
    payment_method: str | None = None
    tracking_number: str | None = None
    shipped_at: str | None = None
    delivered_at: str | None = None
    refund_state: RefundStatus | None = None


class ModelDecision(BaseModel):
    """Bounded response from the injected classifier/model boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: InvestigationIntent


class InvestigationResult(BaseModel):
    """Stable result returned by the graph to an API/service caller."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: InvestigationOutcome
    answer: str | None
    evidence: list[PolicyEvidence]
    handoff_reason: str | None
    trace: list[str]
    retrieval_mode: RetrievalMode = "not_applicable"
    generation_mode: GenerationMode = "deterministic"
    citation_ids: list[str] = []


class InvestigationModel(Protocol):
    """Allowlisted model boundary; implementations may be mocked in tests."""

    def classify(self, query: str) -> ModelDecision:
        """Classify into one of the four bounded investigation intents."""


class OrderFactsTool(Protocol):
    """Typed business-facts tool; implementations own authorization/storage."""

    def get_order_facts(self, order_id: str) -> OrderFacts | None:
        """Return facts for an already-authorized order or no result."""


class MockInvestigationModel:
    """Deterministic model stand-in for local development and tests."""

    def __init__(
        self,
        responses: Mapping[str, ModelDecision] | None = None,
        *,
        default: ModelDecision | None = None,
    ) -> None:
        self._responses = dict(responses or {})
        self._default = default or ModelDecision(intent="unknown")

    def classify(self, query: str) -> ModelDecision:
        return self._responses.get(query, self._default)


class _InvestigationState(TypedDict, total=False):
    query: str
    audience: PolicyAudience
    conversation_state: ConversationState
    order_id: str | None
    model: InvestigationModel
    facts_tool: OrderFactsTool
    policy_retriever: PolicyRetriever | None
    response_provider: PolicyAnswerProvider | None
    intent: InvestigationIntent
    facts: OrderFacts | None
    result: InvestigationResult
    trace: list[str]


def _trace(state: _InvestigationState, step: str) -> list[str]:
    return [*state.get("trace", []), step]


def _handoff_result(
    state: _InvestigationState, reason: str, step: str = "handoff"
) -> InvestigationResult:
    return InvestigationResult(
        outcome="HANDOFF",
        answer=None,
        evidence=[],
        handoff_reason=reason,
        trace=_trace(state, step),
    )


def _classify(state: _InvestigationState) -> dict[str, object]:
    decision = state["model"].classify(state["query"])
    return {"intent": decision.intent, "trace": _trace(state, "classify")}


def _route_after_classify(state: _InvestigationState) -> str:
    intent = state.get("intent", "unknown")
    if intent == "order_status":
        return "fetch_order_facts"
    if intent in {"payment_total", "shipment_tracking", "refund_status", "database_policy_question"}:
        return "fetch_order_facts"
    if intent == "policy_question":
        return "answer_policy"
    return "handoff_intent"


def _fetch_order_facts(state: _InvestigationState) -> dict[str, object]:
    order_id = state.get("order_id")
    if not order_id:
        return {
            "result": _handoff_result(state, "missing_order_id", "fetch_order_facts"),
            "trace": _trace(state, "fetch_order_facts"),
        }
    facts = state["facts_tool"].get_order_facts(order_id)
    if facts is None:
        return {
            "result": _handoff_result(
                state, "order_facts_unavailable", "fetch_order_facts"
            ),
            "trace": _trace(state, "fetch_order_facts"),
        }
    return {"facts": facts, "trace": _trace(state, "fetch_order_facts")}


def _answer_order(state: _InvestigationState) -> dict[str, object]:
    facts = state.get("facts")
    if facts is None:
        return {
            "result": _handoff_result(state, "order_facts_unavailable", "answer_order"),
            "trace": _trace(state, "answer_order"),
        }
    answer = (
        f"Order {facts.order_id} is {facts.status}; shipment is "
        f"{facts.shipment_status}."
    )
    if facts.estimated_delivery:
        answer += f" Estimated delivery: {facts.estimated_delivery}."
    return {
        "result": InvestigationResult(
            outcome="ANSWER",
            answer=answer,
            evidence=[],
            handoff_reason=None,
            trace=_trace(state, "answer_order"),
        ),
        "trace": _trace(state, "answer_order"),
    }


def _answer_structured(state: _InvestigationState) -> dict[str, object]:
    facts = state.get("facts")
    intent = state.get("intent")
    reason: str | None = None
    if facts is None:
        reason = "order_facts_unavailable"
    elif intent == "payment_total" and any(
        term in state["query"].casefold()
        for term in ("paid", "payment", "charged", "amount", "payment method")
    ) and facts.payment_amount_cents is None and facts.payment_status is None:
        reason = "order_facts_unavailable"
    elif intent == "payment_total" and facts.total_cents is None:
        reason = "order_facts_unavailable"
    elif intent == "shipment_tracking":
        normalized_query = state["query"].casefold()
        needs_date = any(
            term in normalized_query
            for term in ("when", "date", "arrive", "delivered", "shipped", "delivery")
        )
        if (not facts.tracking_number) or (
            needs_date
            and not any(
                (facts.estimated_delivery, facts.shipped_at, facts.delivered_at)
            )
        ):
            reason = "order_facts_unavailable"
    elif intent == "refund_status" and facts.refund_state is None:
        reason = "order_facts_unavailable"
    elif intent == "database_policy_question":
        return _answer_database_policy(state)
    else:
        reason = None
    if reason is not None:
        return {"result": _handoff_result(state, reason, "answer_structured"), "trace": _trace(state, "answer_structured")}
    if intent == "payment_total":
        cents = facts.total_cents
        amount = facts.payment_amount_cents or cents
        answer = f"The total for order {facts.order_id} is ${cents // 100}.{cents % 100:02d}."
        if facts.payment_amount_cents is not None:
            answer += f" Recorded payment: ${amount // 100}.{amount % 100:02d}."
        if facts.payment_status is not None:
            answer += f" Payment status: {facts.payment_status}."
        if facts.payment_method is not None:
            answer += f" Payment method: {facts.payment_method}."
    elif intent == "shipment_tracking":
        answer = (
            f"The tracking number for order {facts.order_id} is {facts.tracking_number}."
            f" Shipment status: {facts.shipment_status}."
        )
        if facts.estimated_delivery:
            answer += f" Estimated delivery: {facts.estimated_delivery}."
        if facts.shipped_at:
            answer += f" Shipped at: {facts.shipped_at}."
        if facts.delivered_at:
            answer += f" Delivered at: {facts.delivered_at}."
    else:
        answer = f"The refund status for order {facts.order_id} is {facts.refund_state}."
    return {"result": InvestigationResult(outcome="ANSWER", answer=answer, evidence=[], handoff_reason=None, trace=_trace(state, "answer_structured")), "trace": _trace(state, "answer_structured")}


def _answer_database_policy(state: _InvestigationState) -> dict[str, object]:
    facts = state.get("facts")
    grounded = answer_from_published_policy(state["query"], audience=state["audience"], policy_retriever=state.get("policy_retriever"), response_provider=state.get("response_provider"))
    if facts is None:
        reason = "order_facts_unavailable"
    elif not grounded.grounded or grounded.answer is None:
        reason = "insufficient_published_policy"
    else:
        result = InvestigationResult(outcome="ANSWER", answer=f"Order {facts.order_id} is {facts.status}; shipment is {facts.shipment_status}. {grounded.answer}", evidence=grounded.evidence, handoff_reason=None, trace=_trace(state, "answer_database_policy"), retrieval_mode=grounded.retrieval_mode, generation_mode=("model" if grounded.generation_mode == "model" else "deterministic"), citation_ids=grounded.citation_ids)
        return {"result": result, "trace": _trace(state, "answer_database_policy")}
    result = _handoff_result(state, reason, "answer_database_policy").model_copy(update={"retrieval_mode": grounded.retrieval_mode, "citation_ids": grounded.citation_ids})
    return {"result": result, "trace": _trace(state, "answer_database_policy")}


def _answer_policy(state: _InvestigationState) -> dict[str, object]:
    grounded = answer_from_published_policy(
        state["query"],
        audience=state["audience"],
        policy_retriever=state.get("policy_retriever"),
        response_provider=state.get("response_provider"),
    )
    if not grounded.grounded or grounded.answer is None:
        result = _handoff_result(state, "insufficient_published_policy", "answer_policy")
        result = result.model_copy(
            update={
                "retrieval_mode": grounded.retrieval_mode,
                "citation_ids": grounded.citation_ids,
            }
        )
    else:
        result = InvestigationResult(
            outcome="ANSWER",
            answer=grounded.answer,
            evidence=grounded.evidence,
            handoff_reason=None,
            trace=_trace(state, "answer_policy"),
            retrieval_mode=grounded.retrieval_mode,  # type: ignore[arg-type]
            generation_mode=(
                "model" if grounded.generation_mode == "model" else "deterministic"
            ),
            citation_ids=grounded.citation_ids,
        )
    return {"result": result, "trace": _trace(state, "answer_policy")}


def _handoff_intent(state: _InvestigationState) -> dict[str, object]:
    reason = (
        "refund_requires_human_review"
        if state.get("intent") == "refund_request"
        else "unsupported_investigation_intent"
    )
    return {
        "result": _handoff_result(state, reason, "handoff_intent"),
        "trace": _trace(state, "handoff_intent"),
    }


def _finish(state: _InvestigationState) -> dict[str, object]:
    """Preserve a result produced by a guarded tool node."""

    return {"trace": state.get("trace", [])}


def _build_graph():
    graph = StateGraph(_InvestigationState)
    graph.add_node("classify", _classify)
    graph.add_node("fetch_order_facts", _fetch_order_facts)
    graph.add_node("answer_order", _answer_order)
    graph.add_node("answer_structured", _answer_structured)
    graph.add_node("answer_policy", _answer_policy)
    graph.add_node("handoff_intent", _handoff_intent)
    graph.add_node("finish", _finish)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        _route_after_classify,
        {
            "fetch_order_facts": "fetch_order_facts",
            "answer_policy": "answer_policy",
            "handoff_intent": "handoff_intent",
        },
    )
    graph.add_conditional_edges(
        "fetch_order_facts",
        lambda state: "finish" if state.get("result") is not None else "answer_structured" if state.get("intent") != "order_status" and state.get("facts") is not None else "answer_order" if state.get("facts") is not None else "handoff_intent",
        {"answer_order": "answer_order", "answer_structured": "answer_structured", "finish": "finish", "handoff_intent": "handoff_intent"},
    )
    graph.add_edge("answer_order", END)
    graph.add_edge("answer_structured", END)
    graph.add_edge("answer_policy", END)
    graph.add_edge("handoff_intent", END)
    graph.add_edge("finish", END)
    return graph.compile()


def run_investigation(
    query: str,
    *,
    model: InvestigationModel,
    facts_tool: OrderFactsTool,
    audience: PolicyAudience = "customer",
    conversation_state: ConversationState,
    order_id: str | None = None,
    policy_retriever: PolicyRetriever | None = None,
    response_provider: PolicyAnswerProvider | None = None,
) -> InvestigationResult:
    """Run the finite investigation graph and fail closed on tool/model errors."""

    started = perf_counter()

    def record(result: InvestigationResult) -> InvestigationResult:
        log_event(
            "investigation_completed",
            outcome=result.outcome,
            retrieval_mode=result.retrieval_mode,
            generation_mode=result.generation_mode,
            evidence_count=len(result.evidence),
            handed_off=result.outcome == "HANDOFF",
            handoff_reason=result.handoff_reason,
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
        )
        return result

    if conversation_state != "AI_ACTIVE":
        return record(
            InvestigationResult(
                outcome="HANDOFF",
                answer=None,
                evidence=[],
                handoff_reason="conversation_not_ai_active",
                trace=["blocked_conversation_state"],
            )
        )
    if not query.strip():
        return record(
            InvestigationResult(
                outcome="HANDOFF",
                answer=None,
                evidence=[],
                handoff_reason="empty_query",
                trace=["input_validation"],
            )
        )

    initial: _InvestigationState = {
        "query": query,
        "audience": audience,
        "conversation_state": conversation_state,
        "order_id": order_id,
        "model": model,
        "facts_tool": facts_tool,
        "policy_retriever": policy_retriever,
        "response_provider": response_provider,
        "trace": [],
    }
    try:
        state = _build_graph().invoke(initial)
    except Exception as error:
        log_event(
            "investigation_failed",
            error_category="workflow_exception",
            error_type=type(error).__name__,
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
        )
        return record(
            InvestigationResult(
                outcome="HANDOFF",
                answer=None,
                evidence=[],
                handoff_reason="workflow_error",
                trace=["workflow_error"],
            )
        )
    result = state.get("result")
    if not isinstance(result, InvestigationResult):
        return record(
            InvestigationResult(
                outcome="HANDOFF",
                answer=None,
                evidence=[],
                handoff_reason="missing_workflow_result",
                trace=[*state.get("trace", []), "missing_workflow_result"],
            )
        )
    return record(result)


__all__ = [
    "InvestigationIntent",
    "InvestigationModel",
    "InvestigationOutcome",
    "InvestigationResult",
    "RetrievalMode",
    "MockInvestigationModel",
    "ModelDecision",
    "OrderFacts",
    "OrderFactsTool",
    "PolicyRetriever",
    "run_investigation",
]
