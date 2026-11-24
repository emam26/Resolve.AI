# M18-FIX Remediation Traceability

This document records the remediation of the independent M17/M18 safety review.
It is deliberately limited to implementation facts that can be verified locally;
live provider evaluation remains gated by verified account limits and the
owner-run synthetic harness.

| Finding | Root cause confirmed in code | Remediation | Regression evidence | Status |
| --- | --- | --- | --- | --- |
| M17-01: no shared evaluation budget | FastAPI constructed per-model quota ledgers without configuring a shared experiment scope; reservations were therefore not collective across Groq and Gemini. | Added grouped durable reservations across model, provider-account, and experiment scopes, immutable startup initialization, restart reconciliation, and a PostgreSQL advisory lock for quota transactions. | Alembic `20261124_08`; exact-boundary/restart/concurrency tests; broader PostgreSQL-backed suite passed 324/1 skip. | Fixed; independent re-review PASS |
| M17-02: conservative token accounting | Provider usage selected the first available total/input/output field, ignored reasoning usage, and dispatched failures were settled with zero tokens. | Added defensive usage normalization, reasoning/cached handling, conservative unknown settlement, UTF-8 byte-bound prompt reservation plus output/reasoning allowance, hard ceilings, and durable `OVERRUN` state. | Focused AI/control tests passed 53; PostgreSQL quota tests passed 2; no live provider usage was generated. | Fixed; independent re-review PASS |
| M17-03: evaluation/customer path not isolated | The optional external provider was constructed by the ordinary application startup path when global settings allowed it; no trusted experiment boundary existed. | Customer startup rejects evaluation mode; `build_trusted_evaluation_provider` requires explicit settings, local PostgreSQL, `synthetic_only=True`, qualified models, complete adapters, an exact provider:model allowlist restricted to Groq/Gemini, and an experiment scope; no public route accepts evaluation mode. | Customer/evaluation negative tests and allowlist/ceiling tests passed; live harness was not run. | Fixed; independent re-review PASS |
| M17-04: configurable ModelScope endpoint | A non-empty URL was accepted without HTTPS, host, or private-network protections. | Added HTTPS, public/private-network, exact-host/explicit-allowlist validation; ModelScope remains disabled when no verified endpoint is supplied. | Focused unsafe endpoint tests passed; no DNS or live redirect test was run. | Fixed; live network behavior unverified |
| M17-05: incomplete load evidence | Locust reported request/latency totals but did not persist workload metadata or distinguish unavailable application telemetry. | Added opt-in JSON/event observation with workload names, failure classes, maximum simulated users, and explicit `null`/unavailable fields for provider/quota/fallback/host metrics. | 48 observed requests, 0 failures, 3-second smoke, maximum simulated users 6; unavailable metrics were reported rather than inferred. | Instrumented; application telemetry still absent |

## Persistent-memory capability audit

ResolveAI currently persists conversations and messages in PostgreSQL/SQLite
through `backend/app/db/conversations.py`. The customer workflow can retrieve
the authorized conversation transcript, but the repository contains no
provider-independent compact summaries, cross-conversation issue retrieval, or
memory provenance/poisoning controls. Those are future M18-MEM integration
points, not an implementation claim for this remediation. Current order facts
and published policy evidence remain the authoritative sources for answers.

## Evidence ledger

Historical evidence is preserved in `docs/BENCHMARKS.md` and
`docs/PROJECT_STATE.md`. New results must identify whether they are deterministic
offline, mocked-provider, PostgreSQL integration, browser, load, or live-provider
measurements. Private holdout labels, operational records, credentials, and
model weights do not belong in this repository.

## Independent re-review

The bounded read-only reviewer completed a fresh review of the remediation and
returned **PASS** for the bounded synthetic-evaluation safety gate. Its scope
did not include live providers, billing/free-tier confirmation, protected
holdouts, or production readiness. The lead separately verified the PostgreSQL
migration and concurrency evidence recorded in `docs/BENCHMARKS.md`.
