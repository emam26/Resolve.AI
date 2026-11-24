# Deployment preparation (not a deployment)

ResolveAI is currently a local, synthetic-data V1. This document records the
smallest preparation checklist for a later deployment to the previously chosen
Neon + Render + Cloudflare Pages architecture. No cloud resource, billing
change, database migration, or hosted deployment has been performed or verified
by this repository.

The checked-in [`render.yaml`](../render.yaml) is a non-deploying Render
Blueprint template. It intentionally uses `autoDeployTrigger: off`, leaves
secrets as dashboard-managed values, and does not run migrations automatically.
Review it before using it with an owner-approved service.

## Target topology

| Component | Future target | Current evidence |
| --- | --- | --- |
| Database | Neon PostgreSQL with `vector`/pgvector support | Local PostgreSQL 16/pgvector only |
| API | Render-hosted FastAPI/Uvicorn service | Local Uvicorn only |
| Frontend | Cloudflare Pages static Vite build | Local Vite only |

The backend must be the only component that receives provider credentials. Do
not put API keys in Vite variables, browser storage, source files, or support
messages.

## Local commands used by this repository

From `F:\ResolveAI`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
Set-Location frontend
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

The verified local checks are:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests
Set-Location frontend
npm.cmd run typecheck
npm.cmd run build
```

For a PostgreSQL deployment or staging database, apply the checked-in schema
from `backend/` only after reviewing the target and taking its backup:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
```

The current Alembic head must be inspected with `alembic current`; do not use a
destructive automatic downgrade as a deployment rollback. A rollback requires a
separate reviewed change and an explicitly selected previous revision.

The synthetic commerce importer and policy seed are local verification tools,
not production data loaders. Their commands and safeguards are documented in
[`DATASET.md`](DATASET.md) and the policy seed module. Do not import the local
operational dataset into a hosted database without a separate privacy and
ownership decision.

## Environment checklist

Create the backend environment in the service's private environment store or a
local root `.env` that is never committed. Start from [`.env.example`](../.env.example)
and keep optional external inference disabled until a separately approved,
account-verified evaluation exists.

For a future hosted API, review at least:

```text
RESOLVEAI_ENVIRONMENT=production
RESOLVEAI_DATABASE_URL=<Neon PostgreSQL URL with pgvector>
RESOLVEAI_COMMERCE_DATABASE_URL=<approved Neon commerce schema URL>
RESOLVEAI_CORS_ORIGINS=https://<Cloudflare Pages hostname>
RESOLVEAI_DEMO_AUTH_ENABLED=false
RESOLVEAI_AUTH_SECRET_KEY=<private rotated secret>
RESOLVEAI_PRODUCTION_AUTH_ENABLED=true
RESOLVEAI_PRODUCTION_AUTH_USERS_JSON=<private JSON of provisioned scrypt hashes>
RESOLVEAI_PRODUCTION_SESSION_TTL_SECONDS=3600
RESOLVEAI_TRUSTED_PROXY_IPS=<only the explicitly trusted proxy CIDRs>
RESOLVEAI_SUPPORTED_ALEMBIC_HEAD=20261124_10
RESOLVEAI_EXTERNAL_INFERENCE_ENABLED=false
RESOLVEAI_ZERO_COST_MODE=true
RESOLVEAI_PROVIDER_REQUEST_QUOTA=0
RESOLVEAI_PROVIDER_TOKEN_QUOTA=0
```

The Render service should use the repository's Python build and start commands:

```text
Build:  pip install -r backend/requirements.txt
Start:  uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
Health: /readyz (Render dependency health check)
Liveness: /healthz
```

Production startup requires `RESOLVEAI_COMMERCE_DATABASE_URL`; without it the
application refuses to start rather than serving local synthetic order
fixtures. It may point to the same approved Neon database when the imported
`commerce_*` tables are present.

