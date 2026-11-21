---
name: reuse-first
description: Avoid duplicate ResolveAI coding work by locating existing implementations, tests, contracts, project decisions and reusable skills before changing a nontrivial feature. Use during planning or at the start of a worker task.
---
# Reuse before rebuild

1. Identify the exact requested behavior and relevant bounded path. Do **not** read the entire repo by default.
2. Look up `docs/PROJECT_STATE.md` for capability status, files and known test commands. Cross-check real source/Git: documentation is a pointer, not proof.
3. Search *relevant* files for existing endpoints/functions/components/fixtures and their tests (`rg` or `git grep` scoped by directories; narrow search terms). Check `docs/CONTRACTS.md` for an existing shape.
4. Choose one: **reuse unchanged**, **extend existing code**, **fix a verified gap**, or **implement missing behavior**. Prefer the first that satisfies acceptance criteria. Do not create competing implementations or duplicative tests.
5. Consult a relevant local skill instead of recreating its repeatable workflow. Keep the worker's context packet short: reuse paths + frozen contract + acceptance tests; no full doc dump.
6. After an actually verified milestone, lead records reusable path/test command and result once in `docs/PROJECT_STATE.md`. Update `docs/DECISIONS.md` only for lasting architecture choices.

**Tiny task rule:** if a file and fix are already obvious, skip this procedure and make the fix. Token reduction comes from avoiding needless rework, not running elaborate checklists for everything.
