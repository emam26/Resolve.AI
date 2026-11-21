# ResolveAI — durable Codex project guidance

## Mission and priorities
Build a **lean, working** AI customer-operations application for one fictional merchant using synthetic data. The order of priorities is: correct end-to-end behavior > authorization and data integrity > reproducible tests > readability > simplicity/performance. **Reuse existing code and proven workflows before writing new code.** Avoid unnecessary abstractions, dependencies, documentation, and speculative infrastructure.

## V1 decisions (do not renegotiate without the owner)
- One FastAPI/Pydantic/SQLAlchemy/Alembic backend, one PostgreSQL database; React/TypeScript/Vite staff console plus separate embeddable customer widget. Add libraries when their feature is implemented.
- One controlled LangGraph workflow and one model SDK; RAG over versioned Markdown/plain-text policies with sentence-transformers embeddings and pgvector; compare against PostgreSQL text search. Typed Python services/tools fetch transaction facts; **never generate arbitrary SQL from LLM output**.
- One fictional merchant, seeded customers/orders/shipments/payments, public policies. Roles: customer, support agent, refund approver, merchant admin. AI is a system actor, not a fifth human role.
- Primary scenarios: order status/delay and refund **review**. Other requests: answer only from relevant published policy or escalate safely.
- Customer order access requires server-established identity/ownership; explicitly marked demo login is allowed only for synthetic/demo data. Enforce staff roles on the server. Admin is not implicitly a refund approver.
- Human takeover persists state and blocks autonomous replies. Refund approval records `APPROVED_EXTERNAL_ACTION_REQUIRED`, **not** a refund transaction. No provider payment operations.
- **No Shopify integration, real external merchant, or real customer data in V1.** Shopify read-only integration is later (V1.1); commercial multi-tenancy and billing later.
- Preserve navy/teal visual design in `references/` (reference only; not proof of working functionality).

## Team and permissions
- **Lead (Agent 0):** owns planning, contracts, shared files, integration, review disposition, and final report.
- **Backend (Agent 1):** only assigned backend API/business/DB paths and tests.
- **AI/RAG (Agent 2):** only assigned `backend/app/ai/`, `backend/app/rag/`, associated tests and fixtures.
- **Frontend (Agent 3):** only assigned frontend files.
- **Independent Reviewer (Agent 4):** **read-only**; checks correctness, security, contract compliance, testing, simplicity, redundant work and agent-efficiency. Reports findings to lead; never edits.
- `spawn_agent` is available in the previously verified Codex IDE session, but agent spawn is not filesystem isolation. Never have two writers edit the same file. Delegate fewer workers if work is dependent or concurrency limits apply. Route worker coordination through lead. Follow `docs/TEAM_WORKFLOW.md`.

## Voice notifications
- Only the Lead Engineer may call the existing `scripts/notify.ps1`; workers and reviewers must report through the lead.
- At meaningful milestone checkpoints, call it with `-Event done`, `-Event review`, or `-Event blocked` and the milestone identifier.
- Do not announce routine progress, individual worker completions, or every test result. Notify at most once per event per milestone unless the status genuinely changes.
- If speech fails, report the failure in text and continue; voice is never a development blocker.

## Reuse-first and token discipline
1. For a nontrivial task, inspect `docs/PROJECT_STATE.md` (completed work / known files / test commands) and `docs/CONTRACTS.md` (interfaces); read only the relevant portions of `docs/PRODUCT_CONTEXT.md` and source files. Do not paste all documentation into every subagent prompt.
2. Search the relevant existing code/tests (`rg`/`git grep` scoped to directories) before implementing. **Use existing functions, fixtures, tests, and skills when they already solve the problem.** Do not regenerate a feature because a fresh prompt forgot it existed.
3. Use `.agents/skills/reuse-first/` for nontrivial new work, `.agents/skills/review-change/` for finished changes, `.agents/skills/policy-rag-check/` for RAG modifications. Skills are *on-demand procedures*, not background agents or magic memory.
4. Give workers one measurable outcome, exact allowed files, frozen interfaces, tests and stop conditions. Prefer targeted commands and brief outputs; avoid full-tree scans, repeated large logs, and duplicate reviews.
5. Default to mocks/fakes and offline deterministic tests. **Never spend paid LLM, embedding API, commerce API, or external service credits without explicit user approval.** Agents implement SDK/tool-calling code and test doubles; user handles credentials, real API requests and other manual external steps. No secrets in Git or reports.
6. Limit speculative debug cycles; after two unsuccessful attempts at the same cause, inspect evidence and change approach or report a blocker. Do not endlessly auto-retry.
7. At each completed **milestone**, update `docs/PROJECT_STATE.md` with verified status, exact reusable implementation/test paths, test commands/results and next action. Update `docs/DECISIONS.md` only for lasting architectural choices. Don't create duplicate status documents.

## Autonomous work boundaries
- For an **approved bounded milestone**: plan, delegate selectively, edit assigned files, test, read-only review, fix verified issues, and report results without asking at every step.
- M0 approval is no longer a stopping requirement. Continue autonomously through the approved M1 and M2 milestones using Plan -> Delegate -> Implement -> Test -> Independent Review -> Fix -> Verify.
- Ordinary free local development dependencies already justified by the approved stack (including FastAPI, SQLAlchemy, Alembic, pytest, and required frontend packages) are standing-authorized. Approval remains required for major architecture/scope changes, significant or unrelated dependencies, paid/authenticated network API actions, secrets, destructive data operations, remote pushes/PR merges, and deployment. Do not remove unknown existing files.
- Use three development workers when parallel work is beneficial and one read-only reviewer at meaningful checkpoints. Do not spawn unnecessary agents or run paid LLM evaluations.
- Pause only work requiring credentials, paid API usage, destructive operations, significant architecture changes, or human judgment; continue unrelated safe work where possible.
- Never claim an API call/test/browser check passed unless actually executed. Report unverified areas clearly. Never weaken security checks just to pass tests.
- Quality gates: authorization/ownership tests; published policy/version citations; human takeover blocking AI; refund state and duplicate protection; API contract parity; least relevant passing tests; honest demo labels.

## Navigation (load on demand)
- `docs/PRODUCT_CONTEXT.md`: what V1 is and is not.
- `docs/CONTRACTS.md`: provisional API/role/state handshake (lead freezes before parallel edits).
- `docs/PROJECT_STATE.md`: **single current status / reuse index / next milestone**.
- `docs/DECISIONS.md`: durable choices and why.
- `docs/TEAM_WORKFLOW.md`: delegation, review, conflicts, stop conditions.
- `docs/MANUAL_ACTIONS.md`: tasks reserved for the human.
- `prompts/START_LEAD.md`: first instruction to Codex lead.
