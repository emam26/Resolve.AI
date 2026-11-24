# M19 bounded provider evaluation

**Date:** 2026-11-24
**Status:** stopped safely; no hosted model was qualified or activated.

The owner-authorized tranche was synthetic-only, capped at 48 generation
attempts, 50,000 total tokens, 256 output tokens per request, two models per
provider, and zero expenditure. No protected evaluation holdout, production
record, billing operation, or deployment was used.

## Eligibility checks

The live catalog requests made in this tranche were three requests without
retries: Groq's catalog (11 entries), Gemini's catalog (50 entries), and a
Groq model-detail request for `allam-2-7b`. The model-detail response reported
the model as active with a 4,096-token context and 4,096-token completion limit.
The catalog did not establish account-specific pricing, privacy eligibility,
or quota for the candidate.

Groq's documentation says exact account limits are visible in the account
limits page and exposed through rate-limit response headers, and its data
controls documentation says inference inputs and outputs are not retained by
default. The owner-supplied free-plan and prior rate-limit evidence was reused;
the model-detail response itself returned no rate-limit headers. See the
[Groq rate-limit documentation](https://console.groq.com/docs/rate-limits) and
[Groq data-controls documentation](https://console.groq.com/docs/your-data).

Gemini was not used for generation. Gemini's official documentation says exact
limits vary by model and project and must be checked in AI Studio; its free
tier also states that submitted content may be used to improve Google products.
That did not satisfy the accepted privacy/limit gate for this application.
See [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) and
[Gemini pricing and data-use terms](https://ai.google.dev/gemini-api/docs/pricing).

## Groq candidate result

`allam-2-7b` was the only discovered text candidate without an explicit
non-zero price and with JSON-mode metadata. It was used only with synthetic
policy text and a 256-token request cap.

| Measurement | Result |
| --- | --- |
| Application answer requests | 8 synthetic cases |
| External generation attempts | 6 through the application answer path, plus 1 direct adapter smoke |
| Model-accepted application answers | 1/6 |
| Direct adapter structured-output smoke | 1/1 valid, with one `evidence-1` citation |
| Deterministic fallback or safe handoff | 5/6 application attempts |
| Unsupported-question safety | Safe handoff; no provider call |
| Output cap | 256 tokens configured |
| Observed direct-smoke usage | 184 total tokens (transient provider response) |
| Activation decision | **Rejected; not qualified** |

The application path did not meet the existing model-quality policy (at least
90% supported-answer accuracy, 95% citation validity, 100% unsupported safety,
and zero false acceptance). The candidate was not written as `ACTIVE`, was not
made available to ordinary customer traffic, and was not used through the
trusted routed evaluation factory. The trusted route correctly remained
unavailable because it requires a qualified model.

The 48-request and 50,000-token ceiling was not approached. Aggregate provider
usage was not persisted by this early-stop probe, so no unobserved aggregate
token total is claimed; the only retained usage sample is the direct-smoke
value above. No further live requests are justified for this candidate.

## Next decision

Keep deterministic generation and local Gemma evaluation as the default. A
future hosted tranche requires a candidate with verified account-level free
limits and privacy terms, then must use the trusted PostgreSQL quota factory
and a fresh synthetic qualification set. No provider should be activated from
this report.
