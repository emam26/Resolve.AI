import { FormEvent, useState, useEffect } from "react";
import {
  ApiError,
  AppendMessageResponse,
  appendSupportMessage,
  appendCustomerMessage,
  approveRefund,
  claimSupportConversation,
  createRefund,
  createWidgetConversation,
  ConversationResponse,
  DemoLoginResponse,
  getRefunds,
  getOrderSummary,
  getCaseOrder, loginProduction, productionMode, forgetProductionCsrf, setProductionSessionExpiredHandler,
  getSupportInbox,
  handoffCustomerConversation,
  loginDemoRefundApprover,
  loginDemoMerchantAdmin,
  loginDemoSupport,
  loginDemoCustomer,
  logoutSession,
  rejectRefund,
  resolveSupportConversation,
  RefundSummary,
  OrderSummary,
  SupportConversationSummary,
} from "./api";
import WorkspaceSurface, { WorkspaceSurfaceName } from "./WorkspaceSurface";
import "./styles.css";
import "./reference.css";
import "./redesign.css";
import { DesignShell, Icon, PageHeading, isSurface, type Surface } from "./DesignShell";
import ExtraSurface from "./ExtraSurface";

type NoticeKind = "error" | "denial";

interface Notice {
  kind: NoticeKind;
  message: string;
}

type AppSurface = Surface;

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

