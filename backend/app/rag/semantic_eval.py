"""Run the frozen policy evaluation against the local semantic index.

This command is intentionally read-only: migrations and seeding are separate
commands, and model loading remains local-files-only. It provides a
reproducible check of the real sentence-transformers/pgvector path without
network access or a live model call.
"""

from __future__ import annotations

import json
import os

from .evaluation import (
    DEFAULT_EVALUATION_CASES,
    M11A_EVALUATION_CASES,
    evaluate_answer_contract,
    evaluate_raw_semantic_ranking,
    evaluate_policy_retrieval,
)
from .pgvector_store import PgVectorPolicyRetriever
from .semantic import SentenceTransformerEmbeddingProvider


def evaluate_from_environment() -> dict[str, object]:
    """Evaluate the seeded PostgreSQL policy index using the local model cache."""

    database_url = os.getenv("RESOLVEAI_DATABASE_URL")
    if not database_url or not database_url.startswith(("postgresql", "postgres")):
        raise RuntimeError(
            "RESOLVEAI_DATABASE_URL must be a PostgreSQL URL for semantic evaluation"
        )

    retriever = PgVectorPolicyRetriever(
        database_url,
        SentenceTransformerEmbeddingProvider(
            model_name=os.getenv(
                "RESOLVEAI_SENTENCE_TRANSFORMER_MODEL",
                "sentence-transformers/all-MiniLM-L6-v2",
            ),
            local_files_only=True,
        ),
    )
    try:
        cases = DEFAULT_EVALUATION_CASES + M11A_EVALUATION_CASES
        thresholded = evaluate_policy_retrieval(
            cases=cases,
            policy_retriever=retriever,
        ).as_dict()
        return {
            "raw_ranking": evaluate_raw_semantic_ranking(
                cases=cases,
                policy_retriever=retriever,
            ).as_dict(),
            "thresholded_retrieval": thresholded,
            # Preserve the historical CLI key for existing local consumers;
            # the explicit name above is the authoritative interpretation.
            "retrieval": thresholded,
            "answer_contract": evaluate_answer_contract(
                cases=cases,
                policy_retriever=retriever,
            ).as_dict(),
        }
    finally:
        retriever.close()


if __name__ == "__main__":
    print(json.dumps(evaluate_from_environment(), indent=2))
