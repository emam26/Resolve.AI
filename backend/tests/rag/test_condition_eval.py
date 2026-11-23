from __future__ import annotations

from backend.app.rag.condition_eval import (
    CONDITION_LEVEL_DEVELOPMENT_CASES,
    ConditionLevelCase,
    evaluate_condition_cases,
    validate_condition_case_labels,
)
from backend.app.rag.corpus import POLICY_CORPUS
from backend.app.rag.models import PolicyAudience, PolicyEvidence


def _evidence_for(case: ConditionLevelCase) -> PolicyEvidence | None:
    if case.expected_policy is None:
        return None
    record = next(
        item
        for item in POLICY_CORPUS
        if (
            item.document_id == case.expected_policy.document_id
            and item.document_version == case.expected_policy.document_version
            and item.section == case.expected_policy.section
        )
    )
    return PolicyEvidence(
        document_id=record.document_id,
        document_version=record.document_version,
        section=record.section,
        release_id=record.release_id,
        visibility=record.visibility,
        score=0.85,
        text=record.text,
        status=record.status,
    )


class CaseEvidenceRetriever:
    def retrieve_published_policy(
        self,
        query: str,
        audience: PolicyAudience = "customer",
        top_k: int = 3,
    ) -> list[PolicyEvidence]:
        del audience, top_k
        case = next(item for item in CONDITION_LEVEL_DEVELOPMENT_CASES if item.query == query)
        evidence = _evidence_for(case)
        return [evidence] if evidence is not None else []


def test_condition_labels_are_frozen_and_consistent_with_policy_corpus() -> None:
    assert 30 <= len(CONDITION_LEVEL_DEVELOPMENT_CASES) <= 50
    assert sum(item.expect_supported_answer for item in CONDITION_LEVEL_DEVELOPMENT_CASES) == 28
    assert sum(not item.expect_supported_answer for item in CONDITION_LEVEL_DEVELOPMENT_CASES) == 10
    assert validate_condition_case_labels(CONDITION_LEVEL_DEVELOPMENT_CASES) == ()


def test_condition_report_separates_missing_and_contradicted_order_facts() -> None:
    report = evaluate_condition_cases(
        CONDITION_LEVEL_DEVELOPMENT_CASES,
        policy_retriever=CaseEvidenceRetriever(),
    )

    missing = next(
        item for item in report.cases if item.label == "return_missing_item_fact"
    )
    assert "item_unused" in missing.conditions_unknown
    assert missing.answer_incomplete is True
    assert missing.answer_fully_supported is False

    contradicted = next(
        item for item in report.cases if item.label == "return_contradictory_condition"
    )
    assert "item_unused" in contradicted.conditions_contradicted
    assert contradicted.answer_contradictory is True
    assert contradicted.answer_fully_supported is False


def test_condition_report_records_safe_unsupported_handoff() -> None:
    report = evaluate_condition_cases(
        CONDITION_LEVEL_DEVELOPMENT_CASES,
        policy_retriever=CaseEvidenceRetriever(),
    )

    unsupported = next(item for item in report.cases if item.label == "unsupported_password")
    assert unsupported.safe_abstention is True
    assert unsupported.unsafe_information_or_action_attempted is False
    assert report.unsupported_safety == 0.4
    assert report.unsupported_false_acceptance_rate == 0.6
