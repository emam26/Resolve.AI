# ResolveAI - one living milestone / reuse index

**Last verified by:** ResolveAI Lead (local source/tests/benchmark/browser/Git). **Date:** 2026-11-22. This file is an *index*, not evidence by itself. On opening the project, compare it with actual Git/source/test state; correct discrepancies. Do not mark work completed without inspecting and/or executing checks.

## Current workspace (Lead-verified)
- Root guidance, product docs, prompt templates, local skills, design references, and the existing `scripts/notify.ps1` are present.
- Git is initialized locally and the verified V1 work is published on the dedicated `codex/v1-local-complete` branch at `origin`; no additional Git worktree is used.
- `j.py` was not present during these inspections; it was not recreated or removed.
- A local `.venv` contains the approved backend set: FastAPI, Uvicorn, HTTPX, pytest, Pydantic, SQLAlchemy, Alembic, pgvector, psycopg, sentence-transformers, and LangGraph. Frontend dependencies are installed from `frontend/package.json` and locked in `frontend/package-lock.json`.
- No paid LLM, embedding API, commerce, authenticated external API, or deployment action was performed. Docker Engine was used only through Ubuntu WSL for disposable M6/M7/M8 PostgreSQL verification containers; they were removed after testing.

## Milestones (update after actual verification)
| ID | Outcome | Status | Reuse / proof |
|---|---|---|---|
| M0 | Git + context + first frozen contract + minimal runnable skeleton | COMPLETE | `backend/app/contracts.py`; 7 contract tests; baseline commits `1457f53` and `5af5afa` |
| M1 | Demo identity + customer-scoped synthetic order lookup + simple widget inquiry | COMPLETE | FastAPI M1 routes/services/tests and React widget; full Python suite 24 passed; frontend typecheck/build passed; review findings fixed |
| M2 | Published policy RAG + retrieval evaluation + grounded agent answer | COMPLETE (offline lexical baseline) | `backend/app/rag/**`; `backend/app/ai/**`; 5 predeclared evaluation cases; Recall@3 1.0, wrong-version exposure 0.0, citation/visibility accuracy 1.0, unsupported-answer behavior 1.0; weak-overlap handoff reviewed |
| M2S | Semantic policy retrieval foundation | COMPLETE (offline implementation; real model loading verified in M7; PostgreSQL runtime verified in M6-DB) | `backend/app/rag/semantic.py`; `backend/app/rag/pgvector_store.py`; `backend/tests/rag/test_semantic.py`; lazy sentence-transformers adapter, deterministic cosine retrieval, calibrated 0.60 sufficiency gate, 384-dimension pgvector query builder; focused semantic tests passed |
| M2L | Controlled LangGraph investigation workflow with mocked model responses | COMPLETE (mocked/local workflow; live model unverified) | `backend/app/ai/investigation.py`; `backend/tests/ai/test_investigation.py`; finite StateGraph, typed model/facts boundaries, AI-active guard, grounded policy path, fail-closed handoffs/errors; focused AI tests 11 passed |
| M3 | Persistent conversations, human handoff/inbox, AI stop on takeover | COMPLETE (SQLite/PostgreSQL synthetic runtime and browser flow verified; production unverified) | `backend/app/db/conversations.py`; `backend/app/services/in_memory.py`; `backend/app/api/app.py`; `backend/tests/backend/test_m3_support.py`; `frontend/src/api.ts`; `frontend/src/App.tsx`; `frontend/src/styles.css`; browser customer handoff/staff claim-reply-resolve flow passed |
| M4 | Refund review state/authorization + approval UI | COMPLETE (PostgreSQL synthetic runtime and browser approval verified; no payment provider) | `backend/app/db/refunds.py`; `backend/app/services/in_memory.py`; `backend/app/api/app.py`; `backend/tests/backend/test_m4_refunds.py`; `frontend/src/api.ts`; `frontend/src/App.tsx`; `frontend/src/styles.css`; browser approval displayed `APPROVED_EXTERNAL_ACTION_REQUIRED` |
| M5 | Full E2E verification, local Docker, GitHub CI, portfolio demo | COMPLETE (local synthetic/CI checks; Docker/PostgreSQL/browser unverified) | `backend/tests/test_v1_integration.py`; `.github/workflows/ci.yml`; integration test 1 passed; full backend suite 46 passed; frontend typecheck/build passed; no live services |
| M6 | Semantic policy retrieval through the customer investigation workflow | COMPLETE (customer API and PostgreSQL/pgvector runtime verified with deterministic embeddings; real model completed in M7) | `backend/app/ai/answer.py`; `backend/app/ai/investigation.py`; `backend/app/services/in_memory.py`; `backend/app/rag/pgvector_store.py`; `backend/migrations/`; `backend/app/rag/seed.py`; M6 API/RAG tests; customer API integration and PostgreSQL filters/threshold/order/repeatability covered |
| M7 | Real semantic embeddings and browser end-to-end verification | COMPLETE (local synthetic runtime; no live LLM/payment/production data) | Cached `sentence-transformers/all-MiniLM-L6-v2`; real 384-dimensional seed; semantic customer API; frontend resolution/citation display; Chrome CDP flow covering login/order lookup, answer, handoff, inbox, refund approval and resolve |
| M8 | Evidence-based lexical/FTS/semantic retrieval comparison | COMPLETE (offline benchmark; FTS not added to customer path) | `backend/app/rag/benchmark.py`; `backend/app/rag/fulltext.py`; `backend/tests/rag/test_benchmark.py`; `backend/tests/rag/test_fulltext*.py`; frozen 15-case comparison against PostgreSQL 16/pgvector |
| M8B | Safe workflow diagnostics and retrieval fallback visibility | COMPLETE (local synthetic runtime; no new external services) | `backend/app/diagnostics.py`; HTTP `X-Request-ID`; structured investigation completion/failure/fallback events; `backend/tests/test_diagnostics.py`; customer content is excluded from diagnostic events |

