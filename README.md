<p align="center">
  <img src="docs/design/app-icon-192.png" alt="ResolveAI" width="72" />
</p>

<p align="center"><strong>Support that remembers.</strong></p>

# ResolveAI

ResolveAI is an intelligent customer-operations application for a fictional online merchant. It combines a customer support widget, authenticated order context, policy retrieval, human support workflows, and controlled refund review in one small, testable vertical slice.

The repository is deliberately synthetic-data-first. It demonstrates the boundaries and safety rules needed for customer operations without connecting to a real merchant, payment provider, customer dataset, or paid model API.

## Release status

| Area | Status |
| --- | --- |
| Public product presentation | Locally ready for owner review |
| Backend and frontend release configuration | Prepared, not deployed |
| Local PostgreSQL/pgvector verification | Passed against synthetic data |
| Hosted authentication and browser behavior | Not verified |
| Hosted generative model qualification | Not qualified; deterministic assistance remains the default |

### Product preview

These screenshots show locally verified synthetic product surfaces. They are
representative UI evidence, not proof of a hosted deployment.

| Workspace | Customer support | Knowledge management |
| --- | --- | --- |
| ![Workspace overview](docs/uat/screenshots/workspace-overview.png) | ![Customer widget](docs/uat/screenshots/customer-widget.png) | ![Knowledge management](docs/uat/screenshots/knowledge-management.png) |

## Why ResolveAI

Customer requests often cross several systems and levels of responsibility: a shopper needs an order update, a policy must be applied, a support agent may need to take over, and a refund may require separate approval. A useful system must keep those steps connected while preserving ownership, evidence, and human control.

ResolveAI addresses that workflow with:

- server-established demo identity and customer-scoped order access;
- published-policy retrieval with evidence and conservative handoff behavior;
- persistent conversation states that stop autonomous replies after takeover;
- a support inbox for claiming, replying to, and resolving cases; and
- a human-controlled refund review lifecycle with separation of duties.

## Current capabilities

| Capability | Current implementation | Verification status |
| --- | --- | --- |
| Customer widget | React/TypeScript/Vite UI with local synthetic login or provisioned production login, order selection, transcript, and human-handoff control | Local API and frontend checks pass; hosted browser behavior is unverified |
| Staff console | Support inbox, claim/reply/resolve controls, support-side refund-review request form, and refund-approver view | Local API and frontend checks pass |
| Operations workspace | Authorized overview metrics, recent activity, read-only policy catalog, and merchant-admin team/settings view | PostgreSQL-backed API tests and browser checks pass locally |
| Embeddable widget mode | Customer-only `?surface=widget` route reusing the server-established demo session boundary | Eight local Playwright checks pass with an explicit system Chrome executable |
| Identity and authorization | Server-issued synthetic sessions for local demo mode plus PostgreSQL-backed provisioned sessions, role checks, CSRF protection, and customer order ownership checks | Covered by backend and local PostgreSQL tests |
| Conversations | SQLAlchemy-backed conversation and message persistence; SQLite is the default local database | SQLite and disposable PostgreSQL runtime exercised locally; no production database |
| Policy answering | Deterministic lexical retrieval over a small versioned policy corpus with published/visibility filtering and citations | Offline baseline verified |
| Semantic retrieval | Sentence-transformers adapter, deterministic cosine retriever, pgvector retriever, publication-safe query, migration, and seed helper | Real 384-dimensional local embeddings seeded into pgvector; customer API and browser path verified locally |
| Investigation workflow | Bounded LangGraph workflow with typed order facts, injected policy retrieval, evidence validation, and deterministic fallback | Deterministic local workflow and customer API path verified; no hosted model is qualified |
| Optional local answer model | Local-only Transformers adapter behind the existing validated `PolicyAnswerProvider` boundary | Disabled by default; adapter contract tested, but no cached generative model smoke test yet |
| Refund review | Backend API and staff console support pending requests, stable idempotency, separate approver decisions, and an external-action-required terminal state | Local synthetic flow verified; no payment operation |

## Customer-to-resolution workflow

The main supported path is:

