"""Evaluate an already-cached local answer model on synthetic policy cases.

This is an opt-in M17 harness.  It never downloads weights, calls a hosted
provider, or changes the deterministic customer default.  Retrieval remains
the existing deterministic policy boundary so generation quality is measured
separately from semantic retrieval quality.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from statistics import mean, median
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app.ai.answer import answer_from_published_policy
from backend.app.ai.local_transformers import LocalTransformersPolicyAnswerProvider
from backend.app.rag.corpus import POLICY_CORPUS
from backend.app.rag.evaluation import (
    M16_CALIBRATION_EVALUATION_CASES,
    M16_CALIBRATION_EVALUATION_SET_VERSION,
)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def _expected_evidence(case, answer) -> bool:
    if not answer.evidence:
        return False
    evidence = answer.evidence[0]
    return (
        evidence.document_id == case.expected_document_id
        and evidence.document_version == case.expected_version
        and evidence.section == case.expected_section
        and evidence.status == "published"
        and (case.audience != "customer" or evidence.visibility == "public")
    )


def evaluate(model: str, timeout_seconds: float, max_new_tokens: int) -> dict[str, object]:
    provider = LocalTransformersPolicyAnswerProvider(
        model,
        timeout_seconds=timeout_seconds,
        max_new_tokens=max_new_tokens,
    )
    latencies: list[float] = []
    input_tokens = 0
    output_tokens = 0
    estimated_token_calls = 0
    provider_fallbacks = 0
    model_accepted = 0
    supported_total = 0
    supported_valid = 0
    unsupported_total = 0
    unsupported_valid = 0
    citation_valid = 0
    evaluated_cases = 0
    case_results: list[dict[str, object]] = []
    provider_unavailable = False

    for case in M16_CALIBRATION_EVALUATION_CASES:
        if case.expect_supported_answer:
            supported_total += 1
        else:
            unsupported_total += 1
        calls_before = provider.generation_count
        started = time.perf_counter()
        answer = answer_from_published_policy(
            case.query,
            audience=case.audience,
            corpus=POLICY_CORPUS,
            response_provider=provider,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        evaluated_cases += 1

        call_made = provider.generation_count > calls_before
        usage = provider.last_usage if call_made else None
        if usage is not None:
            input_tokens += int(usage["input_tokens"])
            output_tokens += int(usage["output_tokens"])
            estimated_token_calls += int(bool(usage.get("estimated", False)))
        if call_made and answer.generation_mode != "model":
            provider_fallbacks += 1
            if usage is None:
                provider_unavailable = True
        if answer.generation_mode == "model":
            model_accepted += 1

        expected = _expected_evidence(case, answer)
        citation_ok = (
            answer.grounded
            and bool(answer.citation_ids)
            and all(
                citation == f"evidence-{index}"
                for index, citation in enumerate(answer.citation_ids, start=1)
            )
        )
        citation_valid += int(citation_ok if case.expect_supported_answer else not answer.evidence)
        if case.expect_supported_answer:
            valid = (
                answer.generation_mode == "model"
                and answer.grounded
                and not answer.needs_handoff
                and expected
                and citation_ok
            )
            supported_valid += int(valid)
        else:
            valid = (
                not answer.grounded
                and answer.answer is None
                and answer.needs_handoff
                and not answer.evidence
            )
            unsupported_valid += int(valid)

        case_results.append(
            {
                "label": case.label,
                "supported": case.expect_supported_answer,
                "generation_mode": answer.generation_mode,
                "handoff": answer.needs_handoff,
                "contract_valid": valid,
                "latency_ms": round(latency_ms, 2),
            }
        )
        if provider_unavailable:
            break

    status = "provider_unavailable" if provider_unavailable else "completed"
    return {
        "status": status,
        "model": model,
        "calibration_set": M16_CALIBRATION_EVALUATION_SET_VERSION,
        "cases_evaluated": evaluated_cases,
        "supported_answer_accuracy": (
            supported_valid / supported_total if supported_total else 0.0
        ),
        "unsupported_safety": (
            unsupported_valid / unsupported_total if unsupported_total else 0.0
        ),
        "model_accepted_cases": model_accepted,
        "provider_fallbacks": provider_fallbacks,
        "citation_validity": citation_valid / evaluated_cases if evaluated_cases else 0.0,
        "latency_ms": {
            "mean": round(mean(latencies), 2) if latencies else 0.0,
            "p50": round(median(latencies), 2) if latencies else 0.0,
            "p95": round(_percentile(latencies, 0.95), 2),
        },
        "token_accounting": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_calls": estimated_token_calls,
        },
        "cases": case_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.getenv("RESOLVEAI_LOCAL_POLICY_MODEL", "").strip(),
        help="local model directory or cached model name; no download is attempted",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.getenv("RESOLVEAI_LOCAL_POLICY_TIMEOUT_SECONDS", "8")),
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=int(os.getenv("RESOLVEAI_LOCAL_POLICY_MAX_NEW_TOKENS", "256")),
    )
    args = parser.parse_args()
    if not args.model:
        print(
            json.dumps(
                {
                    "status": "not_run",
                    "reason": "RESOLVEAI_LOCAL_POLICY_MODEL or --model is required",
                    "default_generation": "deterministic",
                },
                indent=2,
            )
        )
        return 0
    print(json.dumps(evaluate(args.model, args.timeout_seconds, args.max_new_tokens), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
