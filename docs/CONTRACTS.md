# V1 contracts — lead-owned provisional handshake

**Status: draft, not a frozen OpenAPI specification.** Before a cross-component parallel batch, the lead freezes only the endpoints and response models that batch needs. Keep one source of truth; do not allow workers to invent divergent schemas. Business data below is synthetic.

## Backend/API principles
- Suggested prefix `/api/v1`, consistent structured error responses and role-appropriate responses.
- Authenticate actors server-side. Private order lookup requires verified customer-session ownership OR authorized staff access linked to the case. No raw order ID as sole proof. Nonexistent/foreign records should not leak existence to customers.
- Tool calls go through typed services. Customer-facing model never decides refund eligibility, authorization, or approval state.
- Use stable IDs and timestamps. Define fields once using Pydantic and generated/derived TypeScript types when practical; avoid hand-maintained duplicate shapes.

## First thin-slice endpoints (freeze these first)
- `POST /api/v1/auth/demo-login` — **demo only**, returns established synthetic actor/session; production credential verification is not implied. Role/customer relationship is checked server-side.
- `GET /api/v1/me` — authenticated actor details and role grants.
- `GET /api/v1/orders/{order_id}` — actor-scoped order summary with order status, payment status and shipment status; never another customer's order.
- `POST /api/v1/conversations` — begin a widget conversation.
- `POST /api/v1/conversations/{id}/messages` — append a message and return accepted state, tool/policy evidence where appropriate, and handoff state. The server determines the author; client cannot impersonate staff.
- `GET /api/v1/conversations/{id}` — authorized transcript and state.

**Lead must write exact request/response JSON and denial/error contracts before delegating these paths.** Do not build all endpoints upfront. If streaming isn't necessary, use normal HTTP responses in V1.

### M0 frozen contract: demo identity and order investigation

This contract is the minimum handshake for the first implementation milestone. It is intentionally HTTP/JSON-shaped even before the FastAPI application exists. All IDs and records are synthetic.

#### Authentication

`POST /api/v1/auth/demo-login`

Request:

```json
{
  "demo_actor_id": "customer_001"
}
```

The server accepts only a configured synthetic demo actor ID. The client does not submit a role or customer relationship.

Success `200 OK`:

```json
{
  "session_id": "demo-session-customer_001",
  "actor": {
    "actor_id": "customer_001",
    "display_name": "Demo Customer",
    "role": "customer",
    "customer_id": "customer_001",
    "permissions": ["orders:read:self"]
  }
}
```

Invalid or unknown demo actor `422 Unprocessable Entity`:

```json
{
  "error": {
    "code": "invalid_demo_actor",
    "message": "The requested demo actor is not available.",
    "details": {}
  }
}
```

#### Current actor

`GET /api/v1/me`

Authentication: `Authorization: Bearer demo-session-customer_001`

Success `200 OK`:

```json
{
  "actor_id": "customer_001",
  "display_name": "Demo Customer",
  "role": "customer",
  "customer_id": "customer_001",
  "permissions": ["orders:read:self"]
}
```

Missing or invalid session `401 Unauthorized`:

```json
{
  "error": {
    "code": "unauthenticated",
    "message": "Authentication is required.",
    "details": {}
  }
}
```

#### Customer-scoped order summary

`GET /api/v1/orders/{order_id}`

Authentication: `Authorization: Bearer demo-session-customer_001`

Success `200 OK`:

```json
{
  "order_id": "order_1001",
  "status": "delayed",
  "payment_status": "paid",
  "shipment_status": "delayed",
  "estimated_delivery_date": "2026-11-08"
}
```

Missing or foreign order `404 Not Found` (existence-hiding contract):

```json
{
  "error": {
    "code": "order_not_found",
    "message": "The requested order was not found.",
    "details": {}
  }
}
```

The first implementation may support only customer self-access. Staff access linked to an authorized case is a later milestone and must not be inferred from a client-supplied role or order ID.

#### M0 model constraints

- `role` is one of `customer`, `support_agent`, `refund_approver`, or `merchant_admin`.
- M0 order `status` is one of `processing`, `in_transit`, `delayed`, `delivered`, or `cancelled`.
- M0 `payment_status` is one of `pending`, `paid`, or `failed`; no refund transaction is represented.
- M0 `shipment_status` is one of `not_shipped`, `in_transit`, `delayed`, or `delivered`.
- `estimated_delivery_date` is an ISO date or `null`.
- The shared error envelope is `{ "error": { "code": string, "message": string, "details": object } }`.

## Later V1 endpoints (add when milestone needs them)
- Knowledge: document create/list -> index -> test retrieval -> publish active version -> get published release.
- Support: queue/list, conversation claim/takeover, human reply, resolve, ticket create/list/detail.
- Refunds: request from linked case, list/detail, approve/reject; review decision only. No provider refund endpoint.
- Settings: basic demo memberships/role grants as needed, enforced server-side.

## Canonical state invariants
- Conversation `AI_ACTIVE -> HANDOFF_QUEUED -> HUMAN_ACTIVE -> RESOLVED`; claims atomic, a second claim conflicts; human state prohibits AI auto-replies.
- Policy release: `DRAFT -> INDEXING -> READY_FOR_TEST -> PUBLISHED` or `FAILED`; last published release stays active if new indexing fails. Source citation includes document/version/section/release.
- Refund: `PENDING_REVIEW -> APPROVED_EXTERNAL_ACTION_REQUIRED | REJECTED`; no `REFUNDED` based on approval. Idempotent pending creation, amount constraints, actor separation and audit record.
- Provider capabilities not applicable in V1; do not add Shopify capability flags or integration routes now.

## Response/error expectations
- Relevant `401` unauthenticated, `403` forbidden, `404` missing or existence-hiding, `409` duplicate/ownership/state conflict, `422` validation; do not invent 200 success for denied actions.
- Cited answers must reference active published policy evidence, never draft or internal policies.
- Distinguish API transport success from grounded AI answer; uncertain answers can hand off.

## Rule for changes
The lead owns this document and the shared OpenAPI contract when created. Worker requests a modification; lead evaluates/updates contract and communicates the change **before** multiple workers implement it. Record any change in `docs/DECISIONS.md` if it is architectural, not merely a field correction.