1. In local demo mode, a synthetic customer requests the allowlisted `customer_001` actor. In production mode, a provisioned account signs in through the server-issued HttpOnly session path. Both paths enforce server-side role and ownership; the demo path is never enabled for production.
2. The customer opens a widget conversation, optionally associated with seeded order `order_1001`, and sends a message. The API runs the bounded investigation workflow: authorized order questions use typed order facts, while policy questions use the configured semantic retriever or the deterministic lexical fallback.
3. A grounded response includes only published, audience-visible policy evidence. Irrelevant, unsupported, refund, and unavailable-tool cases return a safe handoff result without an invented answer. The customer can then request human support, moving the conversation from `AI_ACTIVE` to `HANDOFF_QUEUED`.
4. A synthetic support agent signs in as `support_001`, claims the queued case, and replies as a human. The state becomes `HUMAN_ACTIVE`, which blocks autonomous replies.
5. While the case is human-active, the support agent can prepare a synthetic refund review in the staff console, subject to the local eligibility rules and a 5,000-cent limit.
6. A separate `refund_approver_001` actor can approve or reject the request. Approval produces `APPROVED_EXTERNAL_ACTION_REQUIRED`; it never moves money and never records `REFUNDED`.
7. After the human work is complete, the support agent can resolve the conversation, moving it from `HUMAN_ACTIVE` to `RESOLVED`.

The local widget route uses a deterministic classifier and controlled model boundary; it does not call a hosted LLM. Semantic retrieval is opt-in for a PostgreSQL database through `RESOLVEAI_POLICY_RETRIEVAL=semantic`. The sentence-transformers model is loaded from the local cache only. If that backend or local model is unavailable, the policy answer layer falls back to the lexical baseline and never presents that fallback as a semantic success.

## System architecture

```mermaid
flowchart LR
    Customer[Customer] --> Widget[React customer widget]
    Staff[Support agent] --> Console[React staff console]
    Approver[Refund approver] --> Console

    Widget -->|JSON + demo Bearer or production cookie/CSRF session| API[FastAPI API]
    Console -->|JSON + demo Bearer or production cookie/CSRF session| API

    API --> Auth[Server identity, role, and ownership checks]
    API --> Conversations[Conversation and state service]
    API --> Refunds[Refund review state machine]
    Conversations --> Store[(SQLAlchemy persistence<br/>SQLite default<br/>PostgreSQL URL supported)]
    Refunds --> Store

    subgraph AI[Controlled investigation and policy retrieval]
        Workflow[Controlled LangGraph investigation]
        Facts[Typed order-facts boundary]
        Lexical[Offline lexical policy baseline]
        Semantic[Semantic adapter + pgvector]
        Evidence[Published policy evidence<br/>version and audience filtered]
        Workflow --> Facts
        Workflow --> Evidence
        Evidence -->|configured PostgreSQL path| Semantic
        Evidence -->|backend failure fallback| Lexical
    end

    API --> Workflow
    CI[GitHub Actions] --> BackendChecks[pytest + compileall]
    CI --> FrontendChecks[typecheck + Vite build]
```

## Technology stack

| Area | Stack |
| --- | --- |
| Frontend | React 19, TypeScript, Vite |
| Backend | Python 3.11 in CI, FastAPI, Pydantic, Uvicorn |
| Persistence | SQLAlchemy repositories; SQLite by default; PostgreSQL policy-embedding migration and pgvector query path |
| Retrieval | Versioned in-code policy corpus, deterministic lexical baseline, sentence-transformers adapter, pgvector retriever with safe fallback |
| Workflow | LangGraph with injected model and typed business-facts boundaries |
| Quality | pytest, HTTPX/FastAPI tests, TypeScript typecheck, Vite production build, GitHub Actions |

Provider adapters and routing controls exist behind explicit qualification, quota,
privacy, and zero-cost gates. No hosted model is currently qualified or active.
Production authentication is implemented, but hosted cross-origin cookie behavior
and a real merchant integration have not been verified. There is no payment-write
integration.

## Local setup

### Prerequisites

- Python 3.11 or later; Python 3.11 is the version used by CI.
- Node.js 20 or later; CI uses Node.js 20.
- PostgreSQL and Docker are not required for the verified local test suite. The default application database is in-memory SQLite.

### Install

From a fresh checkout:

```powershell
git clone https://github.com/emam26/ResolveAI.git
cd ResolveAI

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt

Push-Location frontend
npm ci
Pop-Location
```

On macOS or Linux, use `python3 -m venv .venv`, activate with `source .venv/bin/activate`, and use forward slashes in the requirements path.

### Configuration

