# Bounded autonomous collaboration — Codex IDE

## Roles
- **Lead:** orchestrates and integrates; only lead edits shared contracts, root config, migrations that cross components, and status documents.
- **Backend worker:** assigned files in `backend/app/api/`, `backend/app/services/`, `backend/app/db/`, `backend/tests/backend/`.
- **AI/RAG worker:** assigned files in `backend/app/ai/`, `backend/app/rag/`, `backend/tests/ai/`, assigned policy fixtures.
- **Frontend worker:** assigned files in `frontend/`.
- **Reviewer (read-only):** reviews stable changed files, targeted tests, contracts, attack/edge cases, and simplicity; cannot commit/edit.
These are *suggested boundaries*: adopt existing repo layout rather than imposing unnecessary directory structure. Lead retains ownership over shared files (e.g. `pyproject.toml`, dependency locks, app bootstrap, OpenAPI, `.env.example`, CI).

## One milestone loop
1. **Reuse check:** lead consults `docs/PROJECT_STATE.md`, relevant source/tests and `.agents/skills/reuse-first/`; don't rebuild what exists.
2. **Freeze tiny contract:** agree endpoints, payloads, ownership, test/acceptance criteria. Identify dependencies.
3. **Delegate selectively:** spawn up to three writing workers **only if independent**; max concurrency is a *host capability*, not guaranteed. Assign disjoint file ownership. No worktree isolation is currently verified; context fork != filesystem fork. If workers need the same files, serialize those edits or isolate via verified Git worktrees.
4. **Communicate via lead:** workers raise blockers or contract changes to lead using session messaging; lead relays decisions. No undocumented peer-to-peer chat assumption.
5. **Continuous checkpoint review:** when a worker finishes a coherent, stable diff, let reviewer inspect it while other disjoint work continues. Don't inspect partially edited files mid-write or duplicate a finished review without new changes.
6. **Fix and verify:** lead confirms findings, sends fixes to owner, runs relevant narrow tests and integration checks. Two unsuccessful attempts on one issue trigger evidence-based reassessment; stop if genuinely blocked.
7. **Report once:** summarize built behavior, exact paths, tests actually run, reviewer findings, unverified items, required human steps. Update `docs/PROJECT_STATE.md` after verified milestone completion, not at every message.

## Reviewer checklist
- Correctness of business rules and state transitions.
- Cross-customer/role permission paths and demo-only identity restrictions.
- Evidence-supported RAG answer, citation/version isolation, failure/handoff.
- API/DB/frontend type parity, negative/failure tests, actual test results.
- Duplicate code, unnecessary classes/packages, expensive/mis-scoped tool calls and repeated analysis.
- Report only **actionable, evidenced** P0/P1/P2 findings with file locations and short fix options; say explicitly when no relevant issue found. Separate speculation from verified defect. **Do not alter files.**

## Approval / spending boundary
Lead can implement, test locally, and fix within authorized milestone without repeated human prompts. **Human authorization required** for external paid or authenticated services, significant new packages, destructive data operations, architecture changes, remote pushes/merges, deployments and production-like credentials. See `docs/MANUAL_ACTIONS.md`.

## Worker task packet fields
Outcome; existing work to reuse; owned files; forbidden shared files; frozen APIs and example response; fixtures; minimal tests; pass criteria; non-goals; block/stop conditions; result format. `prompts/WORKER_TASK_TEMPLATE.md` is reusable.

## Token guardrails
- No workers for tiny edits or strictly sequential tasks; don't keep agents idle and consuming tokens.
- Worker gets a short objective and relevant references, not whole project history.
- Reviewer sees a stable diff plus contract/tests, not an entire repeated repository briefing.
- Use local deterministic tests and compact output (`-q`, targeted file) before full suite.
- Avoid repeating already-verified checks without a relevant change.
- Agent overhead is nonzero; optimize for verified progress, not agent count.
