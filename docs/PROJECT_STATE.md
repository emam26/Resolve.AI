# ResolveAI - one living milestone / reuse index

**Last verified by:** ResolveAI Lead (local source/tests/Git). **Date:** 2026-11-22. This file is an *index*, not evidence by itself. On opening the project, compare it with actual Git/source/test state; correct discrepancies. Do not mark work completed without inspecting and/or executing checks.

## Current workspace (Lead-verified)
- Root guidance, product docs, prompt templates, local skills, design references, and the existing `scripts/notify.ps1` are present.
- Git is initialized locally and the verified V1 work is published on the dedicated `codex/v1-local-complete` branch at `origin`; no additional Git worktree is used.
- `j.py` was not present during these inspections; it was not recreated or removed.
- A local `.venv` contains the approved backend set: FastAPI, Uvicorn, HTTPX, pytest, Pydantic, SQLAlchemy, Alembic, pgvector, psycopg, sentence-transformers, and LangGraph. Frontend dependencies are installed from `frontend/package.json` and locked in `frontend/package-lock.json`.
- No paid LLM, embedding, commerce, authenticated external API, or deployment action was performed. Docker Engine was used only through Ubuntu WSL for the disposable M6 PostgreSQL verification container; it was removed after testing.

## Milestones (update after actual verification)
| ID | Outcome | Status | Reuse / proof |
|---|---|---|---|
| M0 | Git + context + first frozen contract + minimal runnable skeleton | COMPLETE | `backend/app/contracts.py`; 7 contract tests; baseline commits `1457f53` and `5af5afa` |
| M1 | Demo identity + customer-scoped synthetic order lookup + simple widget inquiry | COMPLETE | FastAPI M1 routes/services/tests and React widget; full Python suite 24 passed; frontend typecheck/build passed; review findings fixed |
| M2 | Published policy RAG + retrieval evaluation + grounded agent answer | COMPLETE (offline lexical baseline) | `backend/app/rag/**`; `backend/app/ai/**`; 5 predeclared evaluation cases; Recall@3 1.0, wrong-version exposure 0.0, citation/visibility accuracy 1.0, unsupported-answer behavior 1.0; weak-overlap handoff reviewed |
| M2S | Semantic policy retrieval foundation | COMPLETE (offline implementation; real model loading unverified; PostgreSQL runtime verified in M6-DB) | `backend/app/rag/semantic.py`; `backend/app/rag/pgvector_store.py`; `backend/tests/rag/test_semantic.py`; lazy sentence-transformers adapter, deterministic cosine retrieval, 0.65 sufficiency gate, 384-dimension pgvector query builder; focused semantic tests passed |
| M2L | Controlled LangGraph investigation workflow with mocked model responses | COMPLETE (mocked/local workflow; live model unverified) | `backend/app/ai/investigation.py`; `backend/tests/ai/test_investigation.py`; finite StateGraph, typed model/facts boundaries, AI-active guard, grounded policy path, fail-closed handoffs/errors; focused AI tests 11 passed |
| M3 | Persistent conversations, human handoff/inbox, AI stop on takeover | COMPLETE (local SQLAlchemy/SQLite verified; PostgreSQL/browser unverified) | `backend/app/db/conversations.py`; `backend/app/services/in_memory.py`; `backend/app/api/app.py`; `backend/tests/backend/test_m3_support.py`; `frontend/src/api.ts`; `frontend/src/App.tsx`; `frontend/src/styles.css`; 10 focused backend tests and full suite passed |
| M4 | Refund review state/authorization + approval UI | COMPLETE (local simulated review verified; no payment provider) | `backend/app/db/refunds.py`; `backend/app/services/in_memory.py`; `backend/app/api/app.py`; `backend/tests/backend/test_m4_refunds.py`; `frontend/src/api.ts`; `frontend/src/App.tsx`; `frontend/src/styles.css`; 15 focused backend tests and full suite passed |
| M5 | Full E2E verification, local Docker, GitHub CI, portfolio demo | COMPLETE (local synthetic/CI checks; Docker/PostgreSQL/browser unverified) | `backend/tests/test_v1_integration.py`; `.github/workflows/ci.yml`; integration test 1 passed; full backend suite 46 passed; frontend typecheck/build passed; no live services |
| M6 | Semantic policy retrieval through the customer investigation workflow | COMPLETE (customer API and PostgreSQL/pgvector runtime verified with deterministic embeddings; real sentence-transformers seed unverified) | `backend/app/ai/answer.py`; `backend/app/ai/investigation.py`; `backend/app/services/in_memory.py`; `backend/app/rag/pgvector_store.py`; `backend/migrations/`; `backend/app/rag/seed.py`; M6 API/RAG tests; customer API integration and PostgreSQL filters/threshold/order/repeatability covered |

## Reusable implementation / test index
Update this small table **only when real code/tests exist**. This is the anti-duplication lookup before adding a new function or feature.

