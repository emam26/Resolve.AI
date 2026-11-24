# M19 local owner walkthrough

This is a local synthetic-data walkthrough. It does not deploy, call a paid
service, or connect to a real merchant.

## Start the application

From `F:\ResolveAI` in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location frontend
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`. The backend health and readiness endpoints are
`http://127.0.0.1:8000/healthz` and `http://127.0.0.1:8000/readyz`.

## Synthetic walkthrough

1. Start the customer session and use `order_1001`. Select **Check order
   status** to verify the server-authorized delayed order, then open the
   conversation.
2. Ask **Are delivery dates guaranteed?** and confirm the grounded answer,
   citation, retrieval mode, and deterministic generation badge.
3. Ask an unsupported question and confirm the safe human-review handoff.
4. Start the support session as `support_001`, claim the queued conversation,
   reply as a human, and resolve it. The customer composer stays blocked after
   takeover.
5. Create a synthetic refund-review request. In the separate approver surface,
   sign in as `refund_approver_001` and approve or reject it. Approval ends at
   `APPROVED_EXTERNAL_ACTION_REQUIRED`; no payment operation occurs.
6. For the workspace demo, use `merchant_admin_001` to inspect the policy
   catalog and the existing policy-management controls.

The demo actors are fixed synthetic identities. They are not production
authentication and do not authorize access to real customer data.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests
Set-Location frontend
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test:e2e
```

The browser suite uses the existing cached Chromium executable when the IDE
shell cannot resolve the normal Playwright browser install. No browser or
provider dependency should be downloaded for this walkthrough.

Cloud deployment, cloud databases, billing, external customer data, and live
provider traffic remain intentionally out of scope for local V1 verification.
