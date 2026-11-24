# ResolveAI local owner walkthrough

This walkthrough uses only synthetic ResolveAI data. It is for manual local
inspection of the current V1 surfaces; it is not a production-authentication,
payment, cloud-deployment, or hosted-model acceptance record.

## Open the running application

The expected local URLs are:

| Surface | URL |
| --- | --- |
| Customer/staff application | http://127.0.0.1:5173/ |
| Customer-only widget | http://127.0.0.1:5173/?surface=widget |
| Backend API | http://127.0.0.1:8000/ |
| Backend health | http://127.0.0.1:8000/healthz |
| Backend readiness | http://127.0.0.1:8000/readyz |

If the services are not running, use separate PowerShell terminals from
`F:\ResolveAI`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location frontend
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

Stop only the processes started for this walkthrough. Do not remove
`resolveai-live.db`, local PostgreSQL volumes, or unrelated Docker resources.

## Synthetic demo identities

Use the visible **Start Demo ... session** controls. The existing synthetic
IDs are:

| Role | Demo ID | Allowed walkthrough |
| --- | --- | --- |
| Customer | `customer_001` | Own synthetic orders and conversations |
| Support agent | `support_001` | Inbox, claim, human reply, refund-review request |
| Refund approver | `refund_approver_001` | Separate refund approval/rejection |
| Merchant admin | `merchant_admin_001` | Workspace, policy catalog and lifecycle controls |

There are no passwords for these local demo sessions. The server still checks
role and customer ownership, but the demo login and predictable synthetic
identities are not suitable for public deployment.

## Customer-to-resolution path

1. Open the main URL and start the customer session.
2. Enter `order_1001` and open the widget conversation. The record is synthetic
   and should remain customer-scoped.
3. Ask `Are delivery dates guaranteed?`. Confirm that the answer is grounded,
   includes a policy citation, and shows the deterministic/local retrieval
   mode rather than claiming a live model call.
4. Ask an unsupported question, such as `What is your password reset policy?`.
   Confirm that the application recommends human review and does not invent a
   policy answer or citation.
5. Request human support. In the support surface, start `support_001`, claim
   the queued conversation, send a human reply, and resolve it. After takeover,
   autonomous customer replies remain blocked.
6. Create a refund review from the human-active support conversation. In the
   separate refund surface, start `refund_approver_001` and approve or reject
   the request. Approval must display
   `APPROVED_EXTERNAL_ACTION_REQUIRED`; no payment operation is performed.

## Workspace and policy inspection

1. Open the overview surface and start the merchant-admin session.
2. Inspect the synthetic operations summary, policy catalog, version detail,
   team, and settings panels.
3. If editing/publishing controls are available in the current local database,
   use a disposable fictional draft only. Confirm revision conflicts, failed
   indexing, publication/version filtering, and audit history before treating a
   change as accepted.

## Evidence and limitations

The local backend uses the existing synthetic data and deterministic answer
path by default. Semantic PostgreSQL retrieval and the cached local embedding
model are available only when the documented local configuration is selected.
Hosted Groq/Gemini models are not qualified or active, and no new live
generation should be run without a durable usage ledger and verified account
limits. The owner walkthrough does not claim browser behavior that has not
been observed in the current running session.

For automated evidence, see [`BENCHMARKS.md`](../BENCHMARKS.md),
[`PROJECT_STATE.md`](../PROJECT_STATE.md), and the screenshots in this
directory. Screenshots are synthetic UI evidence, not production claims.
