# ResolveAI — Codex Agentic Starter (v2)

**For:** Antigravity IDE + an already-working Codex extension. No Codex CLI, desktop app, MCP server, extra agent framework, or paid external API connection is necessary.

This bundle is **durable guidance, reusable skills, and project references**, not an implemented ResolveAI application or a running orchestration service.

## Your 5 roles
- Agent 0: **Lead / orchestrator** — plans, assigns, integrates and reports.
- Agent 1: **Backend worker** — FastAPI/PostgreSQL/business rules.
- Agent 2: **AI/RAG worker** — retrieval, LangGraph, evaluations.
- Agent 3: **Frontend worker** — React/TypeScript/widget/console.
- Agent 4: **Read-only independent reviewer** — correctness + security + QA + integration + simplicity + token efficiency. Reviews stable checkpoints while development continues.

The verified Codex session exposes `spawn_agent`, `send_input`, `wait_agent`, `resume_agent`, and `close_agent`. Role files are **prompt templates**, not permanently installed agent profiles. The lead spawns workers with assigned prompts. Context forks do **not** imply Git worktree isolation. Set up a Git repo before using worktrees, and use disjoint file ownership until isolation is verified.

## First-time install (Windows / Antigravity)
1. Open `F:\ResolveAI` in Antigravity. You said this folder has no project material yet, so no application source should be overwritten. Still **inspect existing files first**; keep `j.py` until you decide what it is.
2. Extract the **contents** of this ZIP into the repository root (`F:\ResolveAI`), preserving hidden `.agents/` and `AGENTS.md`. The ZIP should not add an extra nested folder. If a matching file already exists, review/merge instead of blind overwrite.
3. In the existing Codex chat, ask it to read `AGENTS.md`, then paste `prompts/START_LEAD.md` (or ask Codex to follow that file). This is the **only initial prompt** you need.
4. The lead inspects the real workspace, initializes Git if absent, preserves existing files, and records actual project state. It freezes the first small interface before delegating implementation.
5. When a bounded milestone is authorized, the lead delegates selectively, uses the reviewer at stable checkpoints, runs local tests, and returns one milestone report. You do not need to paste a prompt to each worker manually if native `spawn_agent` works.

## Avoid doing the same task twice
**`docs/PROJECT_STATE.md` is the shared project-memory index.** It records what already works, where code/tests live, test commands, what failed, and what is next. Every future lead session begins by checking it **and verifying reality in Git/source/tests**. This prevents re-implementing features on a fresh session. `docs/DECISIONS.md` captures stable architecture decisions; `.agents/skills/` carries repeatable review/reuse/evaluation instructions. These files do not automatically update themselves: the lead must write concise updates after verified milestones.

## Reusable skills
- `.agents/skills/reuse-first/SKILL.md`: find an existing implementation, tests and contract *before* writing new code.
- `.agents/skills/review-change/SKILL.md`: independent, evidence-based, low-noise review and test checklist.
- `.agents/skills/policy-rag-check/SKILL.md`: repeatable RAG benchmark without paid LLM calls by default.

Skills are project-local and can be discovered by Codex from `.agents/skills/` in supported hosts; if skill auto-discovery is unavailable, the lead can read the `SKILL.md` directly. Do **not** add a large third-party skills bundle yet.

## Human vs agents
Codex writes backend/frontend/agent integration code, fixtures, and **mocked** tool calls. **You** handle accounts, API keys, external paid calls, and deployment decisions. Agents must ask approval before invoking live paid external models or APIs. Local unit tests and free synthetic fixtures are the default.

## Source of truth
1. Current explicit instructions from the product owner and this repository's `AGENTS.md`.
2. `docs/PRODUCT_CONTEXT.md`, `docs/CONTRACTS.md`, `docs/DECISIONS.md`.
3. Actual source code/tests/Git state (for what is implemented).
4. `docs/PROJECT_STATE.md` as a *verified index*, not proof by itself.
5. Approved design in `references/` for look-and-feel only.

**Historical caution:** the old `ResolveAI_Lean_V1_Development_Plan.md` was written before Shopify was deferred, and some old API contracts assumed Shopify integration. They are not the current V1 authority. This bundle reflects the later synthetic-data-first decision.
