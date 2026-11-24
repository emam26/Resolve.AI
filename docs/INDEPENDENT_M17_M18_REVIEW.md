# Independent M17/M18 Release-Blocking Safety Review

**Reviewer:** Principal AI Engineer / security review
**Date:** 2026-11-24
**Scope:** commits `ee015d6`, `922c0a1`, `7c47f42`, `5389a14`,
`69485e1`, `338cb26`, and `9ec157d`, plus immediate integration code and
tests.

This review is read-only with respect to application code. No credentials were
printed or inspected for value, no live inference or discovery request was
made, no protected holdout was accessed, and no deployment or push occurred.
The review artifact itself is the only requested file created by this review.

## Verified strengths

- `backend/app/config.py:51-87` stores provider credentials as Pydantic
  `SecretStr` values. `.gitignore:1-8` ignores private environment files at
  every directory depth, and the current private `.env` is not tracked.
- `backend/app/ai/provider_adapters.py:436-492` refuses external adapter
  construction when external inference is disabled, zero-cost mode is on,
  quotas are non-positive, the provider is disabled, credentials are absent,
  or a ModelScope endpoint is absent.
- `backend/app/ai/model_control.py:1027-1077` routes only `ACTIVE`, healthy,
  available, non-deprecated models with verified free, privacy, structured
  output, task-category, capability, health, latency, and quota checks.
- `backend/app/ai/generation.py:151-193` validates the structured schema,
  request-local citations, cited evidence, policy modalities, and prompt
  injection patterns. `backend/app/ai/answer.py:94-169` rechecks publication
  and customer visibility and hands off on retrieval failure.
- Commit `338cb26` propagates a maximum of 256 output tokens to the
  OpenAI-compatible, Gemini, and Cloudflare payloads. The focused tests assert
  the relevant payload fields.
- The provider payload contains only query and server-authorized policy
  evidence (`provider_adapters.py:89-109`). Existing tests assert that
  `customer_id`, `order_id`, and credential text are not sent.
- Deterministic database answers and the current default configuration avoid
  provider calls. The latest local readiness evidence reports 269 backend
  passes, 15/15 Playwright journeys, and zero-failure bounded Locust probes.

## Findings

### M17-01 — Shared budget and actual-token accounting are not enforced

**Severity:** P1 — blocks the authorized live evaluation and production
release; the current default remains fail-closed.

**Evidence:**

- `backend/app/ai/model_control.py:913-945` reserves only the caller's
  `estimated_tokens` in one `QuotaWindowRow` keyed by a model/provider scope.
- `backend/app/api/app.py:170-189` creates a `QuotaLedger`, but does not
  configure quota rows from `provider_request_quota`,
  `provider_token_quota`, `provider_quota_window_seconds`, or
  `provider_max_concurrency`. A configured registry therefore normally has no
  quota capacity and safely falls back to deterministic answers.
- `RouteRequest` and the API route use an estimate of at most 256 tokens, but
  the approved evaluation limit is 50,000 total input/output/reasoning tokens.
  There is no shared ledger spanning the Groq and Gemini model scopes.
- `backend/app/ai/model_control.py:948-960` replaces the estimate with actual
  usage after dispatch, but does not reject or prevent an over-limit actual
  usage. The reservation check has already occurred.
- `backend/app/config.py:157-172` exposes quota-window and concurrency
  settings, but the runtime path does not consume those values when creating
  durable quota windows. `QuotaLedger.reserve` uses a hard-coded one-day reset
  at `model_control.py:922-925`.

**Failure scenario:** Two active models can each pass their individual scope
checks while the combined evaluation exceeds 48 requests or 50,000 tokens.
Prompt/input and reasoning tokens can make actual usage exceed the 256-token
reservation. In the ordinary FastAPI path, the opposite failure also occurs:
without preconfigured quota rows, the routed provider cannot dispatch at all.

