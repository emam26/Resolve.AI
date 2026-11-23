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

export interface OpsActivity {
  activity_id: string;
  kind: string;
  label: string;
  occurred_at: string | null;
  conversation_id?: string | null;
}

export interface OpsSummary {
  total_conversations: number;
  active_conversations: number;
  waiting_for_human: number;
  resolved_conversations: number;
  pending_refund_reviews: number;
  recent_activity: OpsActivity[];
}

export type PolicyStatus = "draft" | "indexing" | "testable" | "published" | "failed" | string;
export type PolicyVisibility = "public" | "internal" | string;

export interface KnowledgePolicySummary {
  document_id: string;
  title: string;
  document_version: string;
  status: PolicyStatus;
  visibility: PolicyVisibility;
  updated_at: string | null;
  section_count: number;
}

export interface KnowledgePolicySection {
  section: string;
  content: string;
}

export interface KnowledgePolicyDetail extends KnowledgePolicySummary {
  effective_from: string | null;
  effective_to: string | null;
  sections: KnowledgePolicySection[];
}

export interface KnowledgePoliciesResponse {
  policies: KnowledgePolicySummary[];
  total: number;
}

export interface WorkspaceTeamMember {
  actor_id: string;
  display_name: string;
  role: ActorRole;
  status: string;
  permissions: string[];
}

export interface WorkspaceTeamResponse {
  members: WorkspaceTeamMember[];
}

export interface WorkspaceSettings {
  merchant_name: string;
  environment: string;
  retrieval_mode: string;
  generation_mode: string;
  synthetic_data: boolean;
}

export interface WorkspaceSettingsResponse {
  settings: WorkspaceSettings;
}

interface BackendOperationsSummary {
  total_conversations: number;
  active_conversations: number;
  waiting_conversations: number;
  resolved_conversations: number;
  pending_refund_reviews: number;
  recent_activity: Array<{
    conversation_id: string;
    state: string;
    order_id: string | null;
    customer_id: string;
    assigned_staff_id: string | null;
    activity_type: string;
    last_activity_at: string | null;
  }>;
}

interface BackendPolicySection {
  document_id: string;
  document_version: string;
  section: string;
  release_id: string;
  status: string;
  visibility: string;
  text: string;
}

interface BackendPolicyListResponse {
  policies: BackendPolicySection[];
}

interface BackendPolicyDocumentResponse {
  document_id: string;
  policies: BackendPolicySection[];
}

interface BackendWorkspaceTeamResponse {
  team: ActorSummary[];
}

interface BackendWorkspaceSettingsResponse {
  merchant_name: string;
  policy_source: string;
  policy_retrieval_mode: string;
  response_generation_mode: string;
  database_ready: boolean;
  commerce_database_configured: boolean;
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

export function loginDemoMerchantAdmin(): Promise<DemoLoginResponse> {
  return requestJson<DemoLoginResponse>("/api/v1/auth/demo-login", {
    method: "POST",
    body: JSON.stringify({ demo_actor_id: "merchant_admin_001" }),
  });
}

export function getOpsSummary(sessionId: string): Promise<OpsSummary> {
  return requestJson<BackendOperationsSummary>("/api/v1/ops/summary", {}, sessionId).then((raw) => ({
    total_conversations: raw.total_conversations,
    active_conversations: raw.active_conversations,
    waiting_for_human: raw.waiting_conversations,
    resolved_conversations: raw.resolved_conversations,
    pending_refund_reviews: raw.pending_refund_reviews,
    recent_activity: raw.recent_activity.map((item) => ({
      activity_id: item.conversation_id,
      kind: item.activity_type,
      label: `${item.conversation_id} · ${item.state}`,
      occurred_at: item.last_activity_at,
      conversation_id: item.conversation_id,
    })),
  }));
}

function summarizePolicySections(sections: BackendPolicySection[]): KnowledgePolicySummary[] {
  const grouped = new Map<string, KnowledgePolicySummary>();
  for (const section of sections) {
    const key = `${section.document_id}:${section.document_version}`;
    const current = grouped.get(key);
    if (current) {
      current.section_count += 1;
      continue;
    }
    grouped.set(key, {
      document_id: section.document_id,
      title: section.document_id,
      document_version: section.document_version,
      status: section.status,
      visibility: section.visibility,
      updated_at: null,
      section_count: 1,
    });
  }
  return [...grouped.values()].sort((left, right) =>
    `${left.document_id}:${left.document_version}`.localeCompare(`${right.document_id}:${right.document_version}`),
  );
}

export function getKnowledgePolicies(
  sessionId: string,
  options: { query?: string; status?: string } = {},
): Promise<KnowledgePoliciesResponse> {
  const params = new URLSearchParams();
  if (options.query?.trim()) params.set("q", options.query.trim());
  if (options.status && options.status !== "all") params.set("status", options.status);
  const query = params.toString();
  return requestJson<BackendPolicyListResponse>(
    `/api/v1/knowledge/policies${query ? `?${query}` : ""}`,
    {},
    sessionId,
  ).then((raw) => {
    const policies = summarizePolicySections(raw.policies);
    return { policies, total: policies.length };
  });
}

export function getKnowledgePolicy(
  sessionId: string,
  documentId: string,
  version?: string,
): Promise<KnowledgePolicyDetail> {
  const query = version ? `?version=${encodeURIComponent(version)}` : "";
  return requestJson<BackendPolicyDocumentResponse>(
    `/api/v1/knowledge/policies/${encodeURIComponent(documentId)}${query}`,
    {},
    sessionId,
  ).then((raw) => {
    const sections = raw.policies;
    const first = sections[0];
    return {
      document_id: raw.document_id,
      title: raw.document_id,
      document_version: first?.document_version ?? version ?? "unknown",
      status: first?.status ?? "unknown",
      visibility: first?.visibility ?? "unknown",
      updated_at: null,
      section_count: sections.length,
      effective_from: null,
      effective_to: null,
      sections: sections.map((section) => ({ section: section.section, content: section.text })),
    };
  });
}

export function getWorkspaceTeam(sessionId: string): Promise<WorkspaceTeamResponse> {
  return requestJson<BackendWorkspaceTeamResponse>("/api/v1/workspace/team", {}, sessionId).then((raw) => ({
    members: raw.team.map((member) => ({ ...member, status: "active" })),
  }));
}

export function getWorkspaceSettings(sessionId: string): Promise<WorkspaceSettingsResponse> {
  return requestJson<BackendWorkspaceSettingsResponse>("/api/v1/workspace/settings", {}, sessionId).then((raw) => ({
    settings: {
      merchant_name: raw.merchant_name,
      environment: raw.database_ready ? "local · ready" : "local · not ready",
      retrieval_mode: raw.policy_retrieval_mode,
      generation_mode: raw.response_generation_mode,
      synthetic_data: true,
    },
  }));
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
