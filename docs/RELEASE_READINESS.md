# Local V1 Release Readiness

This checklist describes local evidence only. ResolveAI is not deployed and no
cloud account or paid provider call is enabled by this repository state.

| Gate | Status | Evidence / limitation |
|---|---|---|
| Backend regression | PASS for current local tree | M20 rerun: `312 passed, 40 skipped`; the PostgreSQL-backed historical M19 result remains `341 passed, 1 intentional skip` |
| Frontend static verification | PASS | `npm.cmd run typecheck` and `npm.cmd run build` |
| Browser journeys | PASS (local, split evidence) | Existing suite `16/16` plus owner screenshot test `1/1` with installed system Chrome; synthetic data only. A later consolidated 17-test rerun timed out during runner shutdown and is not counted as a single 17/17 pass |
| Authentication/authorization and business safeguards | PASS for covered local cases; distributed deployment still blocked | M21 adds provisioned scrypt accounts, opaque expiring HttpOnly sessions, logout revocation, CSRF protection, CORS credential handling, login/request admission limits, and negative tests. Demo sessions remain predictable synthetic identities and are local-only. Admission state is process-local. |
| Health/readiness | PASS for local checks and fail-closed schema gate | `/healthz` remains liveness-only; `/readyz` checks PostgreSQL connectivity, required tables, and Alembic head `20261124_09` without running migrations. Real PostgreSQL M21 execution remains unavailable in the current Docker context. |
| Secret protection | PASS | Private `.env` is ignored and untracked; backend-only `SecretStr` settings; provider errors/payload tests redact credentials |
| Deterministic customer path | PASS | External inference disabled, zero-cost mode enabled, quotas zero by default |
| PostgreSQL/pgvector | HISTORICAL PASS; M21 runtime rerun unavailable | M19 disposable PostgreSQL 16/pgvector migration reached `20261124_09 (head)`. WSL/Docker is healthy now, but no `resolveai-m15-pg` container or `resolveai` volume exists in the current context; no M21 PostgreSQL pass is claimed. |
| Local load probes | PASS (bounded probe) | 10-second load/stress/soak results are in `BENCHMARKS.md`; not a capacity claim |
| Hosted model qualification | NOT QUALIFIED | One Groq synthetic candidate was rejected after 1/6 application model-accepted answers; Gemini was excluded because free-tier privacy and exact model quota evidence were not sufficient |
| Real-model customer quality | NOT VERIFIED | Previous local Gemma quality gate did not pass; deterministic fallback remains default |
| Independent review | CONDITIONAL PASS | The bounded read-only M21 review completed and accepted local fail-closed controls. It identified process-local sessions/admission and incomplete historical provider accounting as remaining blockers; the migration-head, malformed-token and cross-origin CSRF response-path fixes were lead-rechecked. |
| Deployment | NOT IN SCOPE | No push, merge, cloud resource, billing, or deployment was performed |

## M20 owner-acceptance disposition

Local manual UAT can proceed at the URLs in
[`uat/OWNER_WALKTHROUGH.md`](uat/OWNER_WALKTHROUGH.md). Public deployment is
not approved: deployment-scale shared admission storage, real PostgreSQL
runtime verification in this environment, and hosted model qualification
remain open. The M19 usage ledger is incomplete, so no new live provider
tranche is authorized by this work.

## Remaining local-V1 gates

1. Keep deterministic customer responses as the default; no hosted model is
   qualified or active.
2. A future hosted tranche needs conservative reconstruction of the M19 ledger
   or a separately approved budget, verified account-level free limits and
   privacy terms, then the trusted PostgreSQL quota factory.
3. A multi-instance deployment needs shared admission enforcement or an
   explicitly bounded single-instance topology.
4. Do not access protected holdouts or activate a provider from the M19 probe.

## Owner-only actions

- Confirm a privacy-compatible provider/model and account-level quota before
  authorizing any later live tranche. No credential values need to be placed
  in Git.
