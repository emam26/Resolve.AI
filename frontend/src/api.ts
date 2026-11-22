export type ActorRole =
  | "customer"
  | "support_agent"
  | "refund_approver"
  | "merchant_admin";

export type ConversationState =
  | "AI_ACTIVE"
  | "HANDOFF_QUEUED"
  | "HUMAN_ACTIVE"
  | "RESOLVED";

export type MessageAuthorType = "customer" | "assistant" | "staff";

export interface ActorSummary {
  actor_id: string;
  display_name: string;
  role: ActorRole;
  customer_id: string | null;
  permissions: string[];
}

export interface DemoLoginResponse {
  session_id: string;
  actor: ActorSummary;
}

export interface ConversationMessage {
  message_id: string;
  author_type: MessageAuthorType;
  content: string;
  created_at: string;
}

export interface ConversationResponse {
  conversation_id: string;
  channel: "widget";
  state: ConversationState;
  order_id: string | null;
  messages: ConversationMessage[];
}

export interface SupportConversationSummary {
  conversation_id: string;
  channel: ConversationResponse["channel"];
  state: ConversationState;
  order_id: string | null;
  customer_id: string | null;
  assigned_staff_id: string | null;
  messages: ConversationMessage[];
}

export interface SupportInboxResponse {
  conversations: SupportConversationSummary[];
}

export type RetrievalMode = "not_applicable" | "lexical" | "semantic" | "lexical_fallback";
export type GenerationMode = "deterministic" | "model";

export interface PolicyEvidence {
  document_id: string;
  document_version: string;
  section: string;
  release_id: string;
  visibility: "public" | "internal";
  score: number;
  text: string;
}

export type RefundState =
  | "PENDING_REVIEW"
  | "APPROVED_EXTERNAL_ACTION_REQUIRED"
  | "REJECTED";

export interface RefundSummary {
  refund_id: string;
  conversation_id: string;
  order_id: string;
  amount_cents: number;
  reason: string;
  state: RefundState;
  requested_by: string;
  decided_by: string | null;
  decision_note: string | null;
}

export interface CreateRefundRequest {
  amount_cents: number;
  reason: string;
  idempotency_key: string;
}

export interface RefundListResponse {
  refunds: RefundSummary[];
}

export interface AppendMessageResponse {
  conversation_id: string;
  state: ConversationState;
  message: ConversationMessage;
  assistant_reply: ConversationMessage | null;
  evidence: PolicyEvidence[];
  handoff_reason: string | null;
  retrieval_mode: RetrievalMode;
  generation_mode: GenerationMode;
  citation_ids: string[];
}

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    message: string,
    code = "request_failed",
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

async function requestJson<T>(
  path: string,
  options: RequestInit = {},
  sessionId?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (sessionId) {
    headers.set("Authorization", `Bearer ${sessionId}`);
  }

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, "The local API could not be reached.", "network_error");
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const envelope = (payload ?? {}) as ErrorEnvelope;
    const error = envelope.error;
    throw new ApiError(
      response.status,
      error?.message ?? `The request failed with status ${response.status}.`,
      error?.code,
      error?.details,
    );
  }

  return payload as T;
}

export function loginDemoCustomer(): Promise<DemoLoginResponse> {
  return requestJson<DemoLoginResponse>("/api/v1/auth/demo-login", {
    method: "POST",
    body: JSON.stringify({ demo_actor_id: "customer_001" }),
  });
}

export function loginDemoSupport(): Promise<DemoLoginResponse> {
  return requestJson<DemoLoginResponse>("/api/v1/auth/demo-login", {
    method: "POST",
    body: JSON.stringify({ demo_actor_id: "support_001" }),
  });
}

export function loginDemoRefundApprover(): Promise<DemoLoginResponse> {
  return requestJson<DemoLoginResponse>("/api/v1/auth/demo-login", {
    method: "POST",
    body: JSON.stringify({ demo_actor_id: "refund_approver_001" }),
  });
}

export function createWidgetConversation(
  sessionId: string,
  orderId: string | null,
): Promise<ConversationResponse> {
  return requestJson<ConversationResponse>(
    "/api/v1/conversations",
    {
      method: "POST",
      body: JSON.stringify({ channel: "widget", order_id: orderId }),
    },
    sessionId,
  );
}

export function appendCustomerMessage(
  sessionId: string,
  conversationId: string,
  content: string,
): Promise<AppendMessageResponse> {
  return requestJson<AppendMessageResponse>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`,
    {
      method: "POST",
      body: JSON.stringify({ content }),
    },
    sessionId,
  );
}

export function handoffCustomerConversation(
  sessionId: string,
  conversationId: string,
): Promise<ConversationResponse> {
  return requestJson<ConversationResponse>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/handoff`,
    { method: "POST" },
    sessionId,
  );
}

export function getSupportInbox(sessionId: string): Promise<SupportInboxResponse> {
  return requestJson<SupportInboxResponse>("/api/v1/support/inbox", {}, sessionId);
}

export function claimSupportConversation(
  sessionId: string,
  conversationId: string,
): Promise<SupportConversationSummary> {
  return requestJson<SupportConversationSummary>(
    `/api/v1/support/conversations/${encodeURIComponent(conversationId)}/claim`,
    { method: "POST" },
    sessionId,
  );
}

export function appendSupportMessage(
  sessionId: string,
  conversationId: string,
  content: string,
): Promise<AppendMessageResponse> {
  return requestJson<AppendMessageResponse>(
    `/api/v1/support/conversations/${encodeURIComponent(conversationId)}/messages`,
    {
      method: "POST",
      body: JSON.stringify({ content }),
    },
    sessionId,
  );
}

export function resolveSupportConversation(
  sessionId: string,
  conversationId: string,
): Promise<SupportConversationSummary> {
  return requestJson<SupportConversationSummary>(
    `/api/v1/support/conversations/${encodeURIComponent(conversationId)}/resolve`,
    { method: "POST" },
    sessionId,
  );
}

export function createRefund(
  sessionId: string,
  conversationId: string,
  request: CreateRefundRequest,
): Promise<RefundSummary> {
  return requestJson<RefundSummary>(
    `/api/v1/support/conversations/${encodeURIComponent(conversationId)}/refunds`,
    {
      method: "POST",
      body: JSON.stringify(request),
    },
    sessionId,
  );
}

export function getRefunds(sessionId: string): Promise<RefundListResponse> {
  return requestJson<RefundListResponse>("/api/v1/refunds", {}, sessionId);
}

export function approveRefund(sessionId: string, refundId: string): Promise<RefundSummary> {
  return requestJson<RefundSummary>(
    `/api/v1/refunds/${encodeURIComponent(refundId)}/approve`,
    { method: "POST" },
    sessionId,
  );
}

export function rejectRefund(sessionId: string, refundId: string): Promise<RefundSummary> {
  return requestJson<RefundSummary>(
    `/api/v1/refunds/${encodeURIComponent(refundId)}/reject`,
    { method: "POST" },
    sessionId,
  );
}
