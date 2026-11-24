# ResolveAI — reference-driven frontend reconstruction (integration candidate)

This React/TypeScript/Vite source replaces the previous combined support page with the merchant-console layout from `ResolveAI_UI_Redesign_v2.html`. The original dependencies are retained. The API client now integrates the supplied M21 provisioned-account contract and narrow staff case-order / policy-audit endpoints. This remains an integration candidate, not a verified production or payment release.

## Local run (Windows)

From the repository root, start the existing backend using its documented environment. In a second PowerShell:

```powershell
cd F:\ResolveAI\frontend
npm.cmd ci
npm.cmd run typecheck
npm.cmd run build
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/` (overview). The Vite `/api` proxy defaults to `http://127.0.0.1:8000`; an alternative API origin can be set through `VITE_API_BASE_URL`.

Local demo roles are established through the existing backend endpoints. Navigation exposes separate pages, not a client-side permission grant. Staff inbox is `?surface=support`, approver queue `?surface=refunds`, merchant storefront preview `?surface=widget-preview`, and isolated customer-only widget `?surface=widget`. The remaining routes are `overview`, `tickets`, `orders`, `knowledge`, `playground`, `evaluations`, `onboarding`, `integrations`, `team`, `audit`, and `settings`.

## Verification

```powershell
npm.cmd run typecheck
npm.cmd run build
$env:RESOLVEAI_PLAYWRIGHT_EXECUTABLE = "C:\Program Files\Google\Chrome\Application\chrome.exe"
npm.cmd run test:e2e
```

The existing E2E tests were updated for separate page navigation; they have not passed against the real backend in this handoff. Browser fixture screenshots are not end-to-end verification. No production auth, hosted model qualification, or deployment claim is made.

## Authentication modes and current integration gaps

Use `VITE_AUTH_MODE=demo` for the local synthetic walkthrough. For provisioned account testing, use `VITE_AUTH_MODE=production` and the backend M21 account settings with demo authentication disabled. Production-mode requests send credentials, retain the returned CSRF nonce in memory, and check `/me`; the browser never receives an API session bearer in this mode. Reload requires signing in again. Hosted cookie behavior must be verified independently.

The support ticket page is a case follow-up view, the order page uses case-linked lookups, and audit history reads policy audit events. The playground inspects published catalog records; it is not a runtime retrieval test. Dedicated ticket/SLA storage, unrestricted order directory, full case evidence, live AI evaluation results, Shopify authorization, unified audit, account management and settings writes remain unavailable. See `../docs/UI_INTEGRATION_HANDOFF.md` for contracts, changed files, current verification and remaining release gates.
