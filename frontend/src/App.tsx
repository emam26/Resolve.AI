import { FormEvent, useState } from "react";
import {
  ApiError,
  AppendMessageResponse,
  appendSupportMessage,
  appendCustomerMessage,
  approveRefund,
  claimSupportConversation,
  createWidgetConversation,
  ConversationResponse,
  DemoLoginResponse,
  getRefunds,
  getSupportInbox,
  handoffCustomerConversation,
  loginDemoRefundApprover,
  loginDemoSupport,
  loginDemoCustomer,
  rejectRefund,
  resolveSupportConversation,
  RefundSummary,
  SupportConversationSummary,
} from "./api";
import "./styles.css";

type NoticeKind = "error" | "denial";

interface Notice {
  kind: NoticeKind;
  message: string;
}

function noticeFromError(error: unknown): Notice {
  if (error instanceof ApiError) {
    return {
      kind: error.status === 401 || error.status === 403 || error.status === 404 ? "denial" : "error",
      message: error.message,
    };
  }
  return { kind: "error", message: "Something went wrong while contacting the local API." };
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatCents(value: number): string {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(value / 100);
}

export default function App() {
  const [session, setSession] = useState<DemoLoginResponse | null>(null);
  const [conversation, setConversation] = useState<ConversationResponse | null>(null);
  const [latestResolution, setLatestResolution] = useState<AppendMessageResponse | null>(null);
  const [orderId, setOrderId] = useState("order_1001");
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isHandingOff, setIsHandingOff] = useState(false);
  const [staffSession, setStaffSession] = useState<DemoLoginResponse | null>(null);
  const [supportInbox, setSupportInbox] = useState<SupportConversationSummary[]>([]);
  const [selectedSupportConversationId, setSelectedSupportConversationId] = useState<string | null>(null);
  const [staffDraft, setStaffDraft] = useState("");
  const [staffNotice, setStaffNotice] = useState<Notice | null>(null);
  const [isStaffStarting, setIsStaffStarting] = useState(false);
  const [isInboxLoading, setIsInboxLoading] = useState(false);
  const [isClaiming, setIsClaiming] = useState(false);
  const [isStaffSending, setIsStaffSending] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [approverSession, setApproverSession] = useState<DemoLoginResponse | null>(null);
  const [refunds, setRefunds] = useState<RefundSummary[]>([]);
  const [refundFilter, setRefundFilter] = useState<"pending" | "all">("pending");
  const [refundNotice, setRefundNotice] = useState<Notice | null>(null);
  const [isApproverStarting, setIsApproverStarting] = useState(false);
  const [isRefundsLoading, setIsRefundsLoading] = useState(false);
  const [activeRefundActionId, setActiveRefundActionId] = useState<string | null>(null);

  async function startDemoSession() {
    setNotice(null);
    setConversation(null);
    setLatestResolution(null);
    setIsStarting(true);
    try {
      setSession(await loginDemoCustomer());
    } catch (error) {
      setSession(null);
      setNotice(noticeFromError(error));
    } finally {
      setIsStarting(false);
    }
  }

  async function beginConversation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;

    setNotice(null);
    setIsCreating(true);
    try {
      setConversation(await createWidgetConversation(session.session_id, orderId.trim() || null));
      setLatestResolution(null);
    } catch (error) {
      setNotice(noticeFromError(error));
    } finally {
      setIsCreating(false);
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !conversation || isSending) return;

    const content = draft.trim();
    if (!content) {
      setNotice({ kind: "error", message: "Enter a message before sending." });
      return;
    }

    setNotice(null);
    setIsSending(true);
    try {
      const response = await appendCustomerMessage(
        session.session_id,
        conversation.conversation_id,
        content,
      );
      setConversation((current) =>
        current
          ? {
              ...current,
              state: response.state,
              messages: [
                ...current.messages,
                response.message,
                ...(response.assistant_reply ? [response.assistant_reply] : []),
              ],
            }
          : current,
      );
      setLatestResolution(response);
      setDraft("");
    } catch (error) {
      setNotice(noticeFromError(error));
    } finally {
      setIsSending(false);
    }
  }

  async function requestHumanSupport() {
    if (!session || !conversation || isHandingOff) return;
    setNotice(null);
    setIsHandingOff(true);
    try {
      setConversation(
        await handoffCustomerConversation(session.session_id, conversation.conversation_id),
      );
    } catch (error) {
      setNotice(noticeFromError(error));
    } finally {
      setIsHandingOff(false);
    }
  }

  async function loadSupportInbox(sessionId: string) {
    setIsInboxLoading(true);
    try {
      const response = await getSupportInbox(sessionId);
      setSupportInbox(response.conversations);
      setSelectedSupportConversationId((current) =>
        current && response.conversations.some((item) => item.conversation_id === current)
          ? current
          : response.conversations[0]?.conversation_id ?? null,
      );
    } catch (error) {
      setStaffNotice(noticeFromError(error));
    } finally {
      setIsInboxLoading(false);
    }
  }

  async function startStaffSession() {
    setStaffNotice(null);
    setIsStaffStarting(true);
    try {
      const nextSession = await loginDemoSupport();
      setStaffSession(nextSession);
      await loadSupportInbox(nextSession.session_id);
    } catch (error) {
      setStaffSession(null);
      setStaffNotice(noticeFromError(error));
    } finally {
      setIsStaffStarting(false);
    }
  }

  async function refreshStaffInbox() {
    if (!staffSession || isInboxLoading) return;
    setStaffNotice(null);
    await loadSupportInbox(staffSession.session_id);
  }

  function replaceSupportConversation(updated: SupportConversationSummary) {
    setSupportInbox((current) => {
      const existing = current.some((item) => item.conversation_id === updated.conversation_id);
      return existing
        ? current.map((item) => item.conversation_id === updated.conversation_id ? updated : item)
        : [updated, ...current];
    });
    setSelectedSupportConversationId(updated.conversation_id);
  }

  async function claimSelectedConversation() {
    const selected = supportInbox.find((item) => item.conversation_id === selectedSupportConversationId);
    if (!staffSession || !selected || isClaiming) return;

    setStaffNotice(null);
    setIsClaiming(true);
    try {
      replaceSupportConversation(
        await claimSupportConversation(staffSession.session_id, selected.conversation_id),
      );
    } catch (error) {
      setStaffNotice(noticeFromError(error));
    } finally {
      setIsClaiming(false);
    }
  }

  async function sendStaffMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selected = supportInbox.find((item) => item.conversation_id === selectedSupportConversationId);
    const content = staffDraft.trim();
    if (!staffSession || !selected || isStaffSending) return;
    if (selected.state !== "HUMAN_ACTIVE") {
      setStaffNotice({ kind: "denial", message: "Claim the conversation before replying." });
      return;
    }
    if (!content) {
      setStaffNotice({ kind: "error", message: "Enter a reply before sending." });
      return;
    }

    setStaffNotice(null);
    setIsStaffSending(true);
    try {
      const response = await appendSupportMessage(
        staffSession.session_id,
        selected.conversation_id,
        content,
      );
      setSupportInbox((current) => current.map((item) => item.conversation_id === selected.conversation_id
        ? { ...item, state: response.state, messages: [...item.messages, response.message] }
        : item));
      setStaffDraft("");
    } catch (error) {
      setStaffNotice(noticeFromError(error));
    } finally {
      setIsStaffSending(false);
    }
  }

  async function resolveSelectedConversation() {
    const selected = supportInbox.find((item) => item.conversation_id === selectedSupportConversationId);
    if (!staffSession || !selected || isResolving) return;

    setStaffNotice(null);
    setIsResolving(true);
    try {
      replaceSupportConversation(
        await resolveSupportConversation(staffSession.session_id, selected.conversation_id),
      );
    } catch (error) {
      setStaffNotice(noticeFromError(error));
    } finally {
      setIsResolving(false);
    }
  }

  async function loadRefunds(sessionId: string) {
    setIsRefundsLoading(true);
    try {
      const response = await getRefunds(sessionId);
      setRefunds(response.refunds);
    } catch (error) {
      setRefundNotice(noticeFromError(error));
    } finally {
      setIsRefundsLoading(false);
    }
  }

  async function startApproverSession() {
    setRefundNotice(null);
    setIsApproverStarting(true);
    try {
      const nextSession = await loginDemoRefundApprover();
      setApproverSession(nextSession);
      await loadRefunds(nextSession.session_id);
    } catch (error) {
      setApproverSession(null);
      setRefundNotice(noticeFromError(error));
    } finally {
      setIsApproverStarting(false);
    }
  }

  async function refreshRefunds() {
    if (!approverSession || isRefundsLoading) return;
    setRefundNotice(null);
    await loadRefunds(approverSession.session_id);
  }

  async function decideRefund(refundId: string, decision: "approve" | "reject") {
    if (!approverSession || activeRefundActionId) return;

    setRefundNotice(null);
    setActiveRefundActionId(refundId);
    try {
      const updated = decision === "approve"
        ? await approveRefund(approverSession.session_id, refundId)
        : await rejectRefund(approverSession.session_id, refundId);
      setRefunds((current) => current.map((refund) =>
        refund.refund_id === updated.refund_id ? updated : refund,
      ));
      setRefundFilter("all");
    } catch (error) {
      setRefundNotice(noticeFromError(error));
    } finally {
      setActiveRefundActionId(null);
    }
  }

  const selectedSupportConversation = supportInbox.find(
    (item) => item.conversation_id === selectedSupportConversationId,
  ) ?? null;
  const visibleRefunds = refundFilter === "pending"
    ? refunds.filter((refund) => refund.state === "PENDING_REVIEW")
    : refunds;

  return (
    <main className="page-shell">
      <section className="widget-frame" aria-labelledby="widget-title">
        <header className="brand-bar">
          <div className="brand-mark" aria-hidden="true">✳</div>
          <div>
            <p className="eyebrow">ResolveAI · customer operations</p>
            <h1 id="widget-title">ShopEase support</h1>
          </div>
          <span className="demo-pill">Local demo</span>
        </header>

        <div className="content-grid">
          <section className="intro-panel" aria-labelledby="intro-title">
            <p className="eyebrow accent">Customer widget preview</p>
            <h2 id="intro-title">A thoughtful place to start an order question.</h2>
            <p className="intro-copy">
              This is a synthetic customer support experience for the ResolveAI M1 milestone.
              Every request stays on your configured local API.
            </p>

            <div className="demo-note">
              <span className="note-icon" aria-hidden="true">i</span>
              <p><strong>Demo only.</strong> No live customer, commerce, or AI service is connected.</p>
            </div>

            <div className="session-card">
              <div className="card-heading">
                <div>
                  <p className="section-label">Identity</p>
                  <h3>Server-established session</h3>
                </div>
                <span className={session ? "status-dot active" : "status-dot"} aria-label={session ? "active" : "not started"} />
              </div>
              {session ? (
                <div className="session-details">
                  <span className="avatar">DC</span>
                  <div>
                    <strong>{session.actor.display_name}</strong>
                    <span>{session.actor.actor_id} · {session.actor.role}</span>
                  </div>
                </div>
              ) : (
                <p className="muted">No customer identity has been established yet.</p>
              )}
              <button className="primary-button full-width" type="button" onClick={startDemoSession} disabled={isStarting}>
                {isStarting ? "Starting demo session…" : session ? "Restart Demo Customer session" : "Start Demo Customer session"}
              </button>
            </div>
          </section>

          <section className="chat-card" aria-labelledby="chat-title">
            <div className="chat-header">
              <div className="chat-avatar" aria-hidden="true">✳</div>
              <div>
                <h2 id="chat-title">ShopEase Support</h2>
                <p>Powered by ResolveAI · synthetic demo</p>
              </div>
              <span className="online-label"><span /> local</span>
            </div>

            {!session ? (
              <div className="chat-placeholder">
                <div className="placeholder-icon" aria-hidden="true">→</div>
                <h3>Start your demo session</h3>
                <p>Establish the Demo Customer identity to open a secure widget conversation.</p>
              </div>
            ) : !conversation ? (
              <form className="conversation-start" onSubmit={beginConversation}>
                <div>
                  <p className="section-label">Conversation setup</p>
                  <h3>What should we look at?</h3>
                  <p className="muted">An order ID is optional. Leave it blank for a public-policy conversation.</p>
                </div>
                <label htmlFor="order-id">Order ID <span>(optional)</span></label>
                <input
                  id="order-id"
                  value={orderId}
                  onChange={(event) => setOrderId(event.target.value)}
                  placeholder="order_1001"
                  autoComplete="off"
                />
                <button className="primary-button" type="submit" disabled={isCreating}>
                  {isCreating ? "Opening conversation…" : "Open widget conversation"}
                </button>
              </form>
            ) : (
              <>
                <div className="conversation-meta">
                  <span>Conversation {conversation.conversation_id}</span>
                  <span className="state-badge">{conversation.state}</span>
                </div>
                <div className="transcript" aria-live="polite">
                  {conversation.messages.length === 0 ? (
                    <div className="empty-transcript">
                      <span className="empty-mark" aria-hidden="true">✦</span>
                      <p>No messages yet.</p>
                      <span>Ask about your order to begin.</span>
                    </div>
                  ) : (
                    conversation.messages.map((message) => (
                      <article className={`message ${message.author_type === "customer" ? "customer-message" : "other-message"}`} key={message.message_id}>
                        <div className="message-author">
                          <span>{message.author_type === "customer" ? "You" : message.author_type}</span>
                          <time dateTime={message.created_at}>{formatTimestamp(message.created_at)}</time>
                        </div>
                        <p>{message.content}</p>
                      </article>
                    ))
                  )}
                </div>

                {latestResolution && (
                  <div className="resolution-panel" role="status">
                    <div className="resolution-heading">
                      <div>
                        <span className="section-label">Investigation result</span>
                        <strong>{latestResolution.handoff_reason ? "Human review recommended" : "Grounded answer"}</strong>
                      </div>
                      <span className="state-badge">{latestResolution.retrieval_mode}</span>
                    </div>
                    {latestResolution.evidence.length > 0 ? (
                      <div className="citation-list">
                        <span className="resolution-label">Policy citations</span>
                        {latestResolution.evidence.map((evidence) => (
                          <div className="citation" key={`${evidence.document_id}-${evidence.document_version}-${evidence.section}`}>
                            <strong>{evidence.document_id} · {evidence.document_version}</strong>
                            <span>{evidence.section} · {evidence.release_id}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="resolution-copy">
                        {latestResolution.handoff_reason
                          ? "No sufficient published customer policy evidence was found. Request human support for help."
                          : "No policy evidence was needed for this response."}
                      </p>
                    )}
                  </div>
                )}

                <div className="m1-state" role="status">
                  <span className="state-icon" aria-hidden="true">⌁</span>
                  <div>
                    <strong>{conversation.state === "HANDOFF_QUEUED" ? "Human support requested" : "M3 local demo state"}</strong>
                    <p>{conversation.state === "HANDOFF_QUEUED"
                      ? "Your conversation is queued for the local demo support inbox."
                      : "No automated answer is available yet. You can request a human review."}</p>
                  </div>
                  {conversation.state === "AI_ACTIVE" && (
                    <button className="secondary-button compact-button" type="button" onClick={requestHumanSupport} disabled={isHandingOff}>
                      {isHandingOff ? "Requesting…" : "Request human support"}
                    </button>
                  )}
                </div>

                <form className="message-composer" onSubmit={sendMessage}>
                  <label className="sr-only" htmlFor="message">Your message</label>
                  <textarea
                    id="message"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder="Type your question…"
                    rows={2}
                    disabled={isSending}
                  />
                  <button className="send-button" type="submit" disabled={isSending || !draft.trim()} aria-label="Send message">
                    {isSending ? "…" : "↗"}
                  </button>
                </form>
              </>
            )}
          </section>
        </div>

        <section className="staff-panel" aria-labelledby="staff-title">
          <header className="staff-header">
            <div>
              <p className="eyebrow accent">Staff console preview</p>
              <h2 id="staff-title">Support inbox</h2>
              <p>Review queued synthetic conversations, take ownership, and close the loop.</p>
            </div>
            <span className="staff-demo-pill">Local demo only</span>
          </header>

          {!staffSession ? (
            <div className="staff-login-card">
              <div className="staff-login-icon" aria-hidden="true">S</div>
              <div>
                <p className="section-label">Support identity</p>
                <h3>Open the demo staff inbox</h3>
                <p className="muted">The local API resolves this session as support_001. No live support, AI, or payment system is connected.</p>
              </div>
              <button className="primary-button" type="button" onClick={startStaffSession} disabled={isStaffStarting}>
                {isStaffStarting ? "Opening staff inboxâ€¦" : "Start Demo Support session"}
              </button>
            </div>
          ) : (
            <>
              <div className="staff-toolbar">
                <div className="staff-identity">
                  <span className="avatar">SA</span>
                  <div>
                    <strong>{staffSession.actor.display_name}</strong>
                    <span>{staffSession.actor.actor_id} Â· {staffSession.actor.role}</span>
                  </div>
                </div>
                <button className="secondary-button" type="button" onClick={refreshStaffInbox} disabled={isInboxLoading}>
                  {isInboxLoading ? "Refreshingâ€¦" : "Refresh inbox"}
                </button>
              </div>

              <div className="staff-workspace">
                <aside className="inbox-list-panel" aria-label="Support conversation queue">
                  <div className="inbox-list-heading">
                    <div>
                      <p className="section-label">Queue</p>
                      <h3>Conversations</h3>
                    </div>
                    <span className="queue-count">{supportInbox.length}</span>
                  </div>
                  {isInboxLoading && supportInbox.length === 0 ? (
                    <div className="staff-empty-state">
                      <strong>Loading inboxâ€¦</strong>
                      <span>Checking the local support queue.</span>
                    </div>
                  ) : supportInbox.length === 0 ? (
                    <div className="staff-empty-state">
                      <strong>No queued conversations</strong>
                      <span>New handoffs will appear here.</span>
                    </div>
                  ) : (
                    <div className="inbox-items">
                      {supportInbox.map((item) => {
                        const latestMessage = item.messages[item.messages.length - 1];
                        return (
                          <button
                            className={`inbox-item ${item.conversation_id === selectedSupportConversationId ? "selected" : ""}`}
                            key={item.conversation_id}
                            type="button"
                            onClick={() => setSelectedSupportConversationId(item.conversation_id)}
                          >
                            <span className="inbox-item-top">
                              <strong>{item.conversation_id}</strong>
                              <span className="state-badge">{item.state}</span>
                            </span>
                            <span className="inbox-item-meta">{item.customer_id ?? "Unknown customer"} Â· {item.order_id ?? "No order"}</span>
                            <span className="inbox-item-preview">{latestMessage?.content ?? "No messages yet."}</span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </aside>

                <section className="staff-conversation" aria-labelledby="staff-conversation-title">
                  {!selectedSupportConversation ? (
                    <div className="staff-empty-state large">
                      <div className="staff-login-icon" aria-hidden="true">â†’</div>
                      <strong>Select a conversation</strong>
                      <span>Choose a queued item to review its transcript.</span>
                    </div>
                  ) : (
                    <>
                      <div className="staff-conversation-header">
                        <div>
                          <p className="section-label">Conversation</p>
                          <h3 id="staff-conversation-title">{selectedSupportConversation.conversation_id}</h3>
                          <span className="staff-conversation-meta">{selectedSupportConversation.customer_id ?? "Unknown customer"} Â· {selectedSupportConversation.order_id ?? "No order attached"}</span>
                        </div>
                        <div className="staff-actions">
                          <span className="state-badge">{selectedSupportConversation.state}</span>
                          {selectedSupportConversation.state === "HANDOFF_QUEUED" && (
                            <button className="primary-button compact-button" type="button" onClick={claimSelectedConversation} disabled={isClaiming}>
                              {isClaiming ? "Claimingâ€¦" : "Claim conversation"}
                            </button>
                          )}
                          {selectedSupportConversation.state === "HUMAN_ACTIVE" && (
                            <button className="secondary-button compact-button" type="button" onClick={resolveSelectedConversation} disabled={isResolving}>
                              {isResolving ? "Resolvingâ€¦" : "Resolve"}
                            </button>
                          )}
                        </div>
                      </div>

                      <div className="staff-transcript" aria-live="polite">
                        {selectedSupportConversation.messages.length === 0 ? (
                          <div className="staff-empty-state"><strong>No messages yet</strong><span>The conversation has no transcript.</span></div>
                        ) : (
                          selectedSupportConversation.messages.map((message) => (
                            <article className={`message ${message.author_type === "staff" ? "staff-message" : message.author_type === "customer" ? "customer-message" : "other-message"}`} key={message.message_id}>
                              <div className="message-author">
                                <span>{message.author_type === "staff" ? "You (support)" : message.author_type}</span>
                                <time dateTime={message.created_at}>{formatTimestamp(message.created_at)}</time>
                              </div>
                              <p>{message.content}</p>
                            </article>
                          ))
                        )}
                      </div>

                      {selectedSupportConversation.state === "HUMAN_ACTIVE" ? (
                        <form className="message-composer" onSubmit={sendStaffMessage}>
                          <label className="sr-only" htmlFor="staff-message">Staff reply</label>
                          <textarea
                            id="staff-message"
                            value={staffDraft}
                            onChange={(event) => setStaffDraft(event.target.value)}
                            placeholder="Write a support replyâ€¦"
                            rows={2}
                            disabled={isStaffSending}
                          />
                          <button className="send-button" type="submit" disabled={isStaffSending || !staffDraft.trim()} aria-label="Send staff reply">
                            {isStaffSending ? "â€¦" : "â†—"}
                          </button>
                        </form>
                      ) : (
                        <div className="staff-state" role="status">
                          <strong>{selectedSupportConversation.state === "RESOLVED" ? "Conversation resolved" : "Claim required"}</strong>
                          <span>{selectedSupportConversation.state === "RESOLVED" ? "This local demo conversation is closed." : "Claim the conversation to enable a staff reply. AI replies remain off during human handling."}</span>
                        </div>
                      )}
                    </>
                  )}
                </section>
              </div>
            </>
          )}

          {staffNotice && (
            <div className={`notice ${staffNotice.kind} staff-notice`} role="alert">
              <strong>{staffNotice.kind === "denial" ? "Request denied" : "Local API error"}</strong>
              <span>{staffNotice.message}</span>
            </div>
          )}
        </section>

        <section className="staff-panel refund-panel" aria-labelledby="refund-title">
          <header className="staff-header">
            <div>
              <p className="eyebrow accent">Approval console preview</p>
              <h2 id="refund-title">Refund review</h2>
              <p>Review synthetic requests with a separate approver identity before any external follow-up.</p>
            </div>
            <span className="staff-demo-pill">Local demo only</span>
          </header>

          {!approverSession ? (
            <div className="staff-login-card refund-login-card">
              <div className="staff-login-icon" aria-hidden="true">R</div>
              <div>
                <p className="section-label">Refund approver identity</p>
                <h3>Open the demo review queue</h3>
                <p className="muted">The local API resolves this fixed demo session as refund_approver_001. The client does not choose a role.</p>
              </div>
              <button className="primary-button" type="button" onClick={startApproverSession} disabled={isApproverStarting}>
                {isApproverStarting ? "Opening review queue…" : "Start Demo Approver session"}
              </button>
            </div>
          ) : (
            <>
              <div className="staff-toolbar refund-toolbar">
                <div className="staff-identity">
                  <span className="avatar">RA</span>
                  <div>
                    <strong>{approverSession.actor.display_name}</strong>
                    <span>{approverSession.actor.actor_id} · {approverSession.actor.role}</span>
                  </div>
                </div>
                <div className="refund-toolbar-actions">
                  <div className="refund-filter" role="group" aria-label="Refund list filter">
                    <button
                      className={`refund-filter-button ${refundFilter === "pending" ? "selected" : ""}`}
                      type="button"
                      aria-pressed={refundFilter === "pending"}
                      onClick={() => setRefundFilter("pending")}
                    >
                      Pending review
                    </button>
                    <button
                      className={`refund-filter-button ${refundFilter === "all" ? "selected" : ""}`}
                      type="button"
                      aria-pressed={refundFilter === "all"}
                      onClick={() => setRefundFilter("all")}
                    >
                      All decisions
                    </button>
                  </div>
                  <button className="secondary-button" type="button" onClick={refreshRefunds} disabled={isRefundsLoading}>
                    {isRefundsLoading ? "Refreshing…" : "Refresh reviews"}
                  </button>
                </div>
              </div>

              <div className="refund-policy-note" role="note">
                <strong>Review only.</strong>
                <span>Approval requires an external action and does not move money.</span>
              </div>

              {isRefundsLoading && refunds.length === 0 ? (
                <div className="staff-empty-state refund-empty-state">
                  <strong>Loading refund reviews…</strong>
                  <span>Checking the local approval queue.</span>
                </div>
              ) : visibleRefunds.length === 0 ? (
                <div className="staff-empty-state refund-empty-state">
                  <strong>{refundFilter === "pending" ? "No pending reviews" : "No refund decisions yet"}</strong>
                  <span>{refundFilter === "pending" ? "New synthetic requests will appear here." : "The local API has not returned any review records."}</span>
                </div>
              ) : (
                <div className="refund-list" aria-live="polite">
                  {visibleRefunds.map((refund) => (
                    <article className="refund-card" key={refund.refund_id}>
                      <div className="refund-card-header">
                        <div>
                          <p className="section-label">Refund request</p>
                          <h3>{refund.refund_id}</h3>
                          <p className="refund-card-meta">Order {refund.order_id} · Conversation {refund.conversation_id}</p>
                        </div>
                        <span className="state-badge">{refund.state}</span>
                      </div>
                      <div className="refund-card-details">
                        <div>
                          <span className="refund-detail-label">Amount</span>
                          <strong>{formatCents(refund.amount_cents)}</strong>
                        </div>
                        <div>
                          <span className="refund-detail-label">Reason</span>
                          <span>{refund.reason}</span>
                        </div>
                        <div>
                          <span className="refund-detail-label">Requested by</span>
                          <span>{refund.requested_by}</span>
                        </div>
                        {refund.decided_by && (
                          <div>
                            <span className="refund-detail-label">Decided by</span>
                            <span>{refund.decided_by}</span>
                          </div>
                        )}
                      </div>
                      {refund.decision_note && <p className="refund-decision-note">{refund.decision_note}</p>}
                      {refund.state === "PENDING_REVIEW" ? (
                        <div className="refund-actions">
                          <button
                            className="secondary-button refund-reject-button"
                            type="button"
                            onClick={() => decideRefund(refund.refund_id, "reject")}
                            disabled={activeRefundActionId !== null}
                          >
                            {activeRefundActionId === refund.refund_id ? "Saving…" : "Reject"}
                          </button>
                          <button
                            className="primary-button compact-button"
                            type="button"
                            onClick={() => decideRefund(refund.refund_id, "approve")}
                            disabled={activeRefundActionId !== null}
                          >
                            {activeRefundActionId === refund.refund_id ? "Saving…" : "Approve for external action"}
                          </button>
                        </div>
                      ) : (
                        <p className="refund-closed-state">This review is closed; no payment operation was performed.</p>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </>
          )}

          {refundNotice && (
            <div className="notice refund-notice" role="alert">
              <strong>{refundNotice.kind === "denial" ? "Request denied" : "Local API error"}</strong>
              <span>{refundNotice.message}</span>
            </div>
          )}
        </section>

        {notice && (
          <div className={`notice ${notice.kind}`} role="alert">
            <strong>{notice.kind === "denial" ? "Request denied" : "Local API error"}</strong>
            <span>{notice.message}</span>
          </div>
        )}

        <footer className="footer-note">
          <span>ResolveAI · M1 authenticated widget inquiry</span>
          <span>API base: {import.meta.env.VITE_API_BASE_URL || "same origin"}</span>
        </footer>
      </section>
    </main>
  );
}
