---
name: policy-rag-check
description: Reuse a small offline policy retrieval evaluation process for ResolveAI when altering document ingestion, published versions, semantic pgvector search, full-text baseline or citations. Never use paid LLM APIs by default.
---
# Policy retrieval check (offline first)

1. Locate existing policy fixtures, labeled questions and test/evaluation commands through `docs/PROJECT_STATE.md`. Extend an existing evaluation set instead of producing a new competing benchmark.
2. Freeze a small synthetic policy corpus with published/unpublished and public/internal versions, section labels, release IDs, and unknown-answer cases.
3. Reuse or add *predeclared* labeled questions (expected version/section or no sufficient evidence); never rewrite labels after seeing results.
4. Evaluate PostgreSQL full-text baseline and sentence-transformers/pgvector semantic retrieval on the same queries where local tooling permits. Calculate Recall@3, wrong-version exposure, citation/visibility accuracy and unsupported-answer behavior. Keep tests deterministic where practical.
5. Do not make real model/paid embedding calls. If dependencies or DB aren't set up, run appropriate pure-Python tests, mark DB retrieval 'not verified', and provide a minimal manual step.
6. Report corpus version, query count, command, actual results and specific failures. Add no reranker or extra vector database without measured benefit.
