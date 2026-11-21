# ResolveAI - one living milestone / reuse index

**Last verified by:** ResolveAI Lead (local source/tests/Git). **Date:** 2026-11-21. This file is an *index*, not evidence by itself. On opening the project, compare it with actual Git/source/test state; correct discrepancies. Do not mark work completed without inspecting and/or executing checks.

## Current workspace (Lead-verified)
- Root guidance, product docs, prompt templates, local skills, design references, and the existing `scripts/notify.ps1` are present.
- Git is initialized locally; there is no remote or Git worktree. The current milestone changes are being committed locally only.
- `j.py` was not present during these inspections; it was not recreated or removed.
- A local `.venv` contains the approved M1 development set: FastAPI, Uvicorn, HTTPX, pytest, and Pydantic. Frontend dependencies are installed from `frontend/package.json` and locked in `frontend/package-lock.json`.
- No paid LLM, embedding, commerce, authenticated external API, or deployment action was performed. Docker/PostgreSQL are unavailable in this environment.

## Milestones (update after actual verification)
| ID | Outcome | Status | Reuse / proof |
|---|---|---|---|
| M0 | Git + context + first frozen contract + minimal runnable skeleton | COMPLETE | `backend/app/contracts.py`; 7 contract tests; baseline commits `1457f53` and `5af5afa` |
| M1 | Demo identity + customer-scoped synthetic order lookup + simple widget inquiry | COMPLETE | FastAPI M1 routes/services/tests and React widget; full Python suite 24 passed; frontend typecheck/build passed; review findings fixed |
| M2 | Published policy RAG + retrieval evaluation + grounded agent answer | COMPLETE (offline lexical baseline) | `backend/app/rag/**`; `backend/app/ai/**`; 5 predeclared evaluation cases; Recall@3 1.0, wrong-version exposure 0.0, citation/visibility accuracy 1.0, unsupported-answer behavior 1.0; weak-overlap handoff reviewed |
| M3 | Persistent conversations, human handoff/inbox, AI stop on takeover | NOT STARTED | No persistence or staff workflow |
| M4 | Refund review state/authorization + approval UI | NOT STARTED | No refund workflow |
| M5 | Full E2E verification, local Docker, GitHub CI, portfolio demo | NOT STARTED | No Docker/CI/deployment verification |

## Reusable implementation / test index
Update this small table **only when real code/tests exist**. This is the anti-duplication lookup before adding a new function or feature.

| Capability | Existing code path | Existing tests / command | Status |
|---|---|---|---|
| Demo authentication | `backend/app/api/app.py`; `backend/app/services/in_memory.py`; `backend/app/contracts.py` | `backend/tests/backend/test_m1_api.py`; `python -m pytest -q` | Implemented for synthetic `customer_001` only |
| Order lookup + ownership | `backend/app/services/in_memory.py::order_for_actor` | `backend/tests/backend/test_m1_api.py`; `python -m pytest -q` | Customer ownership and existence-hiding 404 verified |
| Widget conversation | `frontend/src/api.ts`; `frontend/src/App.tsx`; `backend/app/api/app.py` | `npm run typecheck`; `npm run build`; backend conversation tests | Deterministic M1 transcript; no AI answer yet |
| Policy retrieval | `backend/app/rag/corpus.py`; `backend/app/rag/retrieval.py`; `backend/app/rag/evaluation.py` | `backend/tests/rag/**`; `python -m pytest -q` | Offline lexical baseline with published/public filtering |
| Grounded policy answer | `backend/app/ai/answer.py` | `backend/tests/ai/**`; `python -m pytest -q` | Deterministic answer templates and weak-match handoff |
| Semantic embeddings / pgvector / PostgreSQL FTS | - | - | Not implemented or verified |
| LangGraph + model SDK | - | - | Not implemented or verified |
| Human takeover | - | - | Not built |
| Refund review | - | - | Not built |

## Commands that have actually worked here
- `\.venv\Scripts\python.exe -m pytest -q` - 24 tests passed; one Starlette/HTTPX deprecation warning.
- `\.venv\Scripts\python.exe -m compileall -q backend` - passed.
- `npm install` in `frontend/` - 69 packages installed; audit reported 0 vulnerabilities.
- `npm run typecheck` in `frontend/` - passed.
- `npm run build` in `frontend/` - passed.
- `git diff --check` - passed.
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\notify.ps1 -Event test -Milestone M0` - `VOICE_OK`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\notify.ps1 -Event review -Milestone M1` - `VOICE_OK`.

## Current blockers / manual actions
- M2's sentence-transformers/semantic retrieval, pgvector, PostgreSQL full-text comparison, LangGraph, and model SDK integration remain intentionally unimplemented and unverified; no paid or live model call is authorized.
- Docker is unavailable, so PostgreSQL-backed persistence and production-like integration are not yet verifiable.
- No browser/manual widget flow was run; local API and frontend builds are verified independently.
- Existing FastAPI TestClient emits a Starlette/HTTPX deprecation warning; tests still pass. Revisit when the dependency guidance stabilizes.

## Next bounded milestone
**M3:** add persistent conversation storage and staff handoff/inbox behavior, preserving the M1 ownership contract and enforcing `AI_ACTIVE -> HANDOFF_QUEUED -> HUMAN_ACTIVE -> RESOLVED`; no automated reply is allowed in `HUMAN_ACTIVE`. Begin with a contract freeze and local deterministic persistence tests, then address PostgreSQL verification when the environment permits.

## Update policy
After each **completed milestone**, the lead changes status, lists exact implementation/tests reused by next workers, records the test commands and results, the one next action, and any blocker. Do not rewrite this file after every keystroke. Investigate rather than repeat allegedly completed work when code and state differ.