## Reusable implementation / test index
Update this small table **only when real code/tests exist**. This is the anti-duplication lookup before adding a new function or feature.

| Capability | Existing code path | Existing tests / command | Status |
|---|---|---|---|
| Demo authentication | `backend/app/api/app.py`; `backend/app/services/in_memory.py`; `backend/app/contracts.py` | `backend/tests/backend/test_m1_api.py`; `python -m pytest -q` | Implemented for synthetic `customer_001` only |
| Order lookup + ownership | `backend/app/services/in_memory.py::order_for_actor` | `backend/tests/backend/test_m1_api.py`; `python -m pytest -q` | Customer ownership and existence-hiding 404 verified |
| Widget conversation | `frontend/src/api.ts`; `frontend/src/App.tsx`; `backend/app/api/app.py` | `npm run typecheck`; `npm run build`; backend conversation tests | Deterministic M1 transcript; no AI answer yet |
| Policy retrieval | `backend/app/rag/corpus.py`; `backend/app/rag/retrieval.py`; `backend/app/rag/evaluation.py` | `backend/tests/rag/**`; `python -m pytest -q` | Offline lexical baseline with published/public filtering |
| Grounded policy answer | `backend/app/ai/answer.py` | `backend/tests/ai/**`; `python -m pytest -q` | Deterministic answer templates and weak-match handoff |
| Semantic embeddings / pgvector | `backend/app/rag/semantic.py`; `backend/app/rag/pgvector_store.py`; `backend/app/rag/seed.py`; `backend/migrations/`; `backend/requirements.txt` | `backend/tests/rag/test_semantic.py`; `backend/tests/rag/test_pgvector_integration.py`; local-files-only seed command; real five-case evaluation | Real local 384-dimensional embeddings seeded into PostgreSQL 16/pgvector 0.8.7; publication/audience filters and safe threshold behavior verified. Real semantic and lexical metrics were identical on the five-case synthetic corpus. |
| PostgreSQL FTS comparison | `backend/app/rag/fulltext.py`; `backend/app/rag/benchmark.py` | `backend/tests/rag/test_fulltext.py`; `backend/tests/rag/test_fulltext_integration.py`; `\.venv\Scripts\python.exe -m backend.app.rag.benchmark` | Benchmark-only native English `websearch_to_tsquery`, `ts_rank_cd`, and GIN expression index over the existing policy table; no customer production route |
| Workflow diagnostics | `backend/app/diagnostics.py`; `backend/app/api/app.py`; `backend/app/ai/investigation.py`; `backend/app/ai/answer.py` | `backend/tests/test_diagnostics.py`; `\.venv\Scripts\python.exe -m pytest -q backend\tests\test_diagnostics.py` | Server-generated correlation IDs and JSON events expose outcome, retrieval mode, evidence count, handoff/error categories, and elapsed time without logging customer content |
| LangGraph workflow | `backend/app/ai/investigation.py`; `backend/app/services/in_memory.py`; `backend/app/api/app.py`; `backend/requirements.txt` | `backend/tests/ai/test_investigation.py`; `backend/tests/backend/test_m6_investigation.py`; `\.venv\Scripts\python.exe -m pytest -q backend\tests\ai backend\tests\backend\test_m6_investigation.py` | Finite controlled workflow is used by the customer message route with injected policy retrieval, typed order-facts, safe lexical fallback and retrieval-mode reporting; no live model SDK or external calls |
| Live model SDK integration | - | - | Not implemented or verified; requires future owner-approved credentialed evaluation |
| Persistent conversations / human takeover | `backend/app/db/conversations.py`; `backend/app/services/in_memory.py`; `backend/app/api/app.py` | `backend/tests/backend/test_m3_support.py`; `backend/tests/backend/test_m6_investigation.py`; `\.venv\Scripts\python.exe -m pytest -q backend\tests\backend` | SQLAlchemy-backed local persistence, handoff/claim/reply/resolve transitions, server role/ownership checks, and conditional assistant append that refuses replies after takeover |
| Staff inbox UI | `frontend/src/api.ts`; `frontend/src/App.tsx`; `frontend/src/styles.css` | `npm.cmd run typecheck`; `npm.cmd run build` | Local demo support login, queue, claim, human reply and resolve controls |
| Refund review | `backend/app/db/refunds.py`; `backend/app/services/in_memory.py`; `backend/app/api/app.py`; `frontend/src/api.ts`; `frontend/src/App.tsx`; `frontend/src/styles.css` | `backend/tests/backend/test_m4_refunds.py`; `\.venv\Scripts\python.exe -m pytest -q backend\tests\backend`; `npm.cmd run typecheck`; `npm.cmd run build` | Support request, 5,000-cent synthetic limit, idempotency, separate approver decisions, terminal external-action-required/rejected states; no payment operation |

