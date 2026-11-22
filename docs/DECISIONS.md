# ResolveAI durable decisions (append only for meaningful changes)

| Decision | Why | Status |
|---|---|---|
| V1 uses **synthetic company/order data**, no Shopify | No merchant connection; permits repeatable testable development | Frozen |
| One backend + one PostgreSQL + React console/widget | Less integration and operational overhead | Frozen |
| LangGraph single workflow; policy RAG + pgvector, text baseline | Demonstrate controlled AI, retrieval quality, grounded action | Frozen |
| Refund approvals do not execute funds | Human-controlled financial decisions; simulation is honest | Frozen |
| Four product roles, server-enforced permissions | Realistic separation of duties and customer privacy | Frozen |
| Navy/teal ResolveAI visuals retained | Approved UI; don't relitigate design | Frozen |
| One lead + 3 on-demand coding workers + 1 independent read-only reviewer | Delegation where useful, consolidation of review | Frozen for current development |
| Reuse-first task lookup via `docs/PROJECT_STATE.md` | Prevent redo after new agent conversations, save tokens | Frozen |
| Offline mocked tests default, user runs paid external calls | Avoid accidental runtime API costs | Frozen |
| Inject policy retrieval through the existing LangGraph answer node; report retrieval mode and fall back to lexical on backend failure | Preserve one controlled workflow, keep deterministic local operation, and avoid presenting degraded retrieval as semantic success | M6 |

Do not record every implementation detail here; use Git commits/tests and `docs/PROJECT_STATE.md` for routine progress. A new decision entry requires the problem, chosen option, and rationale.