On Render's free web plan, the service can sleep after 15 minutes without
inbound traffic and its local filesystem is ephemeral. Free Render Postgres is
limited to 1 GB, has no backups, and expires after 30 days. Render documents
that `preDeployCommand` is available only for paid web services, so free-plan
migrations must be run separately from a trusted release environment before
traffic is admitted. These are platform limitations, not local ResolveAI test
results.

For the static frontend, Cloudflare Pages' documented Vite defaults are
`npm run build` and `dist`. Configure `VITE_API_BASE_URL` and
`VITE_AUTH_MODE=production` as Pages build variables only. The generated build
contains public configuration only; provider credentials and database/session
secrets belong exclusively to the Render backend.

Neon is the planned PostgreSQL provider. Confirm pgvector availability, use its
TLS connection string, and choose a pooled connection option appropriate for
the deployed web service. Run the migration from a controlled release
environment, then verify the exact head and `/readyz`; never use the service's
startup path to silently mutate an unknown database.

Authoritative platform references checked for this preparation:

- [Cloudflare Pages Vite build configuration](https://developers.cloudflare.com/pages/configuration/build-configuration/)
- [Render FastAPI deployment](https://render.com/docs/deploy-fastapi)
- [Render environment variables and secrets](https://render.com/docs/configure-environment-variables)
- [Render health checks](https://render.com/docs/health-checks)
- [Render free-instance limitations](https://render.com/docs/free)
- [Render Blueprint reference](https://render.com/docs/blueprint-spec)
- [Neon pgvector extension](https://neon.com/docs/extensions/pgvector)
- [Neon application connections](https://neon.com/docs/connect/connect-from-any-app)

Local M21 verification adds a provisioned-account path at
`POST /api/v1/auth/login`. Accounts are configured only in the backend through
`RESOLVEAI_PRODUCTION_AUTH_USERS_JSON`; each account contains a username,
actor/role fields and a password hash generated with the repository's
`backend.app.services.auth.hash_password` helper. The server issues an opaque,
expiring HttpOnly cookie and a CSRF cookie for browser mutations; the login
response also returns the non-secret CSRF nonce so a separately hosted
frontend can retain it in memory when the API-domain cookie is not
script-readable. Cross-origin clients must send credentials and the CSRF
header. Do not place
plaintext passwords, password hashes, or session tokens in Vite variables,
localStorage, logs, or Git. The synthetic demo login remains local-only and
must stay disabled in production.

When provisioned production authentication uses PostgreSQL, sessions and
admission windows are shared and revocable across app instances. SQLite/demo
mode intentionally remains process-local and synthetic-only. `/readyz` fails
closed when PostgreSQL is unavailable, any required table is missing, or
`alembic_version` is not `20261124_10`; it never runs a migration. A hosted
deployment still needs an explicit PostgreSQL connection and browser
cross-origin validation before claiming readiness.

For the static frontend, configure only the public API origin:

```text
VITE_API_BASE_URL=https://<Render API hostname>
VITE_AUTH_MODE=production
```

Never expose `GROQ_API_KEY`, `GEMINI_API_KEY`, or any other provider credential
through `VITE_*` variables. The default deterministic customer path requires no
provider credentials and makes no external inference calls.

## Health and operational boundaries

The local process endpoints are:

- `GET /healthz`: process health check.
- `GET /readyz`: local dependency/readiness check.

The readiness check verifies the configured database, required ResolveAI tables,
and expected Alembic revision. A deployment should still run migrations as a
reviewed release step and verify readiness before admitting traffic.

ResolveAI does not write refunds to a payment provider. An approved refund
ends at `APPROVED_EXTERNAL_ACTION_REQUIRED`. Cloud deployment, billing,
provider qualification, hosted database operations, and external payment
actions remain unverified and out of scope for local V1.

For local synthetic UAT use `VITE_AUTH_MODE=demo`. The reconstructed frontend
production mode requires explicit provisioned login and keeps the non-secret
CSRF nonce in memory. Local session expiry behavior is browser-tested; actual
separately hosted cookie behavior remains unverified. See
`UI_INTEGRATION_HANDOFF.md` before any deployment.