The application has no required secrets or live-provider credentials. These optional environment variables control local runtime behavior:

| Variable | Default | Purpose |
| --- | --- | --- |
| `RESOLVEAI_DATABASE_URL` | `sqlite+pysqlite:///:memory:` | SQLAlchemy database URL for conversations and refund reviews |
| `RESOLVEAI_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated browser origins allowed by the API |
| `RESOLVEAI_POLICY_RETRIEVAL` | `lexical` | Set to `semantic` to use the PostgreSQL/pgvector retriever when the database URL is PostgreSQL |
| `RESOLVEAI_SENTENCE_TRANSFORMER_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Local sentence-transformers model name; model loading remains local-files-only |
| `RESOLVEAI_LOCAL_POLICY_MODEL` | unset | Optional local path or cached Transformers model for policy-answer formulation; unset preserves deterministic generation |
| `RESOLVEAI_LOCAL_POLICY_TIMEOUT_SECONDS` | `8` | Maximum time for one local model response before deterministic fallback; the provider remains closed after a timeout |
| `RESOLVEAI_DEMO_SESSION_TTL_SECONDS` | `3600` | Lifetime of a local synthetic demo session; production authentication is not provided by this demo route |
| `RESOLVEAI_ENVIRONMENT` | `local` | Use `production` only with PostgreSQL, provisioned accounts, explicit trusted origins, and demo auth disabled |
| `VITE_AUTH_MODE` | unset (`demo`) | Set to `production` to use provisioned login and credentialed cookie requests; never put secrets in Vite variables |
| `RESOLVEAI_COMMERCE_DATABASE_URL` | unset locally | PostgreSQL URL for the read-only imported-commerce repository; optional for local demo fixtures but required in production |
| `VITE_API_BASE_URL` | empty, same-origin requests | API base URL used by the Vite frontend |

For a local two-process run, a file-backed SQLite database is convenient:

```powershell
$env:RESOLVEAI_DATABASE_URL = "sqlite+pysqlite:///./resolveai.db"
$env:RESOLVEAI_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
```

#### Optional local response model

The default remains deterministic policy-answer formulation. To evaluate a
compatible **already-cached** Transformers causal or sequence-to-sequence model,
set `RESOLVEAI_LOCAL_POLICY_MODEL` to its local directory before starting the
API. The adapter uses `local_files_only=True`: it does not download weights,
call a hosted API, access the database, or execute tools. It receives only
server-authorized policy evidence and must emit one JSON response that passes
the existing citation and extractive-grounding validation; otherwise ResolveAI
falls back to the deterministic answer. No generative model weights are
bundled with this repository. The opt-in harness performs no download and
reports `not_run` when no model is configured:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_local_model.py --model C:\models\cached-policy-model
```

The current development environment contains only the MiniLM embedding cache,
not a compatible generative model, so no real local-model inference is claimed.

Deployment preparation notes, environment checklists, migration/rollback guidance,
and the current hosted-model limitations are in
[`docs/DEPLOYMENT_PREPARATION.md`](docs/DEPLOYMENT_PREPARATION.md).
The manual synthetic owner walkthrough is in
[`docs/uat/OWNER_WALKTHROUGH.md`](docs/uat/OWNER_WALKTHROUGH.md).

### Run the API and frontend

Start the API in one terminal from the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --reload --port 8000
```

Start the frontend in a second terminal:

```powershell
cd frontend
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev -- --host 127.0.0.1 --port 5173
```

Open <http://127.0.0.1:5173>. Local demo mode labels synthetic identities and records clearly. The API is available at <http://127.0.0.1:8000>.

For the repository-managed local lifecycle, use the existing scripts from the
root. They only target the named local PostgreSQL container and leave unmanaged
processes and unrelated containers untouched:

```powershell
.\scripts\start-local.ps1
.\scripts\status-local.ps1
```

To verify the API session endpoint directly from PowerShell:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/auth/demo-login `
  -ContentType "application/json" `
  -Body '{"demo_actor_id":"customer_001"}'
```

### Test and build

Run backend checks from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests
.\.venv\Scripts\python.exe -m compileall -q backend
```

Run frontend checks from `frontend/`:

```powershell
npm run typecheck
npm run build
```

