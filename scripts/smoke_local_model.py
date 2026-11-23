"""Opt-in smoke test for an already-cached local Transformers answer model.

The script never downloads weights. It is intentionally separate from the
customer default, which remains deterministic generation.
"""

from __future__ import annotations

import argparse
import json
import os
import time

from backend.app.ai.answer import answer_from_published_policy
from backend.app.ai.generation import (
    PolicyAnswerPrompt,
    authorized_evidence,
    validate_generated_answer,
)
from backend.app.ai.local_transformers import LocalTransformersPolicyAnswerProvider
from backend.app.rag.corpus import POLICY_CORPUS
from backend.app.rag.retrieval import retrieve_published_policy


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

    query = "What should I do if my shipment is delayed?"
    evidence = retrieve_published_policy(query, audience="customer", top_k=3)
    if not evidence:
        raise RuntimeError("the local policy corpus did not provide smoke-test evidence")
    answer_texts = []
    for item in evidence:
        record = next(
            record
            for record in POLICY_CORPUS
            if (
                record.document_id == item.document_id
                and record.document_version == item.document_version
                and record.section == item.section
                and record.release_id == item.release_id
            )
        )
        answer_texts.append(record.answer_text or record.text)
    authorized = authorized_evidence(evidence, answer_texts)
    prompt = PolicyAnswerPrompt(query=query, evidence=authorized)
    provider = LocalTransformersPolicyAnswerProvider(
        args.model, timeout_seconds=args.timeout_seconds
    )

    started = time.perf_counter()
    raw = provider.generate(prompt)
    validated = validate_generated_answer(raw, authorized)
    direct_latency_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    integrated = answer_from_published_policy(
        query, response_provider=provider, corpus=POLICY_CORPUS
    )
    integrated_latency_ms = (time.perf_counter() - started) * 1000
    if integrated.generation_mode != "model":
        raise RuntimeError("the answer boundary did not accept the model response")

    print(
        json.dumps(
            {
                "status": "passed",
                "model": args.model,
                "device": "cuda if available, otherwise cpu (provider-selected)",
                "direct_generation_latency_ms": round(direct_latency_ms, 2),
                "integrated_generation_latency_ms": round(integrated_latency_ms, 2),
                "citation_ids": validated.citation_ids,
                "retrieval_mode": integrated.retrieval_mode,
                "generation_mode": integrated.generation_mode,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
