# ResolveAI local frontend

This directory contains the React/TypeScript/Vite frontend for the synthetic ResolveAI customer widget, support inbox, and refund-approval console. It talks to the FastAPI service through the JSON API; authorization and workflow state remain server-controlled.

## Local development

Install the locked dependencies and start Vite:

```powershell
npm ci
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev -- --host 127.0.0.1 --port 5173
```

The Vite development server proxies `/api` to `http://127.0.0.1:8000` by default, so `VITE_API_BASE_URL` can be omitted for the documented two-process setup. Set it when the API uses a different address. See the repository [README](../README.md) for backend setup, synthetic workflow steps, and limitations.

## Checks

```powershell
npm run typecheck
npm run build
```

## Browser checks

The repository includes deterministic Playwright coverage for the synthetic
customer-to-resolution workflow and a safe API-failure state:

```powershell
npm run test:e2e -- --list
npm run test:e2e
```

The tests start or reuse the local FastAPI and Vite processes and use SQLite
with lexical retrieval. A compatible Playwright browser must be installed
locally before execution; browser binaries are not downloaded by this
repository. The current IDE environment can list the two tests but does not
have the Chromium executable, so no browser pass is claimed here.

The UI uses explicitly labelled demo identities and synthetic records. It does not connect to a live customer, commerce, payment, or model provider.
