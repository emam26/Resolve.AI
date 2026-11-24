# Local V1 Release Readiness

This checklist describes local evidence only. ResolveAI is not deployed and no
cloud account or paid provider call is enabled by this repository state.

| Gate | Status | Evidence / limitation |
|---|---|---|
| Backend regression | PASS for current local tree | M20 rerun: `312 passed, 40 skipped`; the PostgreSQL-backed historical M19 result remains `341 passed, 1 intentional skip` |
| Frontend static verification | PASS | `npm.cmd run typecheck` and `npm.cmd run build` |
| Browser journeys | PASS (local, split evidence) | Existing suite `16/16` plus owner screenshot test `1/1` with installed system Chrome; synthetic data only. A later consolidated 17-test rerun timed out during runner shutdown and is not counted as a single 17/17 pass |
| Authentication/authorization and business safeguards | PASS for covered local cases; public deployment blocked | Ownership, staff roles, handoff, refund boundaries, policy visibility, session expiry and logout are covered. Demo sessions remain predictable synthetic identities and are not production authentication. |
| Health/readiness | PASS for local process checks | `/healthz` and `/readyz` are covered; no hosted dependency claim |
| Secret protection | PASS | Private `.env` is ignored and untracked; backend-only `SecretStr` settings; provider errors/payload tests redact credentials |
| Deterministic customer path | PASS | External inference disabled, zero-cost mode enabled, quotas zero by default |
| PostgreSQL/pgvector | HISTORICAL PASS; M20 rerun blocked | M19 disposable PostgreSQL 16/pgvector migration reached `20261124_09 (head)`; the M20 WSL rerun returned `Wsl/E_ACCESSDENIED` before a new database test could run |
| Local load probes | PASS (bounded probe) | 10-second load/stress/soak results are in `BENCHMARKS.md`; not a capacity claim |
| Hosted model qualification | NOT QUALIFIED | One Groq synthetic candidate was rejected after 1/6 application model-accepted answers; Gemini was excluded because free-tier privacy and exact model quota evidence were not sufficient |
| Real-model customer quality | NOT VERIFIED | Previous local Gemma quality gate did not pass; deterministic fallback remains default |
| Independent review | CONDITIONAL | M20 read-only review completed: stale memory-outage test was fixed; predictable demo authentication remains a public-deployment blocker; no production-readiness claim |
| Deployment | NOT IN SCOPE | No push, merge, cloud resource, billing, or deployment was performed |

## M20 owner-acceptance disposition

Local manual UAT can proceed at the URLs in
[`uat/OWNER_WALKTHROUGH.md`](uat/OWNER_WALKTHROUGH.md). Public deployment is
not approved: real authentication/session protection, admission rate limiting,
and migration-aware hosted readiness are still required. Hosted model
qualification remains blocked by the incomplete M19 usage ledger and the
absence of account-verified privacy/quota evidence for a new live tranche.

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
