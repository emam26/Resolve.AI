# ResolveAI Benchmark Evidence

This is the canonical summary of measured local evidence. Each result is
synthetic, local, and tied to the command and environment described below.
Historical milestone detail remains in [`PROJECT_STATE.md`](PROJECT_STATE.md).
No protected M16C holdout labels or operational customer records are included.

## Current readiness checkpoint

| Date | Revision | Evidence | Result | Limits |
|---|---|---|---|---|
| 2026-11-24 | `69485e1` plus uncommitted provider-cap change | Root backend suite | 269 passed, 37 intentional PostgreSQL/commerce skips, 12.42 s | PostgreSQL-specific skips were not counted as passes |
| 2026-11-24 | working tree | Frontend typecheck/build | Both passed | `frontend/` package commands |
| 2026-11-24 | working tree | Playwright with installed system Chrome | 15/15 passed, 7.7 s | Uses synthetic API data; browser path was explicitly configured |
| 2026-11-24 | working tree | Locust load probe | 136 requests, 0 failures, 19.45 req/s; aggregate p50/p95/p99/max 2/9/10/10 ms | 8 users, 10 s measurement window |
| 2026-11-24 | working tree | Locust stress probe | 441 requests, 0 failures, 48.87 req/s; aggregate p50/p95/p99/max 3/10/55/55 ms | 20 users, 10 s measurement window |
| 2026-11-24 | working tree | Locust soak smoke | 133 requests, 0 failures, 19.05 req/s; aggregate p50/p95/p99/max 2/12/13/13 ms | 8 users, 10 s measurement window |

Commands:

```powershell
.venv\Scripts\python.exe -m pytest -q
Push-Location frontend
npm.cmd run typecheck
npm.cmd run build
$env:RESOLVEAI_PLAYWRIGHT_EXECUTABLE = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
npm.cmd run test:e2e -- --reporter=line
Pop-Location
```

The Locust probes used `scripts/locustfile.py`, a temporary local Uvicorn
process, `RESOLVEAI_LOCUST_MAX_SECONDS=10`, and the `load`, `stress`, and
`soak` profiles. The process was terminated after the probes.

## Retrieval and inference evidence

- The verified semantic/pgvector development baseline remains the M15/M16
  result in `PROJECT_STATE.md`; the protected private holdouts remain historical
  evidence and were not accessed.
- The current deterministic customer path remains the default and uses no
  external inference request. Existing tests cover policy publication/version
  filtering, customer/staff visibility, citations, handoff, and provider
  failure fallback.
- M17-D discovery made exactly five authenticated catalog requests in its
  approved tranche: Groq 11, Gemini 50, OpenRouter 439, Agnes 12, and Chutes
  20, for 532 catalog entries. These are not 532 unique, free, private, or
  qualified models. Fifteen entries were explicitly zero-priced; account
  quota, billing, and privacy eligibility were not established by the catalog
  responses. Cloudflare and ModelScope were manual-catalog providers.
- No model was qualified or activated, and no live generation request was
  made. The owner supplied free-plan status, but the required independent
  critical-boundary review timed out in this session, so the newly authorized
  live tranche remains blocked rather than being claimed as evaluated.
- The uncommitted provider safety change adds and tests a hard 256-token
  output cap in OpenAI-compatible, Gemini, and Cloudflare request payloads.

## Historical records

The project state ledger records the historical PostgreSQL, RAG, local Gemma,
Playwright, simulation, and longer Locust runs with their dates, sample sizes,
commands, and limitations. Those records distinguish deterministic execution,
mocked providers, local model inference, and hosted provider inference. They
must not be combined into a universal production-quality or capacity claim.

## Not established

This evidence does not establish live Groq/Gemini quality, provider billing
status through an account API, active adaptive-routing models, hosted-inference
latency, absolute capacity, cloud deployment readiness, or real-customer
behavior.
