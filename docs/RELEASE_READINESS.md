# Local V1 Release Readiness

This checklist describes local evidence only. ResolveAI is not deployed and no
cloud account or paid provider call is enabled by this repository state.

| Gate | Status | Evidence / limitation |
|---|---|---|
| Backend regression | PASS | `pytest -q`: 295 passed, 39 intentional PostgreSQL/commerce skips |
| Frontend static verification | PASS | `npm.cmd run typecheck` and `npm.cmd run build` |
| Browser journeys | PASS (local) | 15/15 with the installed system Chrome; synthetic data only |
| Authentication/authorization and business safeguards | PASS for covered local cases | Backend and browser negative cases cover ownership, staff roles, handoff, refund approval boundaries, policy visibility and conflicts |
| Health/readiness | PASS for local process checks | `/healthz` and `/readyz` are covered; no hosted dependency claim |
| Secret protection | PASS | Private `.env` is ignored and untracked; backend-only `SecretStr` settings; provider errors/payload tests redact credentials |
| Deterministic customer path | PASS | External inference disabled, zero-cost mode enabled, quotas zero by default |
| PostgreSQL/pgvector | PASS (local M18-FIX) | Disposable PostgreSQL 16/pgvector migration reached `20261124_08 (head)`; broader backend-backed suite passed 324 with 1 intentional skip |
| Local load probes | PASS (bounded probe) | 10-second load/stress/soak results are in `BENCHMARKS.md`; not a capacity claim |
| Hosted model qualification | NOT RUN | The trusted synthetic evaluation factory and hard tranche limits are ready; no provider is qualified or active and no live generation was made |
| Real-model customer quality | NOT VERIFIED | Previous local Gemma quality gate did not pass; deterministic fallback remains default |
| Independent review | PASS (bounded safety gate) | Fresh read-only review accepted quota ceilings, conservative accounting, endpoint validation, candidate allowlisting, and customer/evaluation isolation; this is not production readiness |
| Deployment | NOT IN SCOPE | No push, merge, cloud resource, billing, or deployment was performed |

## Remaining local-V1 gates

1. Verify account-specific free entitlement, privacy, billing, and quota
   status before deciding whether to run the already authorized bounded
   Groq/Gemini synthetic tranche. The code gate is now complete, but this
   verification has not been claimed.
2. If the owner proceeds, reuse existing discovery results and do not access
   M16C holdouts or exceed the approved request/token limits.
3. Record model-level quality, structured-output, citation, safety, latency,
   usage, and fallback measurements. Do not activate an unqualified model.
4. Keep deterministic customer responses as the default until live quality
   evidence supports any change.

## Owner-only actions

- Confirm account-specific zero-cost/privacy/quota status in provider consoles
  or authoritative account responses before any live request. No provider
  credential values need to be placed in Git.
- Decide whether to consume the already authorized live budget; no additional
  budget is requested here.
