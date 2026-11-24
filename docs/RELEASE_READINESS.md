# Local V1 Release Readiness

This checklist describes local evidence only. ResolveAI is not deployed and no
cloud account or paid provider call is enabled by this repository state.

| Gate | Status | Evidence / limitation |
|---|---|---|
| Backend regression | PASS | `pytest -q`: 269 passed, 37 intentional PostgreSQL/commerce skips |
| Frontend static verification | PASS | `npm.cmd run typecheck` and `npm.cmd run build` |
| Browser journeys | PASS (local) | 15/15 with the installed system Chrome; synthetic data only |
| Authentication/authorization and business safeguards | PASS for covered local cases | Backend and browser negative cases cover ownership, staff roles, handoff, refund approval boundaries, policy visibility and conflicts |
| Health/readiness | PASS for local process checks | `/healthz` and `/readyz` are covered; no hosted dependency claim |
| Secret protection | PASS | Private `.env` is ignored and untracked; backend-only `SecretStr` settings; provider errors/payload tests redact credentials |
| Deterministic customer path | PASS | External inference disabled, zero-cost mode enabled, quotas zero by default |
| PostgreSQL/pgvector | HISTORICAL PASS | M15/M16 evidence is recorded in `PROJECT_STATE.md`; this checkpoint did not rerun the disposable database suite |
| Local load probes | PASS (bounded probe) | 10-second load/stress/soak results are in `BENCHMARKS.md`; not a capacity claim |
| Hosted model qualification | BLOCKED | No model is qualified or active; live generation was withheld because the required independent critical-boundary review timed out |
| Real-model customer quality | NOT VERIFIED | Previous local Gemma quality gate did not pass; deterministic fallback remains default |
| Independent review | INCOMPLETE | Three bounded reviewer/specialist attempts timed out; no timeout is treated as approval |
| Deployment | NOT IN SCOPE | No push, merge, cloud resource, billing, or deployment was performed |

## Remaining local-V1 gates

1. Obtain a completed independent review of the provider, quota, privacy,
   authorization, and output-cap boundary.
2. Re-run the already authorized, bounded Groq/Gemini synthetic tranche only
   after that review. Reuse existing discovery results; do not access M16C
   holdouts or exceed the approved request/token limits.
3. Record model-level quality, structured-output, citation, safety, latency,
   usage, and fallback measurements. Do not activate an unqualified model.
4. Rerun PostgreSQL integration verification if the provider-control change is
   integrated with the real database path; SQLite and mocked tests are not a
   substitute for that gate.

## Owner-only actions

- Resolve or provide an execution environment in which the bounded independent
  review can complete. No provider credential values need to be placed in Git.
- After review completion, explicitly decide whether the already authorized
  live budget should be consumed; no further budget is requested here.
