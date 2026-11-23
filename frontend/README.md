# ResolveAI local frontend

This directory contains the React/TypeScript/Vite frontend for the synthetic ResolveAI customer widget, support inbox, refund-approval console, operations overview, read-only policy catalog, and admin team/settings view. It talks to the FastAPI service through the JSON API; authorization and workflow state remain server-controlled.

## Local development

Install the locked dependencies and start Vite:

```powershell
npm ci
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev -- --host 127.0.0.1 --port 5173
```

The Vite development server proxies `/api` to `http://127.0.0.1:8000` by default, so `VITE_API_BASE_URL` can be omitted for the documented two-process setup. Set it when the API uses a different address. See the repository [README](../README.md) for backend setup, synthetic workflow steps, and limitations.

The staff workspace is available at `http://127.0.0.1:5173/?surface=overview`, `?surface=knowledge`, or `?surface=team`. The customer-only embed preview is `http://127.0.0.1:5173/?surface=widget`; it does not expose staff or refund controls.

## Checks

```powershell
npm run typecheck
npm run build
```

## Browser checks

The repository includes deterministic Playwright coverage for the synthetic
customer-to-resolution workflow, staff workspace surfaces, widget isolation,
and safe API-failure states:

```powershell
npm run test:e2e -- --list
npm run test:e2e
```

The tests start or reuse the local FastAPI and Vite processes and use SQLite
with lexical retrieval. Browser binaries are not downloaded by this
repository. In environments without the pinned Playwright browser, an
installed system Chromium/Chrome/Edge executable can be selected explicitly:

```powershell
$env:RESOLVEAI_PLAYWRIGHT_EXECUTABLE = "C:\Program Files\Google\Chrome\Application\chrome.exe"
npm run test:e2e
```

The local M13 verification ran all eight tests with the system Chrome path.

The UI uses explicitly labelled demo identities and synthetic records. It does not connect to a live customer, commerce, payment, or model provider.
