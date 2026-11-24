# ResolveAI — Reference UI / M21 integration handoff

**Status: locally integrated; owner visual acceptance pending.** The referenced `F:\ResolveAI-integration\` source directory was not present in this session. The existing root-worktree reconstruction was reviewed in place and retained the later M21 authentication, admission-control and provider-safety changes; no directory replacement was performed.

## Changes in this handoff

| File | Change |
|---|---|
| `frontend/src/App.tsx` | Provisioned account login gate, one production actor, role-specific navigation, case-scoped order evidence and follow-up navigation. Demo sessions remain independent in explicit local mode. |
| `frontend/src/api.ts` | Credentialed cookie requests in production mode, in-memory CSRF nonce from login, identity check via `/me`, no session token stored by JavaScript, new case-order and bounded policy-audit clients. Demo bearer requests omit cookies. |
| `frontend/src/DesignShell.tsx`, `redesign.css` | Role-aware menu and login styling consistent with the original teal/navy UI. |
| `frontend/src/ExtraSurface.tsx` | Support queue, case-linked orders, published policy catalog search/inspection and policy audit page wired to server contracts. |
| `backend/app/services/in_memory.py`, `backend/app/api/app.py` | Staff case-linked order lookup; do not expand customer-only `/orders/{order_id}`. Explicitly reject missing/empty CSRF cookie/header pair for cookie-authenticated mutations. |
| `backend/app/db/policies.py`, `backend/app/api/app.py` | Bounded recent policy audit query with merchant-admin authorization. |
| `backend/tests/backend/test_ui_integration_contracts.py` | New regression cases for scope/roles, audit bounds and missing CSRF values. |

No migration, new package dependency, provider change, external inference, deployment, or payment-write capability was added. Existing backend source and migrations are retained; the archive omits disposable caches. The application remains synthetic-data-first.

## Page map and limits

| Reference screen | Integration disposition |
|---|---|
| Overview | Existing operations summary and policy catalog. Current counts, not fabricated weekly trend. |
| Conversations | Existing support inbox/claim/reply/resolve; new case-linked order evidence. Persisted per-message citation/tool timeline is not exposed by the current inbox contract. |
| Support tickets | Follow-up view of authorized active support cases. No independent ticket entity, priority, SLA or ticket history service. |
| Refund approvals | Existing approval/rejection workflow. No external payment execution; financial balance and full audit evidence are not in response. |
| Orders | Select case-linked records; no unrestricted merchant order directory. |
| Knowledge base | Existing versioned policy CRUD, validation, indexing, publication, rollback and per-version audit. |
| Customer widget | Existing customer auth, order lookup, conversation and handoff, memory path server-owned. Standalone local preview remains a preview, not installed Shopify widget. |
| Retrieval playground | Search and inspect published catalog records through existing staff APIs; NOT a runtime retrieval trace, answer or model evaluation. |
| AI evaluations | Explicit unavailable/live-unverified state. Historical measured results remain in BENCHMARKS.md. |
| Merchant onboarding | Guided local setup, no real merchant/store provisioning. |
| Store integration | Explicit unverified read-only capability matrix; Shopify OAuth and live capabilities are future work. |
| Team & access | Existing read-only roster and permission data, not account administration. |
| Audit history | Recent persisted policy events (admin only), not a cross-domain event ledger. |
| Workspace settings | Existing read-only settings. |

UI-only role navigation is not authorization. The backend remains authoritative. Existing server permissions intentionally separate merchant admin, support and approver; the concept's broader navigation must not grant additional powers. In production-mode UI, switching actors requires signing out and signing in with a different provisioned account. Reload requires sign-in again; no session or CSRF value is persisted in browser storage. Hosted cross-origin cookie behavior and multi-tab/session-expiry workflows require further verification. Some prototype actions are intentionally unavailable to the current role.

## Verification (M22 local integration)

- TypeScript typecheck and native Vite production build: PASS.
- Python `compileall`: PASS.
- Root backend regression after M22 auth/state changes: see the current benchmark entry; PostgreSQL opt-in suites were run separately against the owner container and an isolated synthetic database.
- Real PostgreSQL: Alembic `20261124_10 (head)`, structured synthetic seed, 108 combined PG integration tests, readiness/API smoke: PASS.
- Browser: the configured system-Chrome suite passed 18 tests with 2 intentional production-mode skips; the focused production-auth recovery suite passed 2 tests separately. Browser execution used synthetic data only and one worker because the local API/admission state is shared.
- Reference screenshots were visually spot-checked against the approved dashboard/customer-widget direction. This is not pixel-perfect acceptance; owner approval is still required.
- The bounded independent M22 follow-up review passed the four remediation findings for production database enforcement, lifecycle PID safety, production Playwright isolation, and CSRF session recovery. It did not verify hosted-origin behavior.

## Owner integration instructions

1. If the missing source bundle is supplied later, extract it into a staging directory, not directly over a changing Git checkout. Compare/merge it against the current local branch. Preserve root `.env`, `.venv`, `AGENTS.md`, scripts, databases, Docker volumes and unrelated changes. M22's auth-state migration is already present as `20261124_10`.
2. Reuse the existing Python environment or install backend requirements into that environment. Run `python -m pytest backend/tests/backend/test_ui_integration_contracts.py backend/tests/backend/test_m21_auth_boundary.py -q` using the project virtualenv from root, then the full regression and PostgreSQL tests. Resolve all failures before acceptance.
3. From frontend, use `npm.cmd ci`, `npm.cmd run typecheck`, `npm.cmd run build`, and the project Playwright command. `npm ci` recreates node_modules; `dist` is generated by build.
4. Start documented local services; explicitly set `VITE_AUTH_MODE=demo` for a local synthetic preview. Inspect all 14 reference pages and confirm actual behavior. To exercise provisioned login, configure synthetic test accounts privately in backend settings, disable demo auth and set `VITE_AUTH_MODE=production` before starting/building frontend. Do not expose account credentials or private backend config through Vite variables.
5. Review exact visual comparison, functional tests, and the independent security review before any deployment. Hosted cross-origin cookie compatibility, hosted model eligibility/accounting and owner visual approval remain open; local PostgreSQL session/admission verification is complete for the tested synthetic database.

The source archive contains no review screenshots folder. Keep historical visual review material outside runtime source if desired. Do not overwrite newer concurrent M21+ changes blindly.
