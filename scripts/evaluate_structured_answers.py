"""Run the frozen M16-DB structured-answer benchmark locally.

This evaluator uses the same finite investigation graph and typed facts
boundary as the application, with deterministic synthetic records and a
mocked published-policy retriever.  It never calls a model or external API.
The commerce repository projection is verified separately against PostgreSQL
when ``RESOLVEAI_TEST_POSTGRES_URL`` is configured.
"""

from __future__ import annotations

import json
import os
import sys
from time import perf_counter

from backend.app.ai.investigation import ModelDecision, OrderFacts, run_investigation
from backend.app.commerce.structured_evaluation import (
    STRUCTURED_EVALUATION_CASES,
    STRUCTURED_RECORDS,
    StructuredEvaluationCase,
    StructuredRun,
    evaluate_structured_cases,
)
from backend.app.commerce.repository import CommerceRepository
from backend.app.rag.models import PolicyEvidence
from backend.app.services.in_memory import DemoInvestigationModel


class _BenchmarkFactsTool:
    def __init__(self, customer_id: str) -> None:
        self.customer_id = customer_id
        self.last_order_id: str | None = None
        self.last_values: tuple[tuple[str, str], ...] = ()
        self._records = {record.order_id: record for record in STRUCTURED_RECORDS}

    def get_order_facts(self, order_id: str) -> OrderFacts | None:
        record = self._records.get(order_id)
        if record is None or record.owner_customer_id != self.customer_id:
            return None
        self.last_order_id = record.order_id
        self.last_values = tuple(
            (key, str(value))
            for key, value in (
                ("status", record.status),
                ("shipment_status", record.shipment_status),
                ("total_cents", record.total_cents),
                ("payment_amount_cents", record.payment_amount_cents),
                ("payment_status", record.payment_status),
                ("tracking_number", record.tracking_number),
                ("estimated_delivery", record.estimated_delivery),
                ("shipped_at", record.shipped_at),
                ("delivered_at", record.delivered_at),
                ("refund_state", record.refund_state),
            )
            if value is not None
        )
        return OrderFacts(
            order_id=record.order_id,
            status=record.status,  # type: ignore[arg-type]
            shipment_status=record.shipment_status,  # type: ignore[arg-type]
            estimated_delivery=record.estimated_delivery,
            total_cents=record.total_cents,
            payment_amount_cents=record.payment_amount_cents,
            payment_status=record.payment_status,  # type: ignore[arg-type]
            tracking_number=record.tracking_number,
            shipped_at=record.shipped_at,
            delivered_at=record.delivered_at,
            refund_state=record.refund_state,  # type: ignore[arg-type]
        )


class _PostgresFactsTool:
    """Use the imported synthetic records through the real read boundary."""

    def __init__(self, customer_id: str, repository: CommerceRepository) -> None:
        self.customer_id = customer_id
        self.repository = repository
        self.last_order_id: str | None = None
        self.last_values: tuple[tuple[str, str], ...] = ()

    def get_order_facts(self, order_id: str) -> OrderFacts | None:
        order = self.repository.order_for_customer(order_id, self.customer_id)
        if order is None:
            return None
        record = next(
            item for item in STRUCTURED_RECORDS if item.order_id == order.summary.order_id
        )
        refund_state = order.refund_state or record.refund_state
        self.last_order_id = order.summary.order_id
        self.last_values = tuple(
            (key, str(value))
            for key, value in (
                ("status", order.summary.status),
                ("shipment_status", order.summary.shipment_status),
                ("total_cents", order.total_cents),
                ("payment_amount_cents", order.payment_amount_cents),
                ("payment_status", order.summary.payment_status if order.payment_status else None),
                ("tracking_number", order.tracking_number),
                ("estimated_delivery", order.summary.estimated_delivery_date.isoformat() if order.summary.estimated_delivery_date else None),
                ("shipped_at", order.shipped_at.isoformat() if order.shipped_at else None),
                ("delivered_at", order.delivered_at.isoformat() if order.delivered_at else None),
                ("refund_state", refund_state),
            )
            if value is not None
        )
        return OrderFacts(
            order_id=order.summary.order_id,
            status=order.summary.status,
            shipment_status=order.summary.shipment_status,
            estimated_delivery=(
                None
                if order.summary.estimated_delivery_date is None
                else order.summary.estimated_delivery_date.isoformat()
            ),
            total_cents=order.total_cents,
            payment_amount_cents=order.payment_amount_cents,
            payment_status=(
                None
                if order.payment_status is None
                else order.summary.payment_status
            ),
            payment_method=order.payment_method,
            tracking_number=order.tracking_number,
            shipped_at=None if order.shipped_at is None else order.shipped_at.isoformat(),
            delivered_at=None if order.delivered_at is None else order.delivered_at.isoformat(),
            refund_state=refund_state,  # type: ignore[arg-type]
        )


