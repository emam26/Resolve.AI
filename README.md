# ResolveAI

ResolveAI is an intelligent customer-operations application for a fictional online merchant. It combines a customer support widget, authenticated order context, policy retrieval, human support workflows, and controlled refund review in one small, testable vertical slice.

The repository is deliberately synthetic-data-first. It demonstrates the boundaries and safety rules needed for customer operations without connecting to a real merchant, payment provider, customer dataset, or paid model API.

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
| Customer widget | React/TypeScript/Vite UI with demo customer login, order selection, transcript, and human-handoff control | Local API and frontend checks pass |
| Staff console | Support inbox, claim/reply/resolve controls, and refund-approver view | Local API and frontend checks pass |
| Identity and authorization | Server-issued synthetic sessions, role checks, and customer order ownership checks | Covered by backend tests |
| Conversations | SQLAlchemy-backed conversation and message persistence; SQLite is the default local database | SQLite verified; PostgreSQL runtime not verified |
| Policy answering | Deterministic lexical retrieval over a small versioned policy corpus with published/visibility filtering and citations | Offline baseline verified |
| Semantic retrieval | Sentence-transformers adapter, deterministic cosine retriever, pgvector retriever, publication-safe query, migration, and seed helper | Integrated behind an explicit PostgreSQL/semantic configuration; model loading and PostgreSQL execution outstanding |
| Investigation workflow | Bounded LangGraph workflow with typed order-facts and injected policy retrieval | Deterministic local workflow and customer API path verified; no live model SDK |
| Refund review | Backend API supports support-created pending requests, idempotency, separate approver decisions, and an external-action-required terminal state; the current console exposes approver review | Local synthetic flow verified; no payment operation |

## Customer-to-resolution workflow

The main supported path is:

1. A synthetic customer requests the allowlisted `customer_001` demo actor. The server issues a demo session only for known synthetic identities and enforces role and ownership; this is not production authentication.
2. The customer opens a widget conversation, optionally associated with seeded order `order_1001`, and sends a message. The API runs the bounded investigation workflow: authorized order questions use typed order facts, while policy questions use the configured semantic retriever or the deterministic lexical fallback.
3. A grounded response includes only published, audience-visible policy evidence. Irrelevant, unsupported, refund, and unavailable-tool cases return a safe handoff result without an invented answer. The customer can then request human support, moving the conversation from `AI_ACTIVE` to `HANDOFF_QUEUED`.
4. A synthetic support agent signs in as `support_001`, claims the queued case, and replies as a human. The state becomes `HUMAN_ACTIVE`, which blocks autonomous replies.
5. While the case is human-active, the support agent can create a synthetic refund review through the backend API, subject to the local eligibility rules and a 5,000-cent limit. The current console provides the separate approver review view rather than support-side request creation.
6. A separate `refund_approver_001` actor can approve or reject the request. Approval produces `APPROVED_EXTERNAL_ACTION_REQUIRED`; it never moves money and never records `REFUNDED`.
7. After the human work is complete, the support agent can resolve the conversation, moving it from `HUMAN_ACTIVE` to `RESOLVED`.

The local widget route uses a deterministic classifier and mocked model boundary; it does not call a live LLM. Semantic retrieval is opt-in for a PostgreSQL database through `RESOLVEAI_POLICY_RETRIEVAL=semantic`. If that backend or its local model is unavailable, the policy answer layer falls back to the lexical baseline and never presents that fallback as a semantic success.

## System architecture

```mermaid
flowchart LR
    Customer[Customer] --> Widget[React customer widget]
    Staff[Support agent] --> Console[React staff console]
    Approver[Refund approver] --> Console

    Widget -->|JSON + demo Bearer session| API[FastAPI API]
    Console -->|JSON + demo Bearer session| API

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

There is no live LLM SDK integration, production authentication, commerce connector, or payment-write integration in this version.

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
| `VITE_API_BASE_URL` | empty, same-origin requests | API base URL used by the Vite frontend |

For a local two-process run, a file-backed SQLite database is convenient:

```powershell
$env:RESOLVEAI_DATABASE_URL = "sqlite+pysqlite:///./resolveai.db"
$env:RESOLVEAI_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
```

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

Open <http://127.0.0.1:5173>. The UI labels its demo identities and synthetic data clearly. The API is available at <http://127.0.0.1:8000>.

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

The same backend and frontend checks are defined in [`.github/workflows/ci.yml`](.github/workflows/ci.yml). The current local verification passed 55 backend tests; five opt-in PostgreSQL tests were skipped because no test database URL was configured. Frontend typecheck and the production build remain independently verified.

### PostgreSQL policy index (optional)

The repository includes an Alembic migration for the `policy_embeddings` table and a deterministic-embedder seed helper. From `backend/`, point `RESOLVEAI_DATABASE_URL` at a PostgreSQL instance with the `vector` extension available and run:

```powershell
$env:RESOLVEAI_DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/resolveai"
..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
..\.venv\Scripts\python.exe -m app.rag.seed
```

The migration and idempotent seed command are implemented, but PostgreSQL execution, extension permissions, and sentence-transformers model loading are not claimed as verified by the default local test run.

## Synthetic data and safety boundaries

ResolveAI uses one fictional merchant and seeded records only. Demo actors include `customer_001`, `support_001`, `refund_approver_001`, and `merchant_admin_001`. Demo login is a development convenience, not production authentication. Server-side role and ownership checks still apply to the synthetic records.

Refund approval is intentionally a human-controlled workflow:

- support prepares a request;
- a separate refund approver reviews it;
- idempotency and the local amount limit prevent duplicate or oversized requests; and
- approval records an external follow-up requirement rather than executing a payment.

No Shopify or other commerce integration, real customer data, payment provider, or paid API call is included.

## Roadmap

- Verify semantic retrieval, policy seeding, and publication/version filtering against a PostgreSQL/pgvector runtime.
- Add the planned PostgreSQL full-text comparison and measure it against the lexical and semantic baselines.
- Connect the controlled investigation workflow to an owner-approved model SDK behind explicit cost and credential controls.
- Verify Docker/PostgreSQL and browser-level flows in a reproducible environment.
- Consider production identity, merchant integrations, multi-tenant isolation, and billing only after the single-merchant slice is hardened.

## Limitations

- The customer API uses a deterministic local classifier and mocked model boundary; it is not a live provider integration.
- The semantic and pgvector paths are integrated and tested with deterministic local components, but local model loading and PostgreSQL execution have not been verified here.
- SQLite is the verified local persistence path. PostgreSQL execution, Docker execution, and browser/manual testing remain outstanding.
- Demo authentication, seeded identities, and the single fictional merchant are not suitable for production use.

## Documentation

- [`docs/PRODUCT_CONTEXT.md`](docs/PRODUCT_CONTEXT.md) — product scope and V1 decisions
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) — API, state, role, and refund contracts
- [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) — verified implementation index and outstanding validation
