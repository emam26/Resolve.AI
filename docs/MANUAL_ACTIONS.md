# Human-owned tasks and cost controls

The product owner prefers to handle external/manual operations that could create token costs, paid API usage or account/credential exposure. Coding agents should prepare precise instructions but not autonomously perform these operations.

## Owner performs (only when a milestone actually needs it)
- Create external service/provider accounts, obtain credentials and set local `.env` values privately.
- Approve and perform real LLM/embedding API requests or paid external evaluations. Set spending limits in provider UI where supported.
- Approve downloading/installing major new dependencies, GitHub remote pushes/PR merges, deployments and other external actions.
- Review UI demos, product scope changes and final milestone acceptance.

## Agents do without paid calls (within approved local milestone)
- Write and test API clients/tool interfaces and typed Python functions using **fake** responses and synthetic data.
- Write FastAPI/React/PostgreSQL code, seeded sample records, deterministic RAG test cases, unit/integration tests, setup instructions.
- Run local tests and compilers where the environment and dependencies already support them.
- Document the exact command and minimal credentials expected for a future real test; never generate fake 'live results'.

## Real external evaluation gate
Before any real API test, lead reports: provider, purpose, request count/token upper bound, estimated cost if estimable, how to stop and expected evidence. Wait for human approval. Prefer minimal smoke tests first. Failed network access is a blocker, not grounds to silently repeat paid calls.

## Safety
Never commit `.env` or secret files; avoid printing secrets in command output. Do not use production customer data. Seeded demo identities must not be mistaken for real authentication.
