# ResolveAI product context (current V1, synthetic-data-first)

## Product and audience
ResolveAI is a credible **agentic customer-operations resolution platform**, not a generic FAQ bot. The initial merchant is a fictional e-commerce store (working name **ShopEase**). The application demonstrates the flow from customer inquiry -> verified business facts and published policy -> grounded response or handoff -> staffed resolution / refund review, using only seeded records.

## Four product roles (distinct from coding agents)
- **Customer/shopper:** uses a storefront support widget; may ask public policy questions anonymously. Private own-order inquiry requires server-verified demo customer identity. Knowing an order ID alone does not prove ownership.
- **Support agent:** claims queue cases, reviews scoped order/policy evidence, replies as a human, maintains support tickets, prepares refund review. Cannot approve a request they prepared.
- **Refund approver:** approves/rejects policy-eligible requests after reviewing evidence; cannot trigger money movement in V1.
- **Merchant admin:** manages fictional workspace, staff role grants and policy releases; not automatically an approver. Staff roles share one React console.
AI is a system actor; not a customer/staff role.

## Main V1 scenarios
1. **Delayed order/status investigation:** widget asks a question -> backend authenticates demo customer for private facts -> typed business tool retrieves that customer's order/shipment/payment summary from PostgreSQL -> policy RAG retrieves active published delivery policy -> one controlled LangGraph workflow produces a grounded answer or handoff.
2. **Refund review:** support case -> backend deterministic eligibility/status rules -> pending refund request -> authorized separate approver approves/rejects -> approval status is `APPROVED_EXTERNAL_ACTION_REQUIRED`. This is a **simulated external follow-up**, never `REFUNDED` or actual payment execution.

## Application shape
- **Backend:** one Python/FastAPI/Pydantic application, SQLAlchemy/Alembic and PostgreSQL; explicit server-side authorization and state transitions.
- **AI/RAG:** one LangGraph workflow using one LLM SDK; authorized Python tools for order facts; published Markdown/plain-text policy chunks and metadata, sentence-transformers embeddings + pgvector; PostgreSQL full-text baseline. Deterministic fake LLM for most tests; user-authorized live model eval later.
- **Frontend:** React + TypeScript + Vite with query-surface navigation. Staff UI with sign-in/demo workspace, overview, knowledge, inbox, refund review, minimal team/settings. Separate lightweight embeddable widget. Stable loading/empty/denial/error states.
- **Engineering:** pytest/HTTPX, focused frontend checks, Git, Docker Compose and GitHub Actions when needed. No premature microservices, Redis, Celery, Kubernetes, CrewAI, separate vector DB, arbitrary agent architectures or payment-write API.

## Visual contract
Preserve approved B2B SaaS palette: dark navy sidebar `#102b39`, teal action `#128476`, pale page canvas `#f5f8f7`, white panels/cards. Three-pane support inbox on desktop, evidence drawer on mobile, separate embedded widget. Existing prototype in `references/` is the authoritative visual specification, not working production source.

## Security and important distinctions
- Explicitly labeled demo authentication is acceptable only for synthetic records. Protect other customers' orders; authorization comes from server identity, not client-supplied role/order ID.
- Conversation states: `AI_ACTIVE -> HANDOFF_QUEUED -> HUMAN_ACTIVE -> RESOLVED`; no automated customer-facing AI reply in `HUMAN_ACTIVE`.
- Knowledge states: draft/indexing/testable/published/failed; publish active release atomically and never expose unpublished/internal evidence to public customers.
- Refund states: pending / rejected / approved-external-action-required; preserve idempotency, audit and separation of duties. Approval != refund execution.
- On missing data or weak retrieval, answer with uncertainty/handoff rather than invent status or policy.

## Phased rollout
- **V1:** seeded one-merchant product, two scenarios, authentic local business logic, RAG/LLM integration, staff UI and widget, review/evals/tests. No external provider integrations.
- **V1.1:** authorized Shopify read-only connector and other first-pilot hardening. Real identity verification and operator safeguards before handling external customer records.
- **V2:** multi-merchant SaaS onboarding, billing, analytics and commercial readiness.
- **V3:** additional channels/connectors and optional advanced automation justified by measured need.

## Development philosophy
Target the smallest tested *vertical slice* rather than disconnected demos. Do not introduce technology purely as a resume keyword. The focus is on working, understandable code and justified choices. Credentials and live paid API execution are the owner's manual actions.