## Commands that have actually worked here
- `\.venv\Scripts\python.exe -m pytest -q` - 24 tests passed; one Starlette/HTTPX deprecation warning.
- `\.venv\Scripts\python.exe -m pytest -q` - 30 tests passed after M2S; no broken requirements reported by `pip check`.
- `\.venv\Scripts\python.exe -m pytest -q backend\tests\rag` - 17 focused RAG tests passed after M2S.
- `\.venv\Scripts\python.exe -m pytest -q` - 36 tests passed after M2L; `pip check` reported no broken requirements.
- `\.venv\Scripts\python.exe -m pytest -q backend\tests\ai\test_investigation.py backend\tests\ai\test_answer.py` - 11 focused AI tests passed after M2L.
- `\.venv\Scripts\python.exe -m pytest -q backend\tests\backend` - 10 focused backend M3 tests passed, including persistence, state transitions, authorization and sequence ordering.
- `\.venv\Scripts\python.exe -m pytest -q backend\tests\backend` - 15 focused backend M3/M4 tests passed after simulated refund review and approver-ID regression coverage.
- `\.venv\Scripts\python.exe -m pytest -q` - 45 tests passed after M4; `pip check` reported no broken requirements.
- `\.venv\Scripts\python.exe -m pytest -q backend\tests\test_v1_integration.py` - 1 synthetic cross-feature V1 flow passed.
- `\.venv\Scripts\python.exe -m pytest -q` - 46 tests passed after M5 integration coverage; `pip check` reported no broken requirements.
- `\.venv\Scripts\python.exe -m pytest -q backend\tests` - 57 tests passed and 5 opt-in PostgreSQL tests skipped because `RESOLVEAI_TEST_POSTGRES_URL` was not configured.
- `\.venv\Scripts\python.exe -m pytest -q backend\tests\ai backend\tests\backend\test_m6_investigation.py backend\tests\rag\test_semantic.py backend\tests\rag\test_pgvector_integration.py` - 27 tests passed and 5 PostgreSQL tests skipped after M6 integration/fallback/security fixes.
- `..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head --sql` from `backend/` - PostgreSQL migration SQL rendered successfully; no live database was contacted.
- `wsl.exe -d Ubuntu -- docker run ... pgvector/pgvector:pg16` - disposable `resolveai-m6-postgres` container started with `127.0.0.1:55432` binding; existing containers were not modified.
- Windows Python SQLAlchemy connectivity check - passed against PostgreSQL 16.16; pgvector extension reported version 0.8.7.
- `..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head` from `backend/` - applied revision `20261122_01`; a second upgrade was a successful no-op.
- [Historical M6-DB attempt] `..\.venv\Scripts\python.exe -m app.rag.seed` from `backend/` - did not seed because local-only `sentence-transformers/all-MiniLM-L6-v2` was not yet cached and network model loading was unavailable; no rows were inserted. M7 subsequently cached the official model once and verified the local-only seed path.
- Deterministic `seed_policy_embeddings` repeatability check against the same PostgreSQL database - two upserts left the same four rows unchanged; rows were 4, published 3, unpublished 1, internal 1, dimensions 384.
- `RESOLVEAI_TEST_POSTGRES_URL=... \.venv\Scripts\python.exe -m pytest -q backend\tests\rag\test_pgvector_integration.py` - 8 PostgreSQL integration tests passed, including the customer API path, publication/audience filters, threshold exclusion, stable tie ordering, and repeatability.
- `RESOLVEAI_TEST_POSTGRES_URL=... \.venv\Scripts\python.exe -m pytest -q backend\tests` - 68 backend tests passed with no PostgreSQL skips while the disposable database was running.
- One-time official model load with `SentenceTransformer(..., local_files_only=False)` - succeeded in the selected `.venv`; subsequent provider loads used `local_files_only=True` and produced 384-dimensional embeddings.
- M7 real seed command from `backend/` - first and second runs exited 0 against PostgreSQL 16/pgvector; a final real reseed was performed after deterministic regression tests restored real vectors for the quality check.
- M7 real semantic evaluation on the five frozen cases - `.\.venv\Scripts\python.exe -m backend.app.rag.semantic_eval` from the repository root against the seeded disposable PostgreSQL/pgvector database reported Recall@3 1.000, wrong-version exposure 0.000, citation/visibility accuracy 1.000, unsupported retrieval behavior 1.000; lexical baseline matched all four metrics.
- M7 live customer API smoke - natural-language shipment-delay request returned `retrieval_mode=semantic`, published `delivery-policy v2` evidence with score 0.6347, and the grounded answer; unsupported and refund requests preserved safe handoff behavior.
- M7 browser verification through Chrome CDP - customer login/order lookup, semantic answer/citation display, unsupported handoff, support claim/reply/resolve, synthetic refund request, separate approver approval, and terminal status display all passed. A genuine grounded-answer screenshot was captured and inspected privately in the system temp directory.
- `npm.cmd run typecheck` and `npm.cmd run build` after M7 UI fixes - both passed.
- M8 migration/seed preparation - Alembic current revision `20261122_01`; real local embedding seed completed successfully against disposable PostgreSQL 16/pgvector; the benchmark GIN expression index was present as `ix_policy_embeddings_policy_text_fts`.
- M8 PostgreSQL FTS integration checks - 3 FTS integration tests passed, covering customer publication/access filtering, staff internal visibility, irrelevant queries, and repeatability.
- M8 full backend regression with `RESOLVEAI_TEST_POSTGRES_URL=...` - 75 tests passed with no PostgreSQL skips; frontend typecheck and production build also passed.
- M8 frozen 15-case benchmark - lexical Recall@3/MRR `0.80/0.80`, answer-contract accuracy `0.867`; PostgreSQL FTS `0.30/0.30`, `0.533`; semantic pgvector `0.60/0.60`, `0.733`. All methods had unsupported behavior `1.0`, citation/access-control accuracy `1.0`, and wrong-version exposure `0.0`. Warm p50/p95 latencies were lexical `0.014/0.023 ms`, FTS `1.696/2.317 ms`, semantic `52.037/56.076 ms`.
- M8 recommendation - do not add PostgreSQL FTS to the customer investigation path; its strict all-terms behavior did not improve measured accuracy and added database latency. The lexical baseline remains the strongest aggregate result on this frozen synthetic set; semantic retrieval remains available behind the existing configured path and fallback.
- M8B focused diagnostics - `\.venv\Scripts\python.exe -m pytest -q backend\tests\test_diagnostics.py backend\tests\backend\test_m6_investigation.py backend\tests\ai\test_investigation.py backend\tests\ai\test_answer.py` - 23 tests passed after the independent review fixes. Customer message responses returned UUID correlation IDs; completion and semantic-fallback events recorded allowlisted metadata without the submitted customer text.
- M8B backend regression - `\.venv\Scripts\python.exe -m pytest -q backend\tests` - 67 passed and 11 opt-in PostgreSQL tests skipped because no disposable database was running; `pip check` and Python compilation passed.
- `npm.cmd run typecheck` in `frontend/` - passed after M3 staff inbox and customer handoff controls.
- `npm.cmd run build` in `frontend/` - passed after M3 staff inbox and customer handoff controls.
- `.github/workflows/ci.yml` - added local-only backend/frontend CI commands; workflow execution in GitHub is not claimed here.
- `\.venv\Scripts\python.exe -m compileall -q backend` - passed.
- Independent M6 read-only review - no actionable findings after fixes; conditional takeover guard and backend/seed command were rechecked.
- `npm install` in `frontend/` - 69 packages installed; audit reported 0 vulnerabilities.
- `npm run typecheck` in `frontend/` - passed.
- `npm run build` in `frontend/` - passed.
- `git diff --check` - passed.
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\notify.ps1 -Event test -Milestone M0` - `VOICE_OK`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\notify.ps1 -Event review -Milestone M1` - `VOICE_OK`.

