# Local V1 Release Readiness

This checklist describes local evidence only. ResolveAI is not deployed and no
cloud account or paid provider call is enabled by this repository state.

| Gate | Status | Evidence / limitation |
|---|---|---|
| Backend regression | PASS | M19 default suite: 305 passed, 40 intentional PostgreSQL/commerce skips; PostgreSQL-backed suite: 341 passed, 1 intentional skip |
| Frontend static verification | PASS | `npm.cmd run typecheck` and `npm.cmd run build` |
| Browser journeys | PASS (local) | M19 suite: 16/16 with the existing cached Chromium executable; synthetic data only |
| Authentication/authorization and business safeguards | PASS for covered local cases | Backend and browser negative cases cover ownership, staff roles, handoff, refund approval boundaries, policy visibility and conflicts |
| Health/readiness | PASS for local process checks | `/healthz` and `/readyz` are covered; no hosted dependency claim |
| Secret protection | PASS | Private `.env` is ignored and untracked; backend-only `SecretStr` settings; provider errors/payload tests redact credentials |
| Deterministic customer path | PASS | External inference disabled, zero-cost mode enabled, quotas zero by default |
| PostgreSQL/pgvector | PASS (local M19) | Disposable PostgreSQL 16/pgvector migration reached `20261124_09 (head)`; memory restart/ownership checks and broader backend-backed suite passed 341 with 1 intentional skip |
| Local load probes | PASS (bounded probe) | 10-second load/stress/soak results are in `BENCHMARKS.md`; not a capacity claim |
| Hosted model qualification | NOT QUALIFIED | One Groq synthetic candidate was rejected after 1/6 application model-accepted answers; Gemini was excluded because free-tier privacy and exact model quota evidence were not sufficient |
| Real-model customer quality | NOT VERIFIED | Previous local Gemma quality gate did not pass; deterministic fallback remains default |
| Independent review | PASS with fixes | M18-FIX safety review passed; M19 review findings on memory integration and output-capacity routing were fixed and re-reviewed; no production-readiness claim |
| Deployment | NOT IN SCOPE | No push, merge, cloud resource, billing, or deployment was performed |

## Remaining local-V1 gates

1. Keep deterministic customer responses as the default; no hosted model is
   qualified or active.
2. A future hosted tranche needs verified account-level free limits and privacy
   terms, then must use the trusted PostgreSQL quota factory.
3. Do not access protected holdouts or activate a provider from the M19 probe.

## Owner-only actions

- Confirm a privacy-compatible provider/model and account-level quota before
  authorizing any later live tranche. No credential values need to be placed
  in Git.
