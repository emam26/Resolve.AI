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

export interface AppendMessageResponse {
  conversation_id: string;
  state: ConversationState;
  message: ConversationMessage;
  assistant_reply: ConversationMessage | null;
  evidence: Record<string, unknown>[];
  handoff_reason: string | null;
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