| Capability | Existing code path | Existing tests / command | Status |
|---|---|---|---|
| Demo authentication | `backend/app/api/app.py`; `backend/app/services/in_memory.py`; `backend/app/contracts.py` | `backend/tests/backend/test_m1_api.py`; `python -m pytest -q` | Implemented for synthetic `customer_001` only |
| Order lookup + ownership | `backend/app/services/in_memory.py::order_for_actor` | `backend/tests/backend/test_m1_api.py`; `python -m pytest -q` | Customer ownership and existence-hiding 404 verified |
| Widget conversation | `frontend/src/api.ts`; `frontend/src/App.tsx`; `backend/app/api/app.py` | `npm run typecheck`; `npm run build`; backend conversation tests | Deterministic M1 transcript; no AI answer yet |
| Policy retrieval | `backend/app/rag/corpus.py`; `backend/app/rag/retrieval.py`; `backend/app/rag/evaluation.py` | `backend/tests/rag/**`; `python -m pytest -q` | Offline lexical baseline with published/public filtering |
| Grounded policy answer | `backend/app/ai/answer.py` | `backend/tests/ai/**`; `python -m pytest -q` | Deterministic answer templates and weak-match handoff |
| Semantic embeddings / pgvector | `backend/app/rag/semantic.py`; `backend/app/rag/pgvector_store.py`; `backend/app/rag/seed.py`; `backend/migrations/`; `backend/requirements.txt` | `backend/tests/rag/test_semantic.py`; `backend/tests/rag/test_pgvector_integration.py`; `RESOLVEAI_TEST_POSTGRES_URL=... \.venv\Scripts\python.exe -m pytest -q backend\tests\rag\test_pgvector_integration.py` | In-memory and PostgreSQL retrievers enforce published/audience filters, score thresholds and deterministic ordering; Alembic and deterministic upsert repeatability verified against PostgreSQL 16.16/pgvector 0.8.7. Real sentence-transformers model loading remains unverified because the local model is not cached. |
| PostgreSQL FTS comparison | - | - | Not implemented or verified |
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
- `..\.venv\Scripts\python.exe -m app.rag.seed` from `backend/` - intentionally did not seed: local-only `sentence-transformers/all-MiniLM-L6-v2` was not cached and network model loading was unavailable; no claim of real model loading is made.
- Deterministic `seed_policy_embeddings` repeatability check against the same PostgreSQL database - two upserts left the same four rows unchanged; rows were 4, published 3, unpublished 1, internal 1, dimensions 384.
- `RESOLVEAI_TEST_POSTGRES_URL=... \.venv\Scripts\python.exe -m pytest -q backend\tests\rag\test_pgvector_integration.py` - 8 PostgreSQL integration tests passed, including the customer API path, publication/audience filters, threshold exclusion, stable tie ordering, and repeatability.
- `RESOLVEAI_TEST_POSTGRES_URL=... \.venv\Scripts\python.exe -m pytest -q backend\tests` - 65 backend tests passed with no PostgreSQL skips while the disposable database was running.
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
- M2 is specifically the completed offline lexical retrieval baseline; it does not claim semantic RAG. M2S adds the semantic/pgvector implementation, and M6-DB verifies its PostgreSQL path with deterministic embeddings. The real sentence-transformers model seed remains unverified because the local model is not cached; PostgreSQL full-text comparison remains outstanding. No paid or live model call is authorized.
- LangGraph’s controlled mocked workflow is implemented in M2L. Live model SDK integration remains outstanding and requires future owner-approved credentials/evaluation; no paid or live model call is authorized in local development.
- The verified disposable PostgreSQL container has been removed. Repeatable runtime verification requires starting another isolated PostgreSQL/pgvector container and setting `RESOLVEAI_TEST_POSTGRES_URL`; the Windows host does not have a native `psql` client or PostgreSQL service.
- The local-files-only sentence-transformers seed command still requires the configured model to be present in the local cache; it failed with a Hugging Face cache/connectivity error during M6-DB and inserted no rows.
- No browser/manual widget flow was run; local API and frontend builds are verified independently.
- M3/M4 PostgreSQL execution/migrations and browser/manual flow remain unverified; the local SQLAlchemy tests use SQLite.
- Lead milestone `done` voice attempts for M2S, M2L, M3, M4, and M5 were nonblocking but failed because the existing notifier could not write its deduplication stamp under the environment's local voice-history path; the notifier test itself previously returned `VOICE_OK`.
- Existing FastAPI TestClient emits a Starlette/HTTPX deprecation warning; tests still pass. Revisit when the dependency guidance stabilizes.

## Next bounded milestone
M6-DB is verified for the customer API and deterministic PostgreSQL/pgvector path. The next highest-value local milestone is PostgreSQL full-text baseline comparison and evaluation against semantic retrieval; separately, a real sentence-transformers smoke/seed run can be performed when the approved model is available in the local cache. No paid/live model call is authorized.

## Update policy
After each **completed milestone**, the lead changes status, lists exact implementation/tests reused by next workers, records the test commands and results, the one next action, and any blocker. Do not rewrite this file after every keystroke. Investigate rather than repeat allegedly completed work when code and state differ.
