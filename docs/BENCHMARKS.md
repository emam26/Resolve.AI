# ResolveAI Benchmark Evidence

This is the canonical summary of measured local evidence. Each result is
synthetic, local, and tied to the command and environment described below.
Historical milestone detail remains in [`PROJECT_STATE.md`](PROJECT_STATE.md).
No protected M16C holdout labels or operational customer records are included.

## M21 release-blocker remediation checkpoint

These checks are local and synthetic. No live provider request, protected
holdout, deployment, or payment action was performed.

| Evidence | Result | Limits |
| --- | --- | --- |
| Backend focused auth/readiness/security checks | `32 passed` | Includes opaque cookie login, CSRF, logout revocation, rate-limit concurrency, trusted-forwarded-IP handling, schema/head checks, malformed-token handling, and existing demo-auth regressions |
| AI/provider safety checks | `46 passed` | Evaluation remains fail-closed because the historical M19 aggregate usage ledger cannot be reconstructed; no provider calls |
| Full backend regression | `323 passed, 40 skipped` | PostgreSQL/commerce skips remain because no ResolveAI PostgreSQL test container or URL was available in this run |
| Frontend typecheck/build | Passed | Local package checks |
| Frontend focused browser checks | Worker-reported `4 passed` | Existing cached/system Chrome; the lead did not rerun the browser suite after the final API client adjustment |
| Frontend consolidated browser suite | `18/18 passed` | Installed system Chrome, synthetic local API, after the final M21 client changes |
| Locust default-admission probe | `70` requests, `60` expected `429` failures after shared-IP login admission | 8 synthetic users on one loopback IP; this validates the brute-force/shared-IP gate, not application throughput |
| Python compilation, dependency and diff checks | Passed | `compileall`, `pip check`, `git diff --check` |
| WSL/Docker inspection | WSL/Docker healthy | The claimed `resolveai-m15-pg` container and `resolveai` volume were absent; unrelated CVAT containers were not touched |

The M21 production authentication path used provisioned scrypt account hashes,
opaque expiring HttpOnly cookies, CSRF tokens, credentialed CORS, logout
revocation, and bounded process-local admission controls. M22 adds a
PostgreSQL-backed session/admission path for provisioned production auth; the
SQLite/process-local path remains an explicit deterministic-test fallback. The
code-owned Alembic head is now `20261124_10`; `/readyz` fails closed when the
configured PostgreSQL schema or revision is missing.

## M22 integrated frontend and PostgreSQL checkpoint

These are new local results from the current working tree. They use synthetic
data only, do not include provider calls, and do not establish deployment or
owner visual acceptance.

| Evidence | Result | Limits |
| --- | --- | --- |
| Full backend regression | `332 passed, 42 skipped` | The 42 skips are opt-in PostgreSQL/commerce checks without `RESOLVEAI_TEST_POSTGRES_URL`; the real PostgreSQL subset is reported below |
| Real PostgreSQL migrations | Alembic upgrade/current reached `20261124_10 (head)` in the existing database and isolated synthetic databases | Existing `resolveai-local-dev-postgres` volume preserved; no unrelated container changed |
| Existing PostgreSQL integration suites | `108 passed` | Ran against isolated synthetic `resolveai_m16db`; includes persistence, policy/indexing, pgvector/FTS, memory, commerce, quota, simulation and durable-auth checks |
| Durable production-auth PostgreSQL checks | Included in the `108` above | Session sharing/revocation across two app instances and atomic admission across two repositories; credentials were synthetic test values |
| PostgreSQL seed | Structured synthetic seed completed for four orders, two payments and two shipments | Local evaluation database only; operational records were not exported |
| PG-backed API smoke | Health `200`, readiness `200`, owned `eval_order_001` returned, foreign `eval_order_003` returned `404` | Temporary server; deterministic/demo auth; no hosted provider |
| Frontend typecheck/build | Passed | Local Windows Node dependencies |
| Playwright functional suite | `18 passed, 2 skipped`, one worker, installed system Chrome | The two production-mode tests are selected only for their separate focused run; synthetic fixture/local API |
| Playwright production-auth checks | `2 passed` | Separate production-mode server on isolated ports; expired-session and `403 csrf_required` recovery, mocked synthetic API routes |
| Production-session expiry browser check | `1 passed` | Synthetic mocked login/API; hosted cross-origin cookie behavior remains unverified |
| Local lifecycle scripts | PowerShell parse, start, status and targeted container safety checks passed | Existing backend/frontend were recognized as unmanaged and left untouched; scripts never delete containers/volumes |
| Visual reference check | Dashboard and widget screenshots spot-checked against approved direction | Owner pixel/visual acceptance is still required |

## Current readiness checkpoint