const rolePages: Record<string, Surface[]> = {
  support_agent: ["overview","support","tickets","orders","knowledge"],
  refund_approver: ["overview","refunds","knowledge"],
  merchant_admin: ["overview","knowledge","playground","evaluations","onboarding","integrations","team","audit","settings"],
  customer: [],
};
export default function App() {
  const [identity,setIdentity] = useState<DemoLoginResponse|null>(null);
  const [username,setUsername] = useState(""); const [password,setPassword] = useState("");
  const [busy,setBusy] = useState(false); const [error,setError] = useState("");
  if (!productionMode) return <Application/>;
  if(identity) return <Application key={identity.actor.actor_id} productionIdentity={identity} onSignedOut={(message)=>{forgetProductionCsrf();setIdentity(null);setError(message??"");}}/>;
  async function signIn(e:FormEvent<HTMLFormElement>) {
    e.preventDefault(); if(busy)return; setBusy(true);setError("");
    try {setIdentity(await loginProduction(username,password));}
    catch(e){forgetProductionCsrf();setError(noticeFromError(e).message);}
    finally{setPassword("");setBusy(false);}
  }
  return <main className="secure-login"><section className="card pad secure-login-card"><img src="/branding/resolveai-logo-dark.svg" className="secure-login-logo" alt="ResolveAI"/><div className="eyebrow">MERCHANT OPERATIONS</div><h1 className="heading">Welcome back.</h1><p className="subtitle">Sign in with your provisioned ResolveAI account.</p><form className="stack" onSubmit={signIn}><label className="field">Username<input className="input" autoComplete="username" required value={username} onChange={e=>setUsername(e.target.value)}/></label><label className="field">Password<input className="input" type="password" autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/></label><button className="btn primary" disabled={busy}>{busy?"Signing in…":"Sign in"}</button>{error&&<div className="flag warning" role="alert">{error}</div>}</form></section></main>;
}
function Application({productionIdentity,onSignedOut}:{productionIdentity?:DemoLoginResponse;onSignedOut?:(message?:string)=>void}) {
  const querySurface = new URLSearchParams(window.location.search).get("surface");
  const widgetOnly = productionIdentity ? productionIdentity.actor.role === "customer" : querySurface === "widget";
  const allowed = productionIdentity ? rolePages[productionIdentity.actor.role] ?? [] : undefined;
  const [inboxSearch, setInboxSearch] = useState("");
  const [inboxFilter, setInboxFilter] = useState("All");
  const [selectedRefundId, setSelectedRefundId] = useState<string | null>(null);
  const [caseOrder, setCaseOrder] = useState<{caseId:string;order:OrderSummary} | null>(null);
  const [caseOrderLoading, setCaseOrderLoading] = useState(false);
  const [session, setSession] = useState<DemoLoginResponse | null>(productionIdentity?.actor.role === "customer" ? productionIdentity! : null);
  const [activeSurface, setActiveSurface] = useState<AppSurface>(
    isSurface(querySurface) && (!allowed || allowed.includes(querySurface)) ? querySurface : "overview",
  );
  const [conversation, setConversation] = useState<ConversationResponse | null>(null);
  const [latestResolution, setLatestResolution] = useState<AppendMessageResponse | null>(null);
  const [orderId, setOrderId] = useState(productionIdentity ? "" : "order_1001");
  const [orderSummary, setOrderSummary] = useState<OrderSummary | null>(null);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isLookingUpOrder, setIsLookingUpOrder] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isHandingOff, setIsHandingOff] = useState(false);
  const [staffSession, setStaffSession] = useState<DemoLoginResponse | null>(productionIdentity?.actor.role === "support_agent" ? productionIdentity! : null);
  const [supportInbox, setSupportInbox] = useState<SupportConversationSummary[]>([]);
  const [selectedSupportConversationId, setSelectedSupportConversationId] = useState<string | null>(null);
  const [staffDraft, setStaffDraft] = useState("");
  const [staffNotice, setStaffNotice] = useState<Notice | null>(null);
  const [supportRefundAmount, setSupportRefundAmount] = useState("25.00");
  const [supportRefundReason, setSupportRefundReason] = useState("Delivery delay review");
  const [supportRefundNotice, setSupportRefundNotice] = useState<string | null>(null);
  const [supportRefundRequestKey, setSupportRefundRequestKey] = useState<string | null>(null);
  const [isCreatingRefund, setIsCreatingRefund] = useState(false);
  const [isStaffStarting, setIsStaffStarting] = useState(false);
  const [isInboxLoading, setIsInboxLoading] = useState(false);
  const [isClaiming, setIsClaiming] = useState(false);
  const [isStaffSending, setIsStaffSending] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [approverSession, setApproverSession] = useState<DemoLoginResponse | null>(productionIdentity?.actor.role === "refund_approver" ? productionIdentity! : null);
  const [refunds, setRefunds] = useState<RefundSummary[]>([]);
  const [refundFilter, setRefundFilter] = useState<"pending" | "all">("pending");
  const [refundNotice, setRefundNotice] = useState<Notice | null>(null);
  const [isApproverStarting, setIsApproverStarting] = useState(false);
  const [isRefundsLoading, setIsRefundsLoading] = useState(false);
  const [activeRefundActionId, setActiveRefundActionId] = useState<string | null>(null);
  const [workspaceSession, setWorkspaceSession] = useState<DemoLoginResponse | null>(productionIdentity && productionIdentity.actor.role !== "customer" ? productionIdentity! : null);
  const [isWorkspaceStarting, setIsWorkspaceStarting] = useState(false);
  const [workspaceLoginNotice, setWorkspaceLoginNotice] = useState<Notice | null>(null);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  useEffect(() => {
    if (!productionIdentity) {
      setProductionSessionExpiredHandler(null);
      return;
    }
    setProductionSessionExpiredHandler(() => {
      onSignedOut?.("Your provisioned session expired. Sign in again.");
    });
    return () => setProductionSessionExpiredHandler(null);
  }, [onSignedOut, productionIdentity]);

  useEffect(()=>{if(productionIdentity?.actor.role==='support_agent')void loadSupportInbox("");if(productionIdentity?.actor.role==='refund_approver')void loadRefunds("");},[]);
  async function startDemoSession() {
    if(productionIdentity) return;
    setNotice(null);
    setConversation(null);
    setLatestResolution(null);
    setOrderSummary(null);
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

  async function endSession(
    sessionId: string,
    clearLocalSession: () => void,
    showError: (notice: Notice) => void,
  ) {
    if (isLoggingOut) return;
    setIsLoggingOut(true);
    let logoutError: string | undefined;
    try {
      await logoutSession(sessionId);
    } catch (error) {
      logoutError = "Server logout was not confirmed. Sign in again only on a trusted device.";
      showError(noticeFromError(error));
    } finally {
      // Never retain a bearer credential in the browser after a logout attempt,
      // including when the server is temporarily unavailable.
      clearLocalSession();
      setIsLoggingOut(false);
      if(productionIdentity) onSignedOut?.(logoutError);
    }
  }

  async function endCustomerSession() {
    if (!session) return;
    setNotice(null);
    await endSession(
      session.session_id,
      () => {
        setSession(null);
        setDraft("");
        setConversation(null);
        setLatestResolution(null);
        setOrderSummary(null);
      },
      setNotice,
    );
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

  async function lookupOrder() {
    if (!session || isLookingUpOrder || !orderId.trim()) return;

    setNotice(null);
    setOrderSummary(null);
    setIsLookingUpOrder(true);
    try {
      setOrderSummary(await getOrderSummary(session.session_id, orderId.trim()));
    } catch (error) {
      setNotice(noticeFromError(error));
    } finally {
      setIsLookingUpOrder(false);
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
    if(productionIdentity) return;
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

  async function endStaffSession() {
    if (!staffSession) return;
    setStaffNotice(null);
    await endSession(
      staffSession.session_id,
      () => {
        setStaffSession(null);
        setSupportInbox([]);
        setCaseOrder(null);
        setSelectedSupportConversationId(null);
        setStaffDraft("");
        setSupportRefundNotice(null);
        setSupportRefundRequestKey(null);
      },
      setStaffNotice,
    );
  }

  async function startWorkspaceSession() {
    if(productionIdentity) return;
    setWorkspaceLoginNotice(null);
    setIsWorkspaceStarting(true);
    try {
      setWorkspaceSession(await loginDemoMerchantAdmin());
    } catch (error) {
      setWorkspaceSession(null);
      setWorkspaceLoginNotice(noticeFromError(error));
    } finally {
      setIsWorkspaceStarting(false);
    }
  }

  async function endWorkspaceSession() {
    if (!workspaceSession) return;
    setWorkspaceLoginNotice(null);
    await endSession(
      workspaceSession.session_id,
      () => setWorkspaceSession(null),
      setWorkspaceLoginNotice,
    );
  }

  function navigateSurface(surface: AppSurface) {
    if(allowed && !allowed.includes(surface)) return;
    setActiveSurface(surface);
    const nextQuery = `?surface=${surface}`;
    window.history.replaceState({}, "", `${window.location.pathname}${nextQuery}`);
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

  async function submitRefundRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selected = supportInbox.find((item) => item.conversation_id === selectedSupportConversationId);
    if (!staffSession || !selected || selected.state !== "HUMAN_ACTIVE" || isCreatingRefund) return;

    const amountDollars = Number.parseFloat(supportRefundAmount);
    const reason = supportRefundReason.trim();
    if (!Number.isFinite(amountDollars) || amountDollars <= 0 || amountDollars > 50 || !reason) {
      setStaffNotice({ kind: "error", message: "Enter a refund amount from $0.01 to $50.00 and a reason." });
      return;
    }

    setStaffNotice(null);
    setSupportRefundNotice(null);
    setIsCreatingRefund(true);
    const idempotencyKey = supportRefundRequestKey ?? `support-ui-${selected.conversation_id}-${Date.now()}`;
    if (supportRefundRequestKey === null) {
      setSupportRefundRequestKey(idempotencyKey);
    }
    try {
      const created = await createRefund(
        staffSession.session_id,
        selected.conversation_id,
        {
          amount_cents: Math.round(amountDollars * 100),
          reason,
          idempotency_key: idempotencyKey,
        },
      );
      setSupportRefundNotice(`${created.refund_id} is pending separate approver review.`);
      if (approverSession) await loadRefunds(approverSession.session_id);
      setSupportRefundAmount("25.00");
      setSupportRefundReason("Delivery delay review");
      setSupportRefundRequestKey(null);
    } catch (error) {
      setStaffNotice(noticeFromError(error));
    } finally {
      setIsCreatingRefund(false);
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
    if(productionIdentity) return;
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

  async function endApproverSession() {
    if (!approverSession) return;
    setRefundNotice(null);
    await endSession(
      approverSession.session_id,
      () => {
        setApproverSession(null);
        setRefunds([]);
        setSelectedRefundId(null);
        setActiveRefundActionId(null);
      },
      setRefundNotice,
    );
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
      setSelectedRefundId(updated.refund_id);
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

  const selectedRefund = visibleRefunds.find(r=>r.refund_id===selectedRefundId)??visibleRefunds[0];
  const filteredInbox = supportInbox.filter(c=>(inboxFilter==='All'||({Handoff:'HANDOFF_QUEUED',Human:'HUMAN_ACTIVE',AI:'AI_ACTIVE'} as Record<string,string>)[inboxFilter]===c.state)&&`${c.customer_id} ${c.conversation_id} ${c.order_id} ${c.messages.at(-1)?.content??''}`.toLowerCase().includes(inboxSearch.toLowerCase()));
  async function lookupCaseOrder(){if(!staffSession||!selectedSupportConversation?.order_id)return;setCaseOrderLoading(true);setCaseOrder(null);setStaffNotice(null);try{setCaseOrder({caseId:selectedSupportConversation.conversation_id,order:await getCaseOrder(staffSession.session_id,selectedSupportConversation.conversation_id)});}catch(error){setStaffNotice(noticeFromError(error));}finally{setCaseOrderLoading(false);}}
  const customerView = <section className="customer-preview" aria-labelledby="widget-title"><span className="sr-only" id="widget-title">Customer support</span><div className="storefront customer-surface">
<section className="store-hero"><header><strong className="storebrand">ShopEase.</strong><span className="helper">Storefront preview</span></header><h2>Thoughtful essentials, everyday.</h2><p>Simple things. Better experiences. Everything you need, delivered with care.</p><div className="object-shape" aria-hidden="true"/></section>
          <section className="chat-card widget-frame" aria-labelledby="chat-title">
            <div className="chat-header widget-head">
              <img
                className="chat-avatar"
                src="/branding/app-icon-192.png"
                alt=""
                aria-hidden="true"
              />
              <div>
                <h2 id="chat-title">ShopEase support</h2>
                <p>Powered by ResolveAI · synthetic demo</p>
              </div>
            </div>

            {session && <div className="widget-session"><span>{session.actor.display_name}</span><button className="btn sm" type="button" onClick={()=>void endCustomerSession()} disabled={isLoggingOut}>End session</button></div>}
            {!session ? (
              <div className="widget-body"><div className="wbubble">Hi! I’m the ShopEase assistant. I can explain store policies, help with an order, or connect you to the support team.</div><div className="widget-quick">{['Return policy','Track order','Talk to a person'].map(label=><button key={label} onClick={()=>{setOrderId(label==='Track order'?'order_1001':'');setDraft(label==='Return policy'?'What is your return policy?':label==='Track order'?'What is the status of my order?':'I would like to speak to a person.');void startDemoSession()}} disabled={isStarting}>{label}</button>)}</div><div className="widget-login"><p className="helper"><b>Demo only.</b> Synthetic local identity required to open a conversation.</p><button className="primary-button" onClick={startDemoSession} disabled={isStarting}>{isStarting?'Starting demo session…':'Start Demo Customer session'}</button></div></div>
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
                  onChange={(event) => {
                    setOrderId(event.target.value);
                    setOrderSummary(null);
                  }}
                  placeholder="order_1001"
                  autoComplete="off"
                />
                <div className="conversation-actions">
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => void lookupOrder()}
                    disabled={isLookingUpOrder || !orderId.trim()}
                  >
                    {isLookingUpOrder ? "Checking order" : "Check order status"}
                  </button>
                  <button className="primary-button" type="submit" disabled={isCreating}>
                  {isCreating ? "Opening conversation…" : "Open widget conversation"}
                  </button>
                </div>
                {orderSummary && (
                  <section className="order-summary" aria-labelledby="order-lookup-title">
                    <div className="order-summary-heading">
                      <div>
                        <span className="section-label">Authorized order lookup</span>
                        <h4 id="order-lookup-title">{orderSummary.order_id}</h4>
                      </div>
                      <span className="state-badge">{orderSummary.status}</span>
                    </div>
                    <dl className="order-facts">
                      <div><dt>Payment</dt><dd>{orderSummary.payment_status}</dd></div>
                      <div><dt>Shipment</dt><dd>{orderSummary.shipment_status}</dd></div>
                      <div><dt>Estimated delivery</dt><dd>{orderSummary.estimated_delivery_date ?? "Not provided"}</dd></div>
                    </dl>
                  </section>
                )}
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
                      <span className="state-badge">
                        {latestResolution.retrieval_mode} · {latestResolution.generation_mode}
                      </span>
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
                    <strong>{conversation.state === "HANDOFF_QUEUED"
                      ? "Human support requested"
                      : conversation.state === "HUMAN_ACTIVE"
                        ? "Human support active"
                        : conversation.state === "RESOLVED"
                          ? "Conversation resolved"
                          : "AI support active"}</strong>
                    <p>{conversation.state === "HANDOFF_QUEUED"
                      ? "Your conversation is queued for the local demo support inbox."
                      : conversation.state === "HUMAN_ACTIVE"
                        ? "A support agent is handling this conversation."
                        : conversation.state === "RESOLVED"
                          ? "This conversation is closed in the local demo."
                          : "Ask an order or policy question. You can request a human review at any time."}</p>
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
                    disabled={isSending || conversation.state !== "AI_ACTIVE"}
                  />
                  <button className="send-button" type="submit" disabled={isSending || conversation.state !== "AI_ACTIVE" || !draft.trim()} aria-label="Send message">
                    {isSending ? "…" : "↗"}
                  </button>
                </form>
              </>
            )}
            {notice && <div className={`notice ${notice.kind}`} role="alert"><strong>{notice.kind === 'denial' ? 'Request denied' : 'Local API error'}</strong><span>{notice.message}</span></div>}
          </section>
        </div></section>;
  if(widgetOnly)return <main className="standalone-widget">{customerView}</main>;
  return <DesignShell allowed={allowed} production={!!productionIdentity} surface={activeSurface} navigate={navigateSurface} actor={activeSurface==='support'?staffSession?.actor.display_name:activeSurface==='refunds'?approverSession?.actor.display_name:activeSurface==='widget-preview'?session?.actor.display_name:workspaceSession?.actor.display_name} handoffs={staffSession?supportInbox.filter(c=>c.state==='HANDOFF_QUEUED').length:undefined} pending={approverSession?refunds.filter(r=>r.state==='PENDING_REVIEW').length:undefined}>
    {activeSurface==='widget-preview'&&<><PageHeading title="Customer widget preview" subtitle="An embeddable support experience for the merchant storefront." actions={<a className="btn" href="?surface=widget" target="_blank" rel="noopener">Open standalone widget</a>}/><div className="flag soft"><Icon name="info"/> Local synthetic support. No live Shopify or payment request is made.</div>{customerView}</>}
    {activeSurface==='support'&&<section className="staff-panel" aria-labelledby="staff-title">
          <header className="staff-header">
            <div>
              <p className="eyebrow accent">RESOLVEAI / MERCHANT OPERATIONS</p>
              <h1 id="staff-title" className="heading">Conversations</h1>
              <p>A complete workspace for evidence review, AI handoff and human customer care.</p>
            </div>
            <span className="staff-demo-pill">{productionIdentity?"Provisioned session":"Local demo only"}</span>
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
                {isStaffStarting ? "Opening staff inbox..." : "Start Demo Support session"}
              </button>
            </div>
          ) : (
            <>
              <div className="staff-toolbar">
                <div className="staff-identity">
                  <span className="avatar">SA</span>
                  <div>
                    <strong>{staffSession.actor.display_name}</strong>
                    <span>{staffSession.actor.actor_id} · {staffSession.actor.role}</span>
                  </div>
                </div>
                <button className="secondary-button" type="button" onClick={refreshStaffInbox} disabled={isInboxLoading}>
                  {isInboxLoading ? "Refreshing..." : "Refresh inbox"}
                </button>
                <button className="secondary-button" type="button" onClick={() => void endStaffSession()} disabled={isLoggingOut}>
                  {isLoggingOut ? "Ending..." : "End session"}
                </button>
              </div>

              <div className="staff-workspace card inbox">
                <aside className="inbox-list-panel col-left" aria-label="Support conversation queue">
                  <div className="inbox-list-heading">
                    <div>
                      <h3>Team inbox</h3>
                    </div>
                    <span className="queue-count">{supportInbox.length}</span>
                  </div>
                  <div className="inbox-controls"><div className="search"><Icon name="search"/><input className="input" aria-label="Search conversations" placeholder="Search conversations" value={inboxSearch} onChange={e=>setInboxSearch(e.target.value)}/></div><div className="filters">{['All','Handoff','Human','AI'].map(f=><button key={f} className={`filter ${inboxFilter===f?'on':''}`} onClick={()=>setInboxFilter(f)}>{f}</button>)}</div></div>
                  {isInboxLoading && supportInbox.length === 0 ? (
                    <div className="staff-empty-state">
                      <strong>Loading inbox...</strong>
                      <span>Checking the local support queue.</span>
                    </div>
                  ) : supportInbox.length === 0 ? (
                    <div className="staff-empty-state">
                      <strong>No queued conversations</strong>
                      <span>New handoffs will appear here.</span>
                    </div>
                  ) : (
                    <div className="inbox-items">
                      {filteredInbox.map((item) => {
                        const latestMessage = item.messages[item.messages.length - 1];
                        return (
                          <button
                            className={`inbox-item ${item.conversation_id === selectedSupportConversationId ? "selected" : ""}`}
                            key={item.conversation_id}
                            type="button"
                            onClick={() => {
                              setSelectedSupportConversationId(item.conversation_id);
                              setCaseOrder(null);
                              setStaffDraft("");
                              setSupportRefundRequestKey(null);
                              setSupportRefundNotice(null);
                            }}
                          >
                            <span className="initials">{(item.customer_id??"CU").slice(0,2).toUpperCase()}</span><span className="case-content"><span className="inbox-item-top">
                              <strong>{item.customer_id??"Unknown customer"}</strong>
                              <small>{item.conversation_id}</small>
                            </span>
                            <span className="inbox-item-meta">{item.customer_id ?? "Unknown customer"} · {item.order_id ?? "No order"}</span>
                            <span className="inbox-item-preview">{latestMessage?.content ?? "No messages yet."}</span><span className={`state-badge ${item.state}`}>{item.state}</span></span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </aside>

                <section className="staff-conversation col-mid message-panel" aria-labelledby="staff-conversation-title">
                  {!selectedSupportConversation ? (
                    <div className="staff-empty-state large">
                      <div className="staff-login-icon" aria-hidden="true">-&gt;</div>
                      <strong>Select a conversation</strong>
                      <span>Choose a queued item to review its transcript.</span>
                    </div>
                  ) : (
                    <>
                      <div className="staff-conversation-header">
                        <div>
                          <h3 id="staff-conversation-title">{selectedSupportConversation.customer_id ?? "Customer"}</h3>
                          <span className="staff-conversation-meta">{selectedSupportConversation.customer_id ?? "Unknown customer"} · {selectedSupportConversation.order_id ?? "No order attached"}</span>
                        </div>
                        <div className="staff-actions">
                          <span className={`state-badge ${selectedSupportConversation.state}`}>{selectedSupportConversation.state}</span>
                          {selectedSupportConversation.state === "HUMAN_ACTIVE" && (
                            <button className="secondary-button compact-button" type="button" onClick={resolveSelectedConversation} disabled={isResolving}>
                              {isResolving ? "Resolving..." : "Resolve"}
                            </button>
                          )}
                        </div>
                      </div>

                      {selectedSupportConversation.state === "HANDOFF_QUEUED" && <div className="ownership amber"><div><strong>Human handoff queued</strong><br/>An authorized agent must claim this conversation.</div>                          {selectedSupportConversation.state === "HANDOFF_QUEUED" && (
                            <button className="primary-button compact-button" type="button" onClick={claimSelectedConversation} disabled={isClaiming}>
                              {isClaiming ? "Claiming..." : "Claim conversation"}
                            </button>
                          )}
</div>}
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
                        <>
                        <form className="message-composer" onSubmit={sendStaffMessage}>
                          <label className="sr-only" htmlFor="staff-message">Staff reply</label>
                          <textarea
                            id="staff-message"
                            value={staffDraft}
                            onChange={(event) => setStaffDraft(event.target.value)}
                            placeholder="Write a support reply..."
                            rows={2}
                            disabled={isStaffSending}
                          />
                          <button className="send-button" type="submit" disabled={isStaffSending || !staffDraft.trim()} aria-label="Send staff reply">
                            {isStaffSending ? "..." : "Send"}
                          </button>
                        </form>
                        {selectedSupportConversation.order_id && (
                          <form className="refund-request-form" onSubmit={submitRefundRequest}>
                            <div className="refund-request-heading">
                              <div>
                                <span className="section-label">Refund review request</span>
                                <strong>Prepare a synthetic review</strong>
                              </div>
                              <span className="muted">Maximum $50.00</span>
                            </div>
                            <div className="refund-request-fields">
                              <label htmlFor="support-refund-amount">Amount (USD)
                                <input
                                  id="support-refund-amount"
                                  type="number"
                                  min="0.01"
                                  max="50"
                                  step="0.01"
                                  value={supportRefundAmount}
                                    onChange={(event) => {
                                      setSupportRefundAmount(event.target.value);
                                      setSupportRefundRequestKey(null);
                                    }}
                                  disabled={isCreatingRefund}
                                />
                              </label>
                              <label htmlFor="support-refund-reason">Reason
                                <input
                                  id="support-refund-reason"
                                  value={supportRefundReason}
                                    onChange={(event) => {
                                      setSupportRefundReason(event.target.value);
                                      setSupportRefundRequestKey(null);
                                    }}
                                  maxLength={500}
                                  disabled={isCreatingRefund}
                                />
                              </label>
                              <button className="secondary-button" type="submit" disabled={isCreatingRefund}>
                                {isCreatingRefund ? "Creating review…" : "Create review request"}
                              </button>
                            </div>
                            {supportRefundNotice && (
                              <div className="refund-request-success" role="status">{supportRefundNotice}</div>
                            )}
                          </form>
                        )}
                        </>
                      ) : (
                        <div className="staff-state" role="status">
                          <strong>{selectedSupportConversation.state === "RESOLVED" ? "Conversation resolved" : "Claim required"}</strong>
                          <span>{selectedSupportConversation.state === "RESOLVED" ? "This local demo conversation is closed." : "Claim the conversation to enable a staff reply. AI replies remain off during human handling."}</span>
                        </div>
                      )}
                    </>
                  )}
                </section>
                <aside className="col-right panel-detail" aria-label="Case evidence"><div className="section-title">Case evidence</div><div className="section-sub">{selectedSupportConversation?.conversation_id??'Select a conversation'}</div>{selectedSupportConversation && <><div className="context-block"><div className="context-title">Customer & order</div>{[['Customer',selectedSupportConversation.customer_id],['Order',selectedSupportConversation.order_id],['Ownership',selectedSupportConversation.state.replaceAll('_',' ')],['Assigned agent',selectedSupportConversation.assigned_staff_id]].map(([k,v])=><div className="kv" key={k}><span className="key">{k}</span><span className="val">{v??'Not provided'}</span></div>)}{selectedSupportConversation.order_id&&<button className="btn sm" disabled={caseOrderLoading} onClick={()=>void lookupCaseOrder()}>{caseOrderLoading?'Checking…':'Check linked order'}</button>}{caseOrder && caseOrder.caseId===selectedSupportConversation.conversation_id&&<>{[['Shipment',caseOrder.order.shipment_status],['Payment',caseOrder.order.payment_status],['Delivery',caseOrder.order.estimated_delivery_date]].map(([k,v])=><div className="kv" key={k}><span className="key">{k}</span><span className="val">{v??'Not provided'}</span></div>)}</>}</div><div className="context-block"><div className="context-title">Applicable policy</div><div className="source">The inbox response does not include policy citations. No source is asserted for this case.</div></div><div className="context-block"><div className="context-title">Conversation timeline</div><div className="timeline">{selectedSupportConversation.messages.slice(-5).map(m=><div className="time-item" key={m.message_id}><b>{m.author_type} message</b>{formatTimestamp(m.created_at)}</div>)}</div></div></>}</aside>
              </div>
            </>
          )}

          {staffNotice && (
            <div className={`notice ${staffNotice.kind} staff-notice`} role="alert">
              <strong>{staffNotice.kind === "denial" ? "Request denied" : "Local API error"}</strong>
              <span>{staffNotice.message}</span>
            </div>
          )}
        </section>}
    {activeSurface==='refunds'&&<section className="staff-panel refund-panel" aria-labelledby="refund-title">
          <header className="staff-header">
            <div>
              <p className="eyebrow accent">RESOLVEAI / MERCHANT OPERATIONS</p>
              <h1 className="heading" id="refund-title">Refund approvals</h1>
              <p>Evidence-first decisions with an explicit boundary between approval and external financial action.</p>
            </div>
            <span className="staff-demo-pill">{productionIdentity?"Provisioned session":"Local demo only"}</span>
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
                  <button className="secondary-button" type="button" onClick={() => void endApproverSession()} disabled={isLoggingOut}>
                    {isLoggingOut ? "Ending..." : "End session"}
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
                <div className="refund-grid" aria-live="polite"><div className="card refund-queue"><div className="pad"><div className="section-title">Review queue</div><div className="section-sub">Separate decision and financial state</div></div>{visibleRefunds.map(item=><button type="button" key={item.refund_id} onClick={()=>setSelectedRefundId(item.refund_id)} className={`refund-item ${selectedRefund?.refund_id===item.refund_id?'selected':''}`}><strong>{item.refund_id}</strong><span className={`state-badge ${item.state}`}>{item.state}</span><p>{item.order_id} · {item.reason}</p><b>{formatCents(item.amount_cents)}</b></button>)}</div><div className="refund-list">
                  {selectedRefund && [selectedRefund].map((refund) => (
                    <article className="refund-card" key={refund.refund_id}>
                      <div className="refund-card-header">
                        <div>
                          <p className="section-label">Refund request</p>
                          <h3>{refund.refund_id}</h3>
                          <p className="refund-card-meta">Order {refund.order_id} · Conversation {refund.conversation_id}</p>
                        </div>
                        <span className={`state-badge ${refund.state}`}>{refund.state}</span>
                      </div>
                      <div className="refund-amount"><div className="helper">Amount requested</div><div className="refund-total">{formatCents(refund.amount_cents)}</div><div className="helper">USD · synthetic financial data</div></div><div className="refund-card-details refund-sections">
                        <div>
                          <span className="refund-detail-label">Transaction context</span><strong>Order {refund.order_id}</strong><span>Captured payment and prior refunds not returned by this API.</span>
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
                      <div className="panel-surface execution-panel"><strong>Execution & reconciliation</strong><div className="kv"><span className="key">Financial action</span><span className="val">Not performed by ResolveAI</span></div><div className="kv"><span className="key">Provider verification</span><span className="val">Unavailable in local demo</span></div></div>{refund.decision_note && <p className="refund-decision-note">{refund.decision_note}</p>}
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
                </div></div>
              )}
            </>
          )}

          {refundNotice && (
            <div className="notice refund-notice" role="alert">
              <strong>{refundNotice.kind === "denial" ? "Request denied" : "Local API error"}</strong>
              <span>{refundNotice.message}</span>
            </div>
          )}
        </section>}
    {(['overview','knowledge','team','settings'] as string[]).includes(activeSurface)&&<><WorkspaceSurface activeSurface={activeSurface as WorkspaceSurfaceName} session={workspaceSession} isStarting={isWorkspaceStarting} onStartSession={startWorkspaceSession} onLogout={()=>void endWorkspaceSession()} isLoggingOut={isLoggingOut} navigate={navigateSurface}/>{workspaceLoginNotice&&<div className={`notice ${workspaceLoginNotice.kind}`} role="alert"><strong>Local API error</strong><span>{workspaceLoginNotice.message}</span></div>}</>}
    {!['overview','knowledge','team','settings','widget-preview','support','refunds'].includes(activeSurface)&&<>{workspaceSession&&<div className="workspace-session-toolbar"><span>Signed in as {workspaceSession.actor.display_name}</span><button className="secondary-button compact-button" onClick={()=>void endWorkspaceSession()} disabled={isLoggingOut}>End session</button></div>}<ExtraSurface supportSession={staffSession} supportInbox={supportInbox} startSupport={startStaffSession} supportStarting={isStaffStarting} endSupport={()=>void endStaffSession()} selectCase={(id)=>{if(!staffSession)return;void loadSupportInbox(staffSession.session_id).then(()=>{setSelectedSupportConversationId(id);navigateSurface("support");});}} key={`${activeSurface}-${workspaceSession?.actor.actor_id??'anonymous'}`} surface={activeSurface} navigate={navigateSurface} session={workspaceSession} startSession={startWorkspaceSession} starting={isWorkspaceStarting} notice={workspaceLoginNotice?.message} /></>}
  </DesignShell>;
}