class _BenchmarkPolicyRetriever:
    def __init__(self, policy_key: str | None) -> None:
        self.policy_key = policy_key

    def retrieve_published_policy(
        self, query: str, audience: str = "customer", top_k: int = 3
    ) -> list[PolicyEvidence]:
        if self.policy_key is None:
            return []
        document_id, version, section = self.policy_key.split(":", 2)
        return [
            PolicyEvidence(
                document_id=document_id,
                document_version=version,
                section=section,
                release_id="eval-release-2026-01-01",
                visibility="public",
                score=0.95,
                text=(
                    "Published customer policy evidence: returns are reviewed "
                    "within the applicable delivery window; approval is not guaranteed."
                ),
                status="published",
                is_active=True,
            )
        ][:top_k]


class _LegacyInvestigationModel:
    """M16-DB baseline: status-only structured routing before this milestone."""

    def classify(self, query: str) -> ModelDecision:
        normalized = query.casefold()
        if "refund" in normalized:
            return ModelDecision(intent="refund_request")
        if any(
            phrase in normalized
            for phrase in (
                "where is", "order status", "track my", "tracking",
                "delivery status", "shipment status",
            )
        ):
            return ModelDecision(intent="order_status")
        return ModelDecision(intent="policy_question")


def _run_with_model(case: StructuredEvaluationCase, model) -> StructuredRun:
    decision = model.classify(case.question)
    structured_url = os.getenv("RESOLVEAI_STRUCTURED_EVAL_POSTGRES_URL")
    facts_tool = (
        _PostgresFactsTool(case.customer_id, CommerceRepository(structured_url))
        if structured_url
        else _BenchmarkFactsTool(case.customer_id)
    )
    started = perf_counter()
    result = run_investigation(
        case.question,
        model=model,
        facts_tool=facts_tool,
        audience="customer",
        conversation_state="AI_ACTIVE",
        order_id=case.order_id,
        policy_retriever=_BenchmarkPolicyRetriever(case.policy_key),
    )
    return StructuredRun(
        intent=decision.intent,
        outcome=result.outcome,
        answer=result.answer,
        handoff_reason=result.handoff_reason,
        authorized_fact_order_id=facts_tool.last_order_id,
        fact_values=facts_tool.last_values,
        evidence_keys=tuple(
            f"{item.document_id}:{item.document_version}:{item.section}"
            for item in result.evidence
        ),
        elapsed_ms=(perf_counter() - started) * 1000,
    )


def run_case(case: StructuredEvaluationCase) -> StructuredRun:
    return _run_with_model(case, DemoInvestigationModel())


def run_baseline_case(case: StructuredEvaluationCase) -> StructuredRun:
    return _run_with_model(case, _LegacyInvestigationModel())


def main() -> int:
    baseline = evaluate_structured_cases(run_baseline_case, STRUCTURED_EVALUATION_CASES)
    report = evaluate_structured_cases(run_case, STRUCTURED_EVALUATION_CASES)
    payload = {
        "baseline": {
            "intent_accuracy": baseline.intent_accuracy,
            "tool_authorization_accuracy": baseline.tool_authorization_accuracy,
            "field_value_accuracy": baseline.field_value_accuracy,
            "final_answer_accuracy": baseline.final_answer_accuracy,
            "missing_information_safety": baseline.missing_information_safety,
            "combined_database_policy_accuracy": baseline.combined_database_policy_accuracy,
            "unauthorized_disclosures": baseline.unauthorized_disclosures,
            "unauthorized_actions": baseline.unauthorized_actions,
            "latency_mean_ms": baseline.latency_mean_ms,
            "latency_p50_ms": baseline.latency_p50_ms,
            "latency_p95_ms": baseline.latency_p95_ms,
            "failure_count": len(baseline.failures),
        },
        "query_count": report.query_count,
        "category_counts": report.category_counts,
        "intent_accuracy": report.intent_accuracy,
        "tool_authorization_accuracy": report.tool_authorization_accuracy,
        "field_value_accuracy": report.field_value_accuracy,
        "final_answer_accuracy": report.final_answer_accuracy,
        "missing_information_safety": report.missing_information_safety,
        "combined_database_policy_accuracy": report.combined_database_policy_accuracy,
        "unauthorized_disclosures": report.unauthorized_disclosures,
        "unauthorized_actions": report.unauthorized_actions,
        "latency_mean_ms": report.latency_mean_ms,
        "latency_p50_ms": report.latency_p50_ms,
        "latency_p95_ms": report.latency_p95_ms,
        "failures": report.failures,
        "generation": "deterministic; no LLM calls",
        "facts_backend": "postgres" if os.getenv("RESOLVEAI_STRUCTURED_EVAL_POSTGRES_URL") else "typed synthetic fixture",
    }
    print(json.dumps(payload, indent=2))
    return 0 if not report.failures else 1


if __name__ == "__main__":
    sys.exit(main())