| Date | Revision | Evidence | Result | Limits |
|---|---|---|---|---|
| 2026-11-24 | `69485e1` plus uncommitted provider-cap change | Root backend suite | 269 passed, 37 intentional PostgreSQL/commerce skips, 12.42 s | PostgreSQL-specific skips were not counted as passes |
| 2026-11-24 | working tree | Frontend typecheck/build | Both passed | `frontend/` package commands |
| 2026-11-24 | working tree | Playwright with installed system Chrome | 15/15 passed, 7.7 s | Uses synthetic API data; browser path was explicitly configured |
| 2026-11-24 | working tree | Locust load probe | 136 requests, 0 failures, 19.45 req/s; aggregate p50/p95/p99/max 2/9/10/10 ms | 8 users, 10 s measurement window |
| 2026-11-24 | working tree | Locust stress probe | 441 requests, 0 failures, 48.87 req/s; aggregate p50/p95/p99/max 3/10/55/55 ms | 20 users, 10 s measurement window |
| 2026-11-24 | working tree | Locust soak smoke | 133 requests, 0 failures, 19.05 req/s; aggregate p50/p95/p99/max 2/12/13/13 ms | 8 users, 10 s measurement window |

## M20 owner-acceptance checkpoint

These results were executed after the M20 local changes, using synthetic data
and the running local Windows processes. The PostgreSQL rerun was attempted but
could not start because WSL returned `Wsl/E_ACCESSDENIED`; the historical
PostgreSQL evidence above and in `PROJECT_STATE.md` is not relabeled as a new
M20 pass.

| Evidence | Result | Limits |
| --- | --- | --- |
| Backend regression | `312 passed, 40 skipped` | Existing optional PostgreSQL/commerce inputs were unavailable in this run |
| Frontend static checks | Typecheck and production build passed | Local package installation only |
| Playwright with installed system Chrome | Existing suite `16/16 passed`; added owner screenshot test `1/1 passed` | Synthetic local API; browser executable explicitly configured. A later consolidated 17-test rerun timed out during runner shutdown after enumerating all tests, so it is not counted as a single 17/17 pass |
| Owner screenshots | Four genuine screenshots captured and inspected: customer widget, overview, knowledge, support inbox | Synthetic UI evidence; no production claim |
| Memory context benchmark | 50 records; relevance selector recall `1.0000` versus prior last-five recency recall `0.0000`; mean/p50/p95 `0.3256/0.3176/0.3496 ms` | Deterministic SQLite microbenchmark, not a capacity claim |
| Locust load (5 s) | `93` requests, `0` failures, `18.51` req/s; aggregate p50/p95/p99/max `3/66/89/89 ms` | 8 simulated users; provider/DB/CPU telemetry unavailable |
| Locust stress (5 s) | `269` requests, `0` failures, `52.65` req/s; aggregate p50/p95/p99/max `4/16/20/21 ms` | 20 simulated users; bounded synthetic probe |
| Locust soak smoke (5 s) | `94` requests, `0` failures, `18.51` req/s; aggregate p50/p95/p99/max `3/9/71/71 ms` | 8 simulated users; not a long-duration soak |
| PostgreSQL/WSL rerun | **BLOCKED** | `wsl.exe -d Ubuntu -- docker ps` returned `Wsl/E_ACCESSDENIED`; no M20 PostgreSQL pass is claimed |

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

## M18-FIX remediation evidence (local, no live providers)

| Date | Evidence | Result | Limits |
|---|---|---|---|
| 2026-11-24 | Alembic against disposable PostgreSQL 16/pgvector | Downgrade to `20261124_07`, upgrade to `20261124_08`, and `alembic current` at `20261124_08 (head)` | Isolated local database only |
| 2026-11-24 | PostgreSQL quota/concurrency suite | `backend/tests/backend/test_m18_fix_quota_postgres.py`: 2 passed | Synthetic quota rows; no provider requests |
| 2026-11-24 | PostgreSQL policy/persistence/quota suite | 324 passed, 1 intentional skip | Full backend tests with the separate structured-commerce test excluded because its imported dataset was not loaded into this disposable DB; no live provider calls |
| 2026-11-24 | Default backend regression | 295 passed, 39 skipped, 13.53 s | Skips are existing optional PostgreSQL/commerce inputs; no live provider calls |
| 2026-11-24 | Instrumented Locust load smoke | 48 observed requests, 0 failures, 3 s, maximum simulated users 6 | Setup requests were observed before `--reset-stats`; application CPU/RAM, DB connections, queue depth, provider distribution, quota contention, fallback frequency, saturation, and recovery telemetry were unavailable and explicitly reported as such |

The PostgreSQL quota test initially exposed a real deadlock between concurrent
startup reconciliation and quota completion. The fix uses a short
database-scoped advisory lock around quota-control transactions; the rerun
passed. A combined run against the empty disposable database produced three
data-dependent failures in the separate structured-commerce tests because
their imported evaluation records were not seeded there; those failures are
not counted as M18-FIX passes.

The bounded independent re-review completed with **PASS** for the synthetic
evaluation safety gate after the quota ceilings, conservative reservation,
candidate allowlist, adapter completeness, local PostgreSQL, and explicit
synthetic-only marker fixes. This does not establish provider billing status,
live inference quality, model qualification, or production readiness.

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
  made. The independent M17/M18 review completed with a FAIL verdict; M18-FIX
  remediation is not eligible for live generation until a fresh independent
  re-review accepts the critical quota, accounting, and isolation fixes.
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


## Reference UI integration candidate
No new backend, PostgreSQL, browser, provider or load benchmark pass is claimed. TypeScript typecheck and Python compileall passed. Native build, backend test collection and browser fixture navigation were blocked by environment limitations; see UI_INTEGRATION_HANDOFF.md. All earlier measurements remain historical.
