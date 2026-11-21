---
name: review-change
description: Review a stable ResolveAI development diff for correctness, authorization, QA, integration and unnecessary complexity; produce concise evidenced findings and run the minimum useful local tests. Use at worker handoff and milestone integration.
---
# Review a stable change

1. Receive bounded task outcome, frozen interface, changed files and test results. If files are still being edited, request a stable checkpoint.
2. Inspect only changed code and immediate dependencies/tests. Check scope creep, redundant implementations, new libraries, and unnecessary abstractions.
3. Validate critical V1 invariants relevant to the change: customer/order isolation, staff roles, human takeover blocking AI replies, published policy version/citations, refund `APPROVED_EXTERNAL_ACTION_REQUIRED` and zero provider payment writes.
4. Check contract compatibility and meaningful negative/failure tests. When able, execute the smallest relevant test command; full suites are for integration milestones. A reported test result is not your own verification.
5. Report up to five **actionable** P0/P1/P2 findings with exact file/symbol, observed failure or reason, effect and smallest corrective action. Separate verified defects from hypotheses. Include tests executed vs not verified. Read-only reviewer does not fix files.
6. Avoid duplicating past findings absent new changes. If no significant issue, report 'No actionable findings' briefly. Lead tracks dispositions in milestone handoff; no separate review artifact needed by default.
