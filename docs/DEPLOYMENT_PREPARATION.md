# Deployment preparation (not a deployment)

ResolveAI is currently a local, synthetic-data V1. This document records the
smallest preparation checklist for a later deployment to the previously chosen
Neon + Render + Cloudflare Pages architecture. No cloud resource, billing
change, database migration, or hosted deployment has been performed or verified
by this repository.

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
RESOLVEAI_CORS_ORIGINS=https://<Cloudflare Pages hostname>
RESOLVEAI_DEMO_AUTH_ENABLED=false
RESOLVEAI_AUTH_SECRET_KEY=<private rotated secret>
RESOLVEAI_PRODUCTION_AUTH_ENABLED=true
RESOLVEAI_PRODUCTION_AUTH_USERS_JSON=<private JSON of provisioned scrypt hashes>
RESOLVEAI_PRODUCTION_SESSION_TTL_SECONDS=3600
RESOLVEAI_TRUSTED_PROXY_IPS=<only the explicitly trusted proxy CIDRs>
RESOLVEAI_SUPPORTED_ALEMBIC_HEAD=20261124_09
RESOLVEAI_EXTERNAL_INFERENCE_ENABLED=false
RESOLVEAI_ZERO_COST_MODE=true
RESOLVEAI_PROVIDER_REQUEST_QUOTA=0
RESOLVEAI_PROVIDER_TOKEN_QUOTA=0
```

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

Admission controls are bounded per process. They are suitable for a single
local process, but a multi-instance deployment still requires shared admission
storage or an edge limit before it can claim distributed brute-force
protection. `/readyz` fails closed when PostgreSQL is unavailable, required
tables are missing, or `alembic_version` is not `20261124_09`; it never runs a
migration.

For the static frontend, configure only the public API origin:

```text
VITE_API_BASE_URL=https://<Render API hostname>
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
