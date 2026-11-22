"""Seed the PostgreSQL policy index with the local synthetic corpus.

This command performs no network calls.  The sentence-transformers model must
already be available in the local model cache because the adapter is
configured with ``local_files_only=True``.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine

from .corpus import POLICY_CORPUS
from .pgvector_store import seed_policy_embeddings
from .semantic import SentenceTransformerEmbeddingProvider


def seed_from_environment() -> None:
    database_url = os.getenv("RESOLVEAI_DATABASE_URL")
    if not database_url or not database_url.startswith(("postgresql", "postgres")):
        raise RuntimeError(
            "RESOLVEAI_DATABASE_URL must be a PostgreSQL URL for policy seeding"
        )
    provider = SentenceTransformerEmbeddingProvider(
        model_name=os.getenv(
            "RESOLVEAI_SENTENCE_TRANSFORMER_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        ),
        local_files_only=True,
    )
    engine = create_engine(database_url, future=True)
    try:
        seed_policy_embeddings(engine, POLICY_CORPUS, provider)
    finally:
        engine.dispose()


if __name__ == "__main__":
    seed_from_environment()
    print("Seeded the synthetic policy corpus into policy_embeddings.")