**Recommended fix:** Introduce one durable shared evaluation/account budget
scope in addition to per-provider/model scopes. Reserve a conservative upper
bound before dispatch, including input, output, and any provider-specific
reasoning allowance; settle with actual usage without releasing consumed
budget. Initialize only explicitly approved quota windows, concurrency, and
shared limits. Keep ordinary customer traffic disabled while the evaluation
scope is active.

**Required regression test:** Use two Groq/Gemini model scopes and concurrent
workers. Assert that the aggregate request and token reservations cannot cross
48/50,000, that configured window/concurrency values are applied, and that a
request with actual usage above its estimate is rejected or conservatively
accounted. Add a FastAPI routed-path test proving a correctly configured scope
dispatches and an absent/expired scope falls back without a provider call.

### M17-02 — Provider failures and malformed responses can undercount consumed tokens

**Severity:** P1 — blocks the authorized live evaluation because the approved
token ceiling cannot be evidenced from the current accounting.

**Evidence:**

- `backend/app/ai/provider_adapters.py:72-76` returns the first available
  value among total, input, and output tokens. When a provider reports input
  and output but omits total, output is not added to input.
- `backend/app/ai/provider_adapters.py:139-152` parses no reasoning-token
  fields or provider-specific usage details.
- `backend/app/ai/provider_adapters.py:533-548` calls
  `report_failure(..., dispatched=True)` for provider errors and malformed
  routed responses. `backend/app/ai/model_control.py:1083-1094` settles those
  reservations with `actual_tokens=0`, even when the provider may have
  generated partial output or returned usage metadata.

**Failure scenario:** A provider returns a rate-limit/error response after
partial processing, or returns a structured-but-invalid answer with usage
metadata. The request is counted, but the token ledger removes the estimate
and records zero actual tokens. A provider response with separate prompt and
completion counts is also undercounted when `total_tokens` is absent. Repeated
attempts can therefore exceed the approved token budget while the ledger says
they did not.

**Recommended fix:** Normalize provider usage into total input + output +
reasoning tokens when total is absent. Preserve a conservative reserved amount
on dispatched failures unless authoritative usage proves a lower amount; never
settle a dispatched request at zero solely because output validation failed.
Record usage parsing confidence and stop the evaluation when usage is unknown,
rather than retrying permissively.

**Required regression test:** Add fake responses for missing totals, reasoning
details, HTTP 429/5xx, timeout after dispatch, malformed JSON, and schema
failure. Assert exact request/token ledger deltas and that no retry can exceed
the shared budget.

### M17-03 — Evaluation-only isolation is not a separate enforced boundary

**Severity:** P1 — blocks the requested synthetic-only live evaluation as an
application-controlled experiment; also blocks production release.

**Evidence:**

- `backend/app/api/app.py:149-189` constructs the external provider for the
  ordinary customer application when environment flags, PostgreSQL registry
  state, credentials, and quota state permit it. There is no evaluation-only
  mode, synthetic-dataset marker, or separate evaluation service boundary.
- `backend/app/config.py:135-155` has global enable/quota switches, but no
  authenticated evaluation identity or immutable request budget tied to the
  approved tranche.
- The current `.env` defaults are safe (`external_inference_enabled=false`,
  `zero_cost_mode=true`, quotas zero), but changing those values for an
  experiment changes the same provider path used by ordinary customer traffic.

**Failure scenario:** An operator enables external inference and activates a
qualified model for a test, then a normal customer request enters the same
process and can consume the same provider quota. The current prompt boundary
does prevent arbitrary customer/order fields from being included in the
provider payload, but it does not prove that the whole request is synthetic or
that live traffic cannot use the evaluation budget.

**Recommended fix:** Use a separately guarded evaluation entry point/process
with an explicit synthetic fixture identity, immutable request/token counters,
and no production customer route. Alternatively add a fail-closed evaluation
mode whose request authorization and dataset provenance are independently
validated. Keep production external inference disabled until the mode is
explicitly changed after qualification.

