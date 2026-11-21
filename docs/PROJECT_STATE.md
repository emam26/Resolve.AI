# ResolveAI - one living milestone / reuse index

**Last verified by:** ResolveAI Lead (local source/tests/Git). **Date:** 2026-11-21. This file is an *index*, not evidence by itself. On opening the project, compare it with actual Git/source/test state; correct discrepancies. Do not mark work completed without inspecting and/or executing checks.

## Current workspace (Lead-verified)
- Root guidance, product docs, prompt templates, local skills, and design references are present.
- Git was initialized locally with baseline commit `1457f53`; there is no remote or worktree yet.
- `j.py` was not present during this inspection; it was not recreated or removed.
- The first dependency-light backend contract models and tests now exist under `backend/`.
- Pydantic 2.13.5 and HTTPX are available. FastAPI, SQLAlchemy, Alembic, and pytest are not installed; Docker is unavailable. No dependency was installed and no paid/external API was called.
- The Codex IDE session exposes `spawn_agent`, `send_input`, `wait_agent`, `resume_agent`, and `close_agent`. It does **not** confirm Git worktree isolation or persistent custom agent profiles.

## Milestones (update after actual verification)
| ID | Outcome | Status | Reuse / proof |
|---|---|---|---|
| M0 | Git + context + first frozen contract + minimal runnable skeleton | COMPLETE | `docs/CONTRACTS.md`; `backend/app/contracts.py`; `backend/tests/test_contracts.py`; 5 built-in unittest cases passed; bytecode compilation passed |
| M1 | Demo identity + customer-scoped synthetic order lookup + simple widget inquiry | NOT STARTED | No endpoint or widget implementation |
| M2 | Published policy RAG + retrieval evaluation + grounded agent answer | NOT STARTED | No code/tests |
| M3 | Persistent conversations, human handoff/inbox, AI stop on takeover | NOT STARTED | No code/tests |
| M4 | Refund review state/authorization + approval UI | NOT STARTED | No code/tests |
| M5 | Full E2E verification, local Docker, GitHub CI, portfolio demo | NOT STARTED | No code/tests |

## Reusable implementation / test index
Update this small table **only when real code/tests exist**. This is the anti-duplication lookup before adding a new function or feature.

| Capability | Existing code path | Existing tests / command | Status |
|---|---|---|---|
| Demo authentication | `backend/app/contracts.py` (`DemoLoginRequest`, `DemoLoginResponse`, `ActorSummary`) | `backend/tests/test_contracts.py::test_demo_login_response_matches_frozen_shape`; `python -m unittest discover -s backend/tests -v` | Contract only; endpoint not built |
| Order lookup + authorization | `backend/app/contracts.py` (`OrderSummary`) | `backend/tests/test_contracts.py::test_order_summary_serializes_iso_date`; `python -m unittest discover -s backend/tests -v` | Contract only; persistence/authorization not built |
| Policy index/search | - | - | Not built |
| LangGraph + tool calling | - | - | Not built |
| Widget | - | - | Not built |
| Human takeover | - | - | Not built |
| Refund review | - | - | Not built |

## Commands that have actually worked here
- `python -m unittest discover -s backend/tests -v` - 5 tests passed.
- `python -m compileall -q backend` - passed.

When additional tooling is approved and available, record verified narrow commands such as FastAPI/HTTPX tests, frontend typecheck/build, database seed, and browser E2E; include operating environment and necessary setup. Never paste raw secrets or long logs here.

## Current blockers / manual actions
- M1 endpoint implementation needs an approved local FastAPI/SQLAlchemy/Alembic/test environment; these dependencies were intentionally not installed during M0.
- Docker is unavailable, so PostgreSQL-backed verification is not yet possible here.
- User handles live model/API credentials and paid calls; no paid model evaluation is authorized by this starter.

## Next bounded milestone
**M1:** after the owner provides or approves the local backend/frontend dependency environment, freeze the remaining conversation/widget handshake and implement demo identity plus customer-scoped synthetic order lookup. Delegate only independent work packets with disjoint file ownership; AI/RAG is not needed for this first order slice.

## Update policy
After each **completed milestone**, the lead changes status, lists exact implementation/tests reused by next workers, records the test commands and results, the one next action, and any blocker. Do not rewrite this file after every keystroke. Investigate rather than repeat allegedly completed work when code and state differ.
