# ResolveAI customer widget

This is the synthetic M1 customer widget. It starts a server-established `Demo Customer` session, opens a widget conversation for an optional order ID, and appends customer messages using the M1 HTTP/JSON contract in `docs/CONTRACTS.md`.

The API base is injected with `VITE_API_BASE_URL`. If it is omitted, requests use the same origin:

```powershell
npm install
npm run dev
```

For a separate local API, set the variable before starting Vite, for example:

```powershell
$env:VITE_API_BASE_URL = "http://localhost:8000"
npm run dev
```

M1 intentionally renders the server-returned customer transcript and an explicit “no AI answer is available yet” state. It does not invent assistant responses or perform client-side authorization.