## Current blockers / manual actions
- M2 is specifically the completed offline lexical retrieval baseline; it does not claim semantic RAG. M2S adds the semantic/pgvector implementation, M6-DB verifies deterministic PostgreSQL behavior, M7 verifies the real local model path, and M8 compares lexical, PostgreSQL FTS, and semantic retrieval. No paid or live model call is authorized.
- LangGraph’s controlled mocked workflow is implemented in M2L. Live model SDK integration remains outstanding and requires future owner-approved credentials/evaluation; no paid or live model call is authorized in local development.
- The verified disposable M8 PostgreSQL container has been removed. Repeatable runtime verification requires starting another isolated PostgreSQL/pgvector container and setting `RESOLVEAI_TEST_POSTGRES_URL`; the Windows host does not have a native `psql` client or PostgreSQL service.
- Real model loading is verified only for the selected local cache and synthetic corpus. No live LLM SDK, production credentials, commerce connector, or payment operation is verified.
- Browser verification used Chrome CDP and synthetic data; a standard committed browser-test runner is not yet part of CI.
- Lead milestone `done` voice attempts for M2S, M2L, M3, M4, and M5 were nonblocking but failed because the existing notifier could not write its deduplication stamp under the environment's local voice-history path; the notifier test itself previously returned `VOICE_OK`.
- Existing FastAPI TestClient emits a Starlette/HTTPX deprecation warning; tests still pass. Revisit when the dependency guidance stabilizes.

## Next bounded milestone
M8 and M8B are verified: the fair retrieval comparison does not justify PostgreSQL FTS in the customer path, and the investigation workflow now exposes safe correlation and fallback diagnostics. The next highest-value product milestone is expanding the synthetic policy corpus and challenge labels, then recalibrating semantic retrieval against broader vocabulary while preserving safe handoff; live model SDK integration remains owner-approved only. No paid/live model call is authorized.

## Update policy
After each **completed milestone**, the lead changes status, lists exact implementation/tests reused by next workers, records the test commands and results, the one next action, and any blocker. Do not rewrite this file after every keystroke. Investigate rather than repeat allegedly completed work when code and state differ.