The same backend and frontend checks are defined in [`.github/workflows/ci.yml`](.github/workflows/ci.yml). The M10 local verification reruns the backend regression suite and the focused PostgreSQL/pgvector integration suite against a disposable database; exact counts are recorded in [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md). Frontend typecheck and the production build are also required. CI currently covers deterministic backend tests and frontend compilation/build; the disposable PostgreSQL and browser checks remain explicit local release gates. The M8 comparison below uses a frozen 15-case set and reports retrieval and answer-contract results separately.

### Local load, stress, and soak checks

The optional Locust harness exercises only synthetic local API data. Install its separate load-test dependency, start the API, and choose one bounded profile:

```powershell
python -m pip install -r requirements-load.txt
$env:RESOLVEAI_LOCUST_PROFILE = "load" # load, stress, or soak
locust -f scripts\locustfile.py --host http://127.0.0.1:8000 --headless
```

The profiles stop automatically after their configured duration. For a short smoke run, set `RESOLVEAI_LOCUST_MAX_SECONDS=5` before starting Locust. The workflow users create bounded synthetic conversations and refund-review records during a run, so longer profiles intentionally measure behavior while local state grows; reset the disposable database between comparable runs. These are local performance probes, not production capacity claims; capture the Locust summary with the profile name, API configuration, and machine details when comparing runs.

## Deployment preparation

The intended future topology is a Cloudflare Pages static frontend, a Render
FastAPI web service, and Neon PostgreSQL with pgvector. The checked-in
[`render.yaml`](render.yaml) is a reviewable service template; it does not
create a service or deploy anything. Configure only `VITE_API_BASE_URL` and
`VITE_AUTH_MODE=production` in the Pages build environment. Keep all database,
session, account, and provider secrets in the backend service environment.

Before a hosted rollout:

1. Create the Neon database and confirm the `vector` extension is available.
2. Configure Render secrets and trusted Cloudflare origin values from
   [`.env.example`](.env.example); never copy private values into this repo.
3. Run `python -m alembic -c backend/alembic.ini upgrade head` from a trusted
   release environment against the intended Neon URL, then verify
   `20261124_10` with `alembic current`.
4. Verify `/healthz` for process liveness and `/readyz` for dependency
   readiness before admitting traffic. Readiness must remain fail-closed when
   the database, commerce source, or schema is unavailable.
5. Deploy the frontend only after the API origin, credentialed CORS, cookie,
   CSRF, login, reload, expiry, logout, and role-isolation checks pass in the
   actual hosted domains.
6. Take a database backup and record the previous application commit before a
   rollout. Roll back the application to that commit if smoke checks fail; use
   a separately reviewed Alembic downgrade only when the migration policy
   explicitly permits it.

The free Render plan is suitable for a preview, not a durable production
merchant service: free web services sleep after inactivity and have ephemeral
files, while free Postgres has a 30-day lifetime and no backups. Render's
pre-deploy migration command is not available on the free web plan, so a
trusted migration step must be completed separately or a paid deployment plan
must be selected. See the current platform notes in
[`docs/DEPLOYMENT_PREPARATION.md`](docs/DEPLOYMENT_PREPARATION.md).

### PostgreSQL policy index (optional)

The repository includes an Alembic migration for the `policy_embeddings` table and a local-files-only sentence-transformers seed command. Cache the configured model once from the official model source, then point `RESOLVEAI_DATABASE_URL` at a PostgreSQL instance with the `vector` extension available. Run the migration and seed from `backend/`, then run the read-only evaluator from the repository root:

```powershell
$env:RESOLVEAI_DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/resolveai"
Push-Location backend
..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
..\.venv\Scripts\python.exe -m app.rag.seed
Pop-Location
.\.venv\Scripts\python.exe -m backend.app.rag.semantic_eval
```

The migration, idempotent real-embedding seed command, and frozen semantic evaluation were verified locally against PostgreSQL 16/pgvector. The evaluator reports raw retrieval separately from the customer-facing grounded-answer contract, so a ranked document is not treated as a usable answer unless it clears the existing evidence controls. The command is read-only and requires the configured model to already be cached; it does not download models. The default CI tests use deterministic embeddings. Production database provisioning, extension permissions, and live service operations remain outside this repository’s verification scope.

### Optional synthetic commerce dataset

