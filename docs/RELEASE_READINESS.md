# Local V1 Release Readiness

> **M23 local status: RELEASE_CANDIDATE_READY_FOR_OWNER_APPROVAL.** The public
> product presentation and deployment configuration are locally verified, but
> hosted cross-origin/browser behavior, owner visual approval, real-merchant
> data, and hosted model qualification remain open gates. See [UI integration
> handoff](UI_INTEGRATION_HANDOFF.md).

This checklist describes local evidence only. ResolveAI is not deployed and no
cloud account or paid provider call is enabled by this repository state.

| Gate | Status | Evidence / limitation |
|---|---|---|
| Backend regression | PASS for current local tree | M23 full suite: `344 passed, 42 skipped`; PostgreSQL-specific checks are reported separately rather than hidden in a historical count |
| Frontend static verification | PASS | `npm.cmd run typecheck` and `npm.cmd run build` |
| Browser journeys | PASS (local, owner UAT pending) | Current serialized system-Chrome suite `18 passed, 3 skipped`; focused production-auth/mobile suite `3 passed`; synthetic data only. Hosted cross-origin cookie behavior is not claimed |
| Authentication/authorization and business safeguards | PASS for tested local PostgreSQL boundary; deployment boundary remains | M22 adds provisioned scrypt accounts with PostgreSQL-backed opaque sessions, global logout/replay protection and atomic admission across two app instances. Demo sessions remain predictable synthetic identities and are local-only |
| Health/readiness | PASS for local checks and fail-closed schema/commerce gate | `/healthz` remains liveness-only; `/readyz` checks PostgreSQL connectivity, configured commerce connectivity, actual required tables, and Alembic head `20261124_10` without running migrations. The future Render probe is `/readyz` |
| Secret protection | PASS | Private `.env` is ignored and untracked; backend-only `SecretStr` settings; provider errors/payload tests redact credentials |
| Deterministic customer path | PASS | External inference disabled, zero-cost mode enabled, quotas zero by default |
| PostgreSQL/pgvector | PASS for current isolated local verification | Existing `resolveai-local-dev-postgres` (`pgvector/pgvector:pg16`, `127.0.0.1:55436`) reached `20261124_10`; 108 integration tests passed against isolated synthetic `resolveai_m16db` |
| Local load probes | PASS (bounded probe) | 10-second load/stress/soak results are in `BENCHMARKS.md`; not a capacity claim |
| Hosted model qualification | NOT QUALIFIED | One Groq synthetic candidate was rejected after 1/6 application model-accepted answers; Gemini was excluded because free-tier privacy and exact model quota evidence were not sufficient |
| Real-model customer quality | NOT VERIFIED | Previous local Gemma quality gate did not pass; deterministic fallback remains default |
| Independent review | CONDITIONAL PASS; fixes lead-verified | M23 read-only review found the `/healthz` Render probe, missing production commerce-source requirement, production actor-ID presentation, and architecture-session wording. All four were fixed and rerun through focused/full checks; no second post-fix independent review is claimed |
| Deployment configuration | READY as a non-deploying template | `render.yaml` uses `/readyz`, auto-deploy is off, and secrets/database URLs remain dashboard-managed. No cloud resource, billing, or hosted migration was performed |
| Hosted verification | PENDING | Actual Cloudflare Pages origin, Render service, Neon database, cookie/CSRF behavior, backups, migration execution, and hosted readiness remain unverified |
| Live AI qualification | PENDING / CLOSED BY DEFAULT | No hosted model is qualified or active; deterministic generation remains the customer default |
| Real merchant pilot | NOT READY | The app remains synthetic-data-first with no Shopify, payment, or real-customer integration |

## M20 owner-acceptance disposition

Local manual UAT can proceed at the URLs in
[`uat/OWNER_WALKTHROUGH.md`](uat/OWNER_WALKTHROUGH.md). Public deployment is
not approved: hosted cross-origin cookie behavior, owner visual acceptance and
hosted model qualification remain open. The M19 usage ledger is incomplete, so
no new live provider tranche is authorized by this work.

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
