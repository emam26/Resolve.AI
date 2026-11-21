import { FormEvent, useState } from "react";
import {
  ApiError,
  appendCustomerMessage,
  createWidgetConversation,
  ConversationResponse,
  DemoLoginResponse,
  loginDemoCustomer,
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

export default function App() {
  const [session, setSession] = useState<DemoLoginResponse | null>(null);
  const [conversation, setConversation] = useState<ConversationResponse | null>(null);
  const [orderId, setOrderId] = useState("order_1001");
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isSending, setIsSending] = useState(false);

  async function startDemoSession() {
    setNotice(null);
    setConversation(null);
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
          ? { ...current, state: response.state, messages: [...current.messages, response.message] }
          : current,
      );
      setDraft("");
    } catch (error) {
      setNotice(noticeFromError(error));
    } finally {
      setIsSending(false);
    }
  }

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

                <div className="m1-state" role="status">
                  <span className="state-icon" aria-hidden="true">⌁</span>
                  <div>
                    <strong>M1 demo state</strong>
                    <p>No AI answer is available yet. Your message is recorded by the local API.</p>
                  </div>
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