**Required regression test:** Start the evaluation path with synthetic fixtures,
assert the exact aggregate budget, and assert that ordinary customer routes are
rejected or deterministic while evaluation mode is active. Assert that no
real-order/customer fixture can reach the provider adapter.

### M17-04 — Configurable ModelScope endpoint is not validated

**Severity:** P2 — blocks production provider-security approval; does not by
itself block a Groq/Gemini-only tranche because those endpoints are fixed.

**Evidence:** `backend/app/api/app.py:175-180` passes the environment-provided
`modelscope_base_url` to `build_provider_adapter`, and
`backend/app/ai/provider_adapters.py:474-483` accepts it after only a non-empty
check. There is no HTTPS requirement, host allowlist, redirect policy test, or
explicit private-network restriction.

**Failure scenario:** A misconfigured or compromised local environment can
route ModelScope payloads to an arbitrary HTTP/HTTPS host. The value is not
LLM-controlled, so this is configuration risk rather than an immediate prompt
injection path, but it violates the provider-endpoint boundary.

**Recommended fix:** Validate the URL scheme and approved host before adapter
construction, reject redirects, and add an endpoint-policy test. Keep the
provider disabled unless its endpoint and privacy terms are explicitly
verified.

### M17-05 — Scalability evidence omits required resource and queue metrics

**Severity:** P2 — blocks production scalability claims, not the bounded live
evaluation itself.

**Evidence:** `docs/BENCHMARKS.md` records request counts, test windows,
throughput, failure rates, and p50/p95/p99/max latency for the three short
Locust probes. `scripts/locustfile.py` has no CPU, RSS, database connection,
queue-depth, provider-distribution, or in-flight-request telemetry. The
document explicitly does not claim capacity.

**Failure scenario:** The zero-failure 10-second probes can coexist with
resource exhaustion, connection-pool saturation, or an unobserved queue under
longer workloads. They do not support the sprint's 100–1,000-user capacity or
recovery claims.

**Recommended fix:** Add bounded local telemetry around a declared workload,
capture CPU/RAM/DB connections/queue depth and actual in-flight requests, and
run only after the provider/account safety gates are fixed. Do not expose the
current probes as capacity results.

## Evaluation readiness decision

The requested synthetic evaluation is **not safe to start through the current
routed FastAPI path**. The defaults are fail-closed and the evidence/citation
boundary is strong, but the P1 findings mean the implementation cannot yet
prove the approved shared request/token ceiling or synthetic-only isolation.
An external wrapper could manually count calls, but that would not verify the
application's own quota and routing boundary requested by M17-D/M18.

The prior discovery evidence remains historical: 532 catalog entries across
five providers, 15 explicitly zero-priced entries, zero qualified/active
models, and no generation calls. These counts do not establish provider free
eligibility, privacy eligibility, or account quota.

## Tests executed for this review

The focused offline review suite was executed without network access:

```text
backend/tests/ai/test_model_control.py
backend/tests/ai/test_provider_adapters.py
backend/tests/ai/test_generation.py
backend/tests/backend/test_m9_llm.py
backend/tests/backend/test_settings.py
backend/tests/backend/test_local_model_config.py
44 passed in 1.53s
```

Not executed by this review: full backend regression, PostgreSQL integration,
frontend/browser suites, Locust, live discovery, live inference, protected
holdouts, or cloud services. Existing local evidence for those areas is cited
in `docs/BENCHMARKS.md` and `docs/PROJECT_STATE.md`, but was not re-labelled as
independent review evidence.

## Final verdict

**FAIL — critical quota/accounting and evaluation-isolation defects prevent
bounded live evaluation.**

This is not a judgment that the provider adapters are unusable. It means the
already authorized experiment must wait for the P1 fixes and their focused
concurrency/accounting tests. Once those pass, a new bounded review can decide
whether the existing authorization is sufficient; no protected holdout or paid
request is needed for that decision.