M11A adds a reproducible, read-only operational-data foundation from a verified
synthetic ecommerce source. Imported order IDs use `commerce_order_<source-id>`
and are available through the normal authorized customer API only when
`RESOLVEAI_COMMERCE_DATABASE_URL` is set. Existing `order_1001` fixtures remain
the default local path. See [`docs/DATASET.md`](docs/DATASET.md) for the official
source checksum, isolated import procedure, mappings, deterministic scenarios,
and integration-test inputs. The source archive and staging database are not
part of this repository.

### Retrieval comparison (M8)

After migration and seeding, run the reproducible three-way benchmark from the repository root:

```powershell
.\.venv\Scripts\python.exe -m backend.app.rag.benchmark
```

The frozen set contains the original five evaluation cases plus 10 customer-facing challenge cases. It includes paraphrases, vocabulary mismatches, ambiguous and outdated-language requests, irrelevant questions, internal-only policy questions, and publication/version restrictions. The answer-contract score counts a result only when the top evidence is published, audience-visible, has a deterministic answer template, and matches the labeled policy; unsupported cases must produce no evidence. Latencies are warm steady-state retrieval measurements with three repeats per query.

| Method | Recall@3 | MRR | Answer contract | Unsupported behavior | Citation/access | Wrong version | p50 / p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Existing lexical baseline | 0.80 | 0.80 | 0.867 | 1.00 | 1.00 | 0.00 | 0.014 / 0.023 ms |
| PostgreSQL full-text (benchmark only) | 0.30 | 0.30 | 0.533 | 1.00 | 1.00 | 0.00 | 1.696 / 2.317 ms |
| Semantic pgvector | 0.60 | 0.60 | 0.733 | 1.00 | 1.00 | 0.00 | 52.037 / 56.076 ms |

On this small synthetic corpus, PostgreSQL full-text search adds no measured value beyond the existing methods and is substantially slower than the in-process lexical baseline. It is therefore retained as a benchmark implementation only; it is not added to the customer investigation path. The lexical baseline remains the strongest aggregate result on this labeled set, while semantic retrieval remains the configured path for the existing M7 workflow and its safe lexical fallback.

## Synthetic data and safety boundaries

ResolveAI uses one fictional merchant and seeded records only. Demo actors include `customer_001`, `support_001`, `refund_approver_001`, and `merchant_admin_001`. Demo login is a development convenience, not production authentication. Server-side role and ownership checks still apply to the synthetic records.

Refund approval is intentionally a human-controlled workflow:

- support prepares a request;
- a separate refund approver reviews it;
- idempotency and the local amount limit prevent duplicate or oversized requests; and
- approval records an external follow-up requirement rather than executing a payment.

No Shopify or other production commerce integration, real customer data, payment provider, or paid API call is included. The optional M11A commerce import is a local synthetic dataset only.

## Roadmap

- Expand the synthetic policy corpus and challenge labels before recalibrating semantic retrieval on broader vocabulary.
- Connect the controlled investigation workflow to an owner-approved model SDK behind explicit cost and credential controls.
- Add CI-hosted browser binaries and persistent policy-management/release workflows after their storage and audit contract is approved.
- Consider production identity, merchant integrations, multi-tenant isolation, and billing only after the single-merchant slice is hardened.

## Limitations

- The customer API uses deterministic assistance by default. Provider adapters are present, but no hosted model is qualified or enabled for customer traffic.
- The semantic and pgvector paths are verified locally with real sentence-transformers embeddings and deterministic CI coverage. On the M8 15-case comparison, semantic retrieval reached 0.60 Recall@3 versus 0.80 for lexical; these are small synthetic-corpus results, not production benchmarks.
- PostgreSQL full-text search is implemented for offline comparison only. It reached 0.30 Recall@3 and is not part of the customer runtime.
- SQLite remains the default local persistence path. PostgreSQL, Docker/WSL, and browser automation were verified only against disposable synthetic data, not production infrastructure.
- Local demo authentication, seeded identities, and the single fictional merchant are not suitable for a real merchant pilot. Provisioned production authentication is locally verified, while hosted cookie behavior remains unverified.
- The staff knowledge surface includes the local policy draft/edit, validation,
  publication, rollback, indexing, and audit workflow. It remains synthetic
  and deployment-bound: persistent PostgreSQL/index readiness and production
  authentication must be verified before public use.

## Documentation

- [`docs/PRODUCT_CONTEXT.md`](docs/PRODUCT_CONTEXT.md) — product scope and V1 decisions
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) — API, state, role, and refund contracts
- [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) — verified implementation index and outstanding validation
