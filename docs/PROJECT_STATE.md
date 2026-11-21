# ResolveAI - one living milestone / reuse index

**Last verified by:** ResolveAI Lead (local source/tests/Git). **Date:** 2026-11-21. This file is an *index*, not evidence by itself. On opening the project, compare it with actual Git/source/test state; correct discrepancies. Do not mark work completed without inspecting and/or executing checks.

## Current workspace (Lead-verified)
- Root guidance, product docs, prompt templates, local skills, design references, and the existing `scripts/notify.ps1` are present.
- Git is initialized locally; there is no remote or Git worktree. The current milestone changes are being committed locally only.
- `j.py` was not present during these inspections; it was not recreated or removed.
- A local `.venv` contains the approved backend set: FastAPI, Uvicorn, HTTPX, pytest, Pydantic, SQLAlchemy, Alembic, pgvector, psycopg, sentence-transformers, and LangGraph. Frontend dependencies are installed from `frontend/package.json` and locked in `frontend/package-lock.json`.
- No paid LLM, embedding, commerce, authenticated external API, or deployment action was performed. Docker/PostgreSQL are unavailable in this environment.

## Milestones (update after actual verification)
| ID | Outcome | Status | Reuse / proof |
|---|---|---|---|
| M0 | Git + context + first frozen contract + minimal runnable skeleton | COMPLETE | `backend/app/contracts.py`; 7 contract tests; baseline commits `1457f53` and `5af5afa` |
| M1 | Demo identity + customer-scoped synthetic order lookup + simple widget inquiry | COMPLETE | FastAPI M1 routes/services/tests and React widget; full Python suite 24 passed; frontend typecheck/build passed; review findings fixed |
| M2 | Published policy RAG + retrieval evaluation + grounded agent answer | COMPLETE (offline lexical baseline) | `backend/app/rag/**`; `backend/app/ai/**`; 5 predeclared evaluation cases; Recall@3 1.0, wrong-version exposure 0.0, citation/visibility accuracy 1.0, unsupported-answer behavior 1.0; weak-overlap handoff reviewed |
| M2S | Semantic policy retrieval foundation | COMPLETE (offline implementation; live model/DB unverified) | `backend/app/rag/semantic.py`; `backend/app/rag/pgvector_store.py`; `backend/tests/rag/test_semantic.py`; lazy sentence-transformers adapter, deterministic cosine retrieval, 0.65 sufficiency gate, 384-dimension pgvector query builder; focused RAG tests 17 passed |
| M2L | Controlled LangGraph investigation workflow with mocked model responses | COMPLETE (mocked/local workflow; live model unverified) | `backend/app/ai/investigation.py`; `backend/tests/ai/test_investigation.py`; finite StateGraph, typed model/facts boundaries, AI-active guard, grounded policy path, fail-closed handoffs/errors; focused AI tests 11 passed |
| M3 | Persistent conversations, human handoff/inbox, AI stop on takeover | COMPLETE (local SQLAlchemy/SQLite verified; PostgreSQL/browser unverified) | `backend/app/db/conversations.py`; `backend/app/services/in_memory.py`; `backend/app/api/app.py`; `backend/tests/backend/test_m3_support.py`; `frontend/src/api.ts`; `frontend/src/App.tsx`; `frontend/src/styles.css`; 10 focused backend tests and full suite passed |
| M4 | Refund review state/authorization + approval UI | COMPLETE (local simulated review verified; no payment provider) | `backend/app/db/refunds.py`; `backend/app/services/in_memory.py`; `backend/app/api/app.py`; `backend/tests/backend/test_m4_refunds.py`; `frontend/src/api.ts`; `frontend/src/App.tsx`; `frontend/src/styles.css`; 15 focused backend tests and full suite passed |
| M5 | Full E2E verification, local Docker, GitHub CI, portfolio demo | COMPLETE (local synthetic/CI checks; Docker/PostgreSQL/browser unverified) | `backend/tests/test_v1_integration.py`; `.github/workflows/ci.yml`; integration test 1 passed; full backend suite 46 passed; frontend typecheck/build passed; no live services |

## Reusable implementation / test index
Update this small table **only when real code/tests exist**. This is the anti-duplication lookup before adding a new function or feature.

