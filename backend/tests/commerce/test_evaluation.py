from backend.app.commerce.evaluation import (
    M11A_COMMERCE_EVALUATION_CASES,
    evaluate_frozen_retrieval,
)
from backend.app.commerce.importer import transformation_manifest_sha256


def test_m11a_evaluation_is_frozen_grouped_and_security_labeled() -> None:
    cases = M11A_COMMERCE_EVALUATION_CASES
    development_groups = {case.group_id for case in cases if case.split == "development"}
    holdout_groups = {case.group_id for case in cases if case.split == "holdout"}

    assert len(cases) == 100
    assert len({case.case_id for case in cases}) == 100
    assert len({case.question for case in cases}) == 100
    assert len([case for case in cases if case.split == "development"]) == 80
    assert len([case for case in cases if case.split == "holdout"]) == 20
    assert not development_groups & holdout_groups
    assert all(case.expected_supported_facts for case in cases)
    assert all(case.security_constraint for case in cases)
    assert all(
        case.requires_handoff
        for case in cases
        if case.expected_policy_document_id is None
    )
    assert any(
        case.security_constraint == "prompt_injection_does_not_expand_access"
        for case in cases
    )
    assert any(
        case.security_constraint == "staff_only_policy_never_exposed" for case in cases
    )
    assert len([case for case in cases if case.runtime_login_enabled]) == 5
    assert all(
        "offline owner label only" in case.authorization_context
        for case in cases
        if not case.runtime_login_enabled
    )


def test_m11a_frozen_labels_execute_through_the_lexical_answer_contract() -> None:
    report = evaluate_frozen_retrieval()

    assert report.query_count == 100
    assert report.recall_at_3 == 1.0
    assert report.wrong_version_exposure == 0.0
    assert report.citation_visibility_accuracy == 1.0
    assert report.unsupported_answer_behavior == 1.0


def test_generated_scenario_manifest_is_stable_and_versioned() -> None:
    scenarios = {
        "cases": [{"case_id": "case-1", "opened_at": "2026-01-03T08:00:00"}],
        "messages": [],
        "events": [],
        "refunds": [],
    }
    manifest = transformation_manifest_sha256(scenarios)
    changed_scenarios = {**scenarios, "events": [{"event_id": "event-1"}]}

    assert manifest == transformation_manifest_sha256(scenarios)
    assert manifest != transformation_manifest_sha256(changed_scenarios)
    assert len(manifest) == 64
    assert int(manifest, 16) >= 0
