from __future__ import annotations

from backend.app.rag.evaluation import (
    M16_CALIBRATION_EVALUATION_CASES,
    M16_CALIBRATION_EVALUATION_SET_VERSION,
)


def test_m16_calibration_cases_are_predeclared_and_cover_safety_boundaries() -> None:
    labels = [case.label for case in M16_CALIBRATION_EVALUATION_CASES]
    assert M16_CALIBRATION_EVALUATION_SET_VERSION == "rag-m16-calibration-v1"
    assert len(labels) == len(set(labels)) == 14
    assert (
        sum(case.expect_supported_answer for case in M16_CALIBRATION_EVALUATION_CASES)
        == 8
    )
    assert (
        sum(not case.expect_supported_answer for case in M16_CALIBRATION_EVALUATION_CASES)
        == 6
    )
    assert any(
        case.forbidden_document_id == "refund-review-policy"
        for case in M16_CALIBRATION_EVALUATION_CASES
    )
    assert any(
        case.forbidden_document_id == "warranty-policy"
        for case in M16_CALIBRATION_EVALUATION_CASES
    )
    assert any(
        case.forbidden_version == "v0"
        for case in M16_CALIBRATION_EVALUATION_CASES
    )
