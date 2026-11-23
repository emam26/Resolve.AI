import { FormEvent, useEffect, useState } from "react";
import {
  ApiError,
  DemoLoginResponse,
  getKnowledgePolicies,
  getKnowledgePolicy,
  getOpsSummary,
  getWorkspaceSettings,
  getWorkspaceTeam,
  KnowledgePolicyDetail,
  KnowledgePolicySummary,
  OpsSummary,
  WorkspaceSettings,
  WorkspaceTeamMember,
} from "./api";

export type WorkspaceSurfaceName = "overview" | "knowledge" | "team";

interface WorkspaceSurfaceProps {
  activeSurface: WorkspaceSurfaceName;
  session: DemoLoginResponse | null;
  isStarting: boolean;
  onStartSession: () => void;
}

type ViewError = { kind: "denial" | "error"; message: string };

function errorFrom(error: unknown): ViewError {
  if (error instanceof ApiError) {
    return {
      kind: error.status === 401 || error.status === 403 ? "denial" : "error",
      message: error.message,
    };
  }
  return { kind: "error", message: "The local API returned an unreadable response." };
}

function formatDate(value: string | null): string {
  if (!value) return "Not provided";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function numberFormat(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function WorkspaceLogin({ isStarting, onStartSession }: Pick<WorkspaceSurfaceProps, "isStarting" | "onStartSession">) {
  return (
    <section className="workspace-login" aria-labelledby="workspace-login-title">
      <div className="workspace-icon" aria-hidden="true">W</div>
      <div>
        <p className="section-label">Authorized workspace session</p>
        <h2 id="workspace-login-title">Open the merchant workspace</h2>
        <p className="muted">The local API will establish the synthetic merchant-admin identity. No browser-supplied role is trusted.</p>
      </div>
      <button className="primary-button" type="button" onClick={onStartSession} disabled={isStarting}>
        {isStarting ? "Opening workspace…" : "Start Demo Workspace session"}
      </button>
    </section>
  );
}

function ViewNotice({ error }: { error: ViewError }) {
  return (
    <div className={`notice ${error.kind}`} role="alert">
      <strong>{error.kind === "denial" ? "Access denied" : "Workspace error"}</strong>
      <span>{error.message}</span>
    </div>
  );
}

function MetricCard({ label, value, detail }: { label: string; value: number; detail: string }) {
  return (
    <article className="metric-card">
      <span className="section-label">{label}</span>
      <strong>{numberFormat(value)}</strong>
      <span>{detail}</span>
    </article>
  );
}

function OverviewView({ sessionId }: { sessionId: string }) {
  const [summary, setSummary] = useState<OpsSummary | null>(null);
  const [error, setError] = useState<ViewError | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setSummary(await getOpsSummary(sessionId));
    } catch (requestError) {
      setSummary(null);
      setError(errorFrom(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [sessionId]);

  return (
    <section className="workspace-view" aria-labelledby="overview-title">
      <div className="workspace-view-heading">
        <div>
          <p className="eyebrow accent">Operations overview</p>
          <h2 id="overview-title">A clear view of today’s support work.</h2>
          <p className="muted">Metrics are read from the authorized local workspace API; this surface never invents demo counts.</p>
        </div>
        <button className="secondary-button" type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh overview"}
        </button>
      </div>
      {error && <ViewNotice error={error} />}
      {loading && !summary ? (
        <div className="workspace-empty-state" role="status"><strong>Loading overview…</strong><span>Checking current workspace activity.</span></div>
      ) : summary ? (
        <>
          <div className="metric-grid">
            <MetricCard label="Total conversations" value={summary.total_conversations} detail="All local records" />
            <MetricCard label="Active conversations" value={summary.active_conversations} detail="Currently in progress" />
            <MetricCard label="Waiting for human" value={summary.waiting_for_human} detail="Queued handoffs" />
            <MetricCard label="Resolved" value={summary.resolved_conversations} detail="Closed conversations" />
            <MetricCard label="Refund reviews" value={summary.pending_refund_reviews} detail="Pending approval" />
          </div>
          <section className="activity-card" aria-labelledby="activity-title">
            <div className="workspace-section-heading"><div><p className="section-label">Recent activity</p><h3 id="activity-title">Support timeline</h3></div></div>
            {summary.recent_activity.length === 0 ? (
              <div className="workspace-empty-state compact"><strong>No recent activity</strong><span>The API has not returned any activity records.</span></div>
            ) : (
              <ol className="activity-list">
                {summary.recent_activity.map((item) => (
                  <li key={item.activity_id}><span className="activity-dot" aria-hidden="true" /><div><strong>{item.label}</strong><span>{item.kind}{item.conversation_id ? ` · ${item.conversation_id}` : ""}</span></div><time dateTime={item.occurred_at ?? undefined}>{formatDate(item.occurred_at)}</time></li>
                ))}
              </ol>
            )}
          </section>
        </>
      ) : null}
    </section>
  );
}

function KnowledgeView({ sessionId }: { sessionId: string }) {
  const [policies, setPolicies] = useState<KnowledgePolicySummary[]>([]);
  const [selected, setSelected] = useState<KnowledgePolicyDetail | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [error, setError] = useState<ViewError | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  async function loadPolicies(nextQuery = query, nextStatus = status) {
    setLoading(true);
    setError(null);
    try {
      const response = await getKnowledgePolicies(sessionId, { query: nextQuery, status: nextStatus });
      setPolicies(response.policies);
      if (selected && !response.policies.some((policy) => policy.document_id === selected.document_id)) setSelected(null);
    } catch (requestError) {
      setPolicies([]);
      setSelected(null);
      setError(errorFrom(requestError));
    } finally {
      setLoading(false);
    }
  }

  async function openPolicy(policy: KnowledgePolicySummary) {
    setDetailLoading(true);
    setError(null);
    try {
      setSelected(await getKnowledgePolicy(sessionId, policy.document_id, policy.document_version));
    } catch (requestError) {
      setError(errorFrom(requestError));
    } finally {
      setDetailLoading(false);
    }
  }

  useEffect(() => { void loadPolicies("", "all"); }, [sessionId]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadPolicies();
  }

  return (
    <section className="workspace-view" aria-labelledby="knowledge-title">
      <div className="workspace-view-heading">
        <div><p className="eyebrow accent">Knowledge catalog</p><h2 id="knowledge-title">Published policy evidence, in context.</h2><p className="muted">This is a read-only catalog. Publication and retrieval changes stay server-controlled.</p></div>
      </div>
      {error && <ViewNotice error={error} />}
      <form className="knowledge-toolbar" onSubmit={submitSearch}>
        <label htmlFor="policy-search">Search policies<input id="policy-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title or policy ID" /></label>
        <label htmlFor="policy-status">Status<select id="policy-status" value={status} onChange={(event) => { setStatus(event.target.value); void loadPolicies(query, event.target.value); }}><option value="all">All statuses</option><option value="published">Published</option><option value="unpublished">Unpublished</option></select></label>
        <button className="primary-button" type="submit" disabled={loading}>{loading ? "Searching…" : "Search catalog"}</button>
      </form>
      <div className="knowledge-layout">
        <div className="policy-list" aria-label="Policy catalog">
          {loading && policies.length === 0 ? <div className="workspace-empty-state"><strong>Loading policies…</strong><span>Reading the authorized knowledge catalog.</span></div> : policies.length === 0 ? <div className="workspace-empty-state"><strong>No policies found</strong><span>Try a different search or status filter.</span></div> : policies.map((policy) => <button className={`policy-list-item ${selected?.document_id === policy.document_id ? "selected" : ""}`} type="button" key={`${policy.document_id}-${policy.document_version}`} onClick={() => void openPolicy(policy)}><span><strong>{policy.title}</strong><small>{policy.document_id} · {policy.document_version}</small></span><span className="policy-meta"><b>{policy.status}</b><small>{policy.section_count} sections</small></span></button>)}
        </div>
        <article className="policy-detail" aria-live="polite">
          {detailLoading ? <div className="workspace-empty-state"><strong>Loading policy detail…</strong><span>Checking the selected version.</span></div> : selected ? <><div className="policy-detail-heading"><div><p className="section-label">{selected.document_id} · {selected.document_version}</p><h3>{selected.title}</h3></div><span className="state-badge">{selected.status}</span></div><dl className="policy-facts"><div><dt>Visibility</dt><dd>{selected.visibility}</dd></div><div><dt>Effective from</dt><dd>{formatDate(selected.effective_from)}</dd></div><div><dt>Effective to</dt><dd>{formatDate(selected.effective_to)}</dd></div></dl><div className="policy-sections">{selected.sections.map((section) => <section key={section.section}><h4>{section.section}</h4><p>{section.content}</p></section>)}</div></> : <div className="workspace-empty-state"><strong>Select a policy</strong><span>Choose a catalog entry to inspect its version and sections.</span></div>}
        </article>
      </div>
    </section>
  );
}

function TeamView({ sessionId }: { sessionId: string }) {
  const [members, setMembers] = useState<WorkspaceTeamMember[]>([]);
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [error, setError] = useState<ViewError | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [team, workspace] = await Promise.all([getWorkspaceTeam(sessionId), getWorkspaceSettings(sessionId)]);
      setMembers(team.members);
      setSettings(workspace.settings);
    } catch (requestError) {
      setMembers([]);
      setSettings(null);
      setError(errorFrom(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [sessionId]);

  return (
    <section className="workspace-view" aria-labelledby="team-title">
      <div className="workspace-view-heading"><div><p className="eyebrow accent">Team and settings</p><h2 id="team-title">Know who can act, and where.</h2><p className="muted">Role grants and workspace settings are displayed from the authorized API. This view does not offer unsupported mutations.</p></div><button className="secondary-button" type="button" onClick={() => void load()} disabled={loading}>{loading ? "Refreshing…" : "Refresh workspace"}</button></div>
      {error && <ViewNotice error={error} />}
      {loading && !settings ? <div className="workspace-empty-state" role="status"><strong>Loading workspace…</strong><span>Checking team grants and settings.</span></div> : settings ? <div className="team-layout"><section className="activity-card" aria-labelledby="settings-title"><div className="workspace-section-heading"><div><p className="section-label">Workspace settings</p><h3 id="settings-title">{settings.merchant_name}</h3></div><span className="state-badge">{settings.environment}</span></div><dl className="settings-list"><div><dt>Retrieval</dt><dd>{settings.retrieval_mode}</dd></div><div><dt>Generation</dt><dd>{settings.generation_mode}</dd></div><div><dt>Data mode</dt><dd>{settings.synthetic_data ? "Synthetic local records" : "Not marked synthetic"}</dd></div></dl></section><section className="activity-card" aria-labelledby="team-members-title"><div className="workspace-section-heading"><div><p className="section-label">Access</p><h3 id="team-members-title">Team members</h3></div></div>{members.length === 0 ? <div className="workspace-empty-state compact"><strong>No team members returned</strong><span>The API returned an empty team.</span></div> : <ul className="team-list">{members.map((member) => <li key={member.actor_id}><span className="avatar">{member.display_name.slice(0, 2).toUpperCase()}</span><div><strong>{member.display_name}</strong><span>{member.actor_id} · {member.role}</span></div><span className="team-status">{member.status}</span><small>{member.permissions.join(" · ") || "No permissions returned"}</small></li>)}</ul>}</section></div> : null}
    </section>
  );
}

export default function WorkspaceSurface(props: WorkspaceSurfaceProps) {
  if (!props.session) return <WorkspaceLogin isStarting={props.isStarting} onStartSession={props.onStartSession} />;
  const sessionId = props.session.session_id;
  if (props.activeSurface === "overview") return <OverviewView sessionId={sessionId} />;
  if (props.activeSurface === "knowledge") return <KnowledgeView sessionId={sessionId} />;
  return <TeamView sessionId={sessionId} />;
}