| Capability | Existing code path | Existing tests / command | Status |
|---|---|---|---|
| Demo authentication | `backend/app/api/app.py`; `backend/app/services/in_memory.py`; `backend/app/contracts.py` | `backend/tests/backend/test_m1_api.py`; `python -m pytest -q` | Implemented for synthetic `customer_001` only |
| Order lookup + ownership | `backend/app/services/in_memory.py::order_for_actor` | `backend/tests/backend/test_m1_api.py`; `python -m pytest -q` | Customer ownership and existence-hiding 404 verified |
| Widget conversation | `frontend/src/api.ts`; `frontend/src/App.tsx`; `backend/app/api/app.py` | `npm run typecheck`; `npm run build`; backend conversation tests | Deterministic M1 transcript; no AI answer yet |
| Policy retrieval | `backend/app/rag/corpus.py`; `backend/app/rag/retrieval.py`; `backend/app/rag/evaluation.py` | `backend/tests/rag/**`; `python -m pytest -q` | Offline lexical baseline with published/public filtering |
| Grounded policy answer | `backend/app/ai/answer.py` | `backend/tests/ai/**`; `python -m pytest -q` | Deterministic answer templates and weak-match handoff |
| Semantic embeddings / pgvector | `backend/app/rag/semantic.py`; `backend/app/rag/pgvector_store.py`; `backend/requirements.txt` | `backend/tests/rag/test_semantic.py`; `\.venv\Scripts\python.exe -m pytest -q backend\tests\rag` | Offline adapter, deterministic in-memory retrieval and parameterized PostgreSQL/pgvector query builder implemented; live PostgreSQL/model loading not verified |
| PostgreSQL FTS comparison | - | - | Not implemented or verified |
| LangGraph workflow | `backend/app/ai/investigation.py`; `backend/requirements.txt` | `backend/tests/ai/test_investigation.py`; `\.venv\Scripts\python.exe -m pytest -q backend\tests\ai` | Finite controlled workflow with injected mocked model and typed order-facts tool; no live model SDK or external calls |
| Live model SDK integration | - | - | Not implemented or verified; requires future owner-approved credentialed evaluation |
| Persistent conversations / human takeover | `backend/app/db/conversations.py`; `backend/app/services/in_memory.py`; `backend/app/api/app.py` | `backend/tests/backend/test_m3_support.py`; `\.venv\Scripts\python.exe -m pytest -q backend\tests\backend` | SQLAlchemy-backed local persistence, handoff/claim/reply/resolve transitions, server role/ownership checks, no assistant reply in human state |
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
- `npm.cmd run typecheck` in `frontend/` - passed after M3 staff inbox and customer handoff controls.
- `npm.cmd run build` in `frontend/` - passed after M3 staff inbox and customer handoff controls.
- `.github/workflows/ci.yml` - added local-only backend/frontend CI commands; workflow execution in GitHub is not claimed here.
- `\.venv\Scripts\python.exe -m compileall -q backend` - passed.
- `npm install` in `frontend/` - 69 packages installed; audit reported 0 vulnerabilities.
- `npm run typecheck` in `frontend/` - passed.
- `npm run build` in `frontend/` - passed.
- `git diff --check` - passed.
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\notify.ps1 -Event test -Milestone M0` - `VOICE_OK`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\notify.ps1 -Event review -Milestone M1` - `VOICE_OK`.

## Current blockers / manual actions
- M2 is specifically the completed offline lexical baseline; it does not claim semantic RAG. M2S adds the semantic/pgvector implementation and deterministic tests, but actual sentence-transformers model loading, PostgreSQL execution/migrations, and PostgreSQL full-text comparison remain unverified or outstanding. No paid or live model call is authorized.
- LangGraph’s controlled mocked workflow is implemented in M2L. Live model SDK integration remains outstanding and requires future owner-approved credentials/evaluation; no paid or live model call is authorized in local development.
- Docker is unavailable, so PostgreSQL-backed persistence and production-like integration are not yet verifiable.
- No browser/manual widget flow was run; local API and frontend builds are verified independently.
- M3/M4 PostgreSQL execution/migrations and browser/manual flow remain unverified; the local SQLAlchemy tests use SQLite.
- Lead milestone `done` voice attempts for M2S, M2L, M3, M4, and M5 were nonblocking but failed because the existing notifier could not write its deduplication stamp under the environment's local voice-history path; the notifier test itself previously returned `VOICE_OK`.
- Existing FastAPI TestClient emits a Starlette/HTTPX deprecation warning; tests still pass. Revisit when the dependency guidance stabilizes.

## Next bounded milestone
No further local V1 coding milestone is authorized or required. Human/environment follow-up is limited to running Docker/PostgreSQL migrations, a browser/manual flow, and any owner-approved live model evaluation; none is claimed complete here.

## Update policy
After each **completed milestone**, the lead changes status, lists exact implementation/tests reused by next workers, records the test commands and results, the one next action, and any blocker. Do not rewrite this file after every keystroke. Investigate rather than repeat allegedly completed work when code and state differ.
