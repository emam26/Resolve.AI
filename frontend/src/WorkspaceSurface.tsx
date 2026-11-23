import { FormEvent, useEffect, useState } from "react";
import {
  ApiError,
  createKnowledgePolicy,
  DemoLoginResponse,
  getKnowledgePolicies,
  getKnowledgePolicy,
  getKnowledgePolicyAudit,
  getKnowledgePolicyVersions,
  getOpsSummary,
  getWorkspaceSettings,
  getWorkspaceTeam,
  KnowledgePolicyAuditEvent,
  KnowledgePolicyDetail,
  KnowledgePolicyDraftInput,
  KnowledgePolicyMutation,
  KnowledgePolicySummary,
  OpsSummary,
  indexKnowledgePolicy,
  publishKnowledgePolicy,
  rollbackKnowledgePolicy,
  validateKnowledgePolicy,
  updateKnowledgePolicy,
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

type ViewError = {
  kind: "denial" | "error";
  message: string;
  code?: string;
  details?: Record<string, unknown>;
};

function errorFrom(error: unknown): ViewError {
  if (error instanceof ApiError) {
    return {
      kind: error.status === 401 || error.status === 403 ? "denial" : "error",
      message: error.message,
      code: error.code,
      details: error.details,
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
  const isConflict = error.code === "revision_conflict" || error.message.toLowerCase().includes("revision");
  return (
    <div className={`notice ${error.kind}`} role="alert">
      <strong>{error.kind === "denial" ? "Access denied" : isConflict ? "Conflict" : "Workspace error"}</strong>
      <span>{error.message}</span>
      {error.code && <small className="notice-code">Code: {error.code}</small>}
      {error.details && Object.keys(error.details).length > 0 && (
        <small className="notice-details">{JSON.stringify(error.details)}</small>
      )}
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

type PolicyEditorState = {
  document_id: string;
  title: string;
  document_version: string;
  release_id: string;
  visibility: "public" | "internal";
  sections: KnowledgePolicyDraftInput["sections"];
};

function emptyPolicyEditor(): PolicyEditorState {
  return {
    document_id: "",
    title: "",
    document_version: "",
    release_id: "release_local_v1",
    visibility: "public",
    sections: [{ section: "Policy scope", content: "" }],
  };
}

function editorFromPolicy(policy: KnowledgePolicyDetail): PolicyEditorState {
  return {
    document_id: policy.document_id,
    title: policy.title,
    document_version: policy.document_version,
    release_id: policy.release_id ?? "",
    visibility: policy.visibility === "internal" ? "internal" : "public",
    sections: policy.sections.length > 0 ? policy.sections : [{ section: "Policy scope", content: "" }],
  };
}

function KnowledgeView({ sessionId, canEdit }: { sessionId: string; canEdit: boolean }) {
  const [policies, setPolicies] = useState<KnowledgePolicySummary[]>([]);
  const [selected, setSelected] = useState<KnowledgePolicyDetail | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [error, setError] = useState<ViewError | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editor, setEditor] = useState<PolicyEditorState>(emptyPolicyEditor);
  const [isCreatingDraft, setIsCreatingDraft] = useState(false);
  const [mutationAction, setMutationAction] = useState<"create" | "save" | "validate" | "index" | "publish" | "rollback" | null>(null);
  const [targetVersion, setTargetVersion] = useState("");
  const [auditEvents, setAuditEvents] = useState<KnowledgePolicyAuditEvent[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [managedVersions, setManagedVersions] = useState<KnowledgePolicyMutation[]>([]);
  const [validation, setValidation] = useState<{ valid: boolean; errors: string[] } | null>(null);
  const [actionStatus, setActionStatus] = useState<string | null>(null);

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
    setAuditEvents([]);
    setManagedVersions([]);
    setValidation(null);
    setActionStatus(null);
    try {
      const detail = await getKnowledgePolicy(sessionId, policy.document_id, policy.document_version);
      setSelected(detail);
      setEditor(editorFromPolicy(detail));
      const versions = canEdit ? await getKnowledgePolicyVersions(sessionId, policy.document_id) : [];
      setManagedVersions(versions);
      const managed = versions.find((item) => item.document_version === policy.document_version);
      if (managed && managed.version_id) {
        setSelected(managed);
        setAuditEvents((await getKnowledgePolicyAudit(sessionId, managed.version_id)).events);
      }
      const alternative = versions.find((item) => item.document_version !== policy.document_version) ?? policies.find((item) => item.document_id === policy.document_id && item.document_version !== policy.document_version);
      setTargetVersion(alternative?.document_version ?? "");
      setIsCreatingDraft(false);
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

  function startDraft() {
    setSelected(null);
    setEditor(emptyPolicyEditor());
    setTargetVersion("");
    setAuditEvents([]);
    setManagedVersions([]);
    setValidation(null);
    setActionStatus(null);
    setIsCreatingDraft(true);
    setError(null);
  }

  function updateEditor<K extends keyof PolicyEditorState>(key: K, value: PolicyEditorState[K]) {
    setEditor((current) => ({ ...current, [key]: value }));
  }

  function updateSection(index: number, key: "section" | "content", value: string) {
    setEditor((current) => ({
      ...current,
      sections: current.sections.map((section, sectionIndex) => sectionIndex === index ? { ...section, [key]: value } : section),
    }));
  }

  function addSection() {
    setEditor((current) => ({ ...current, sections: [...current.sections, { section: "New section", content: "" }] }));
  }

  function removeSection(index: number) {
    setEditor((current) => ({
      ...current,
      sections: current.sections.length <= 1 ? current.sections : current.sections.filter((_, sectionIndex) => sectionIndex !== index),
    }));
  }

  function validateEditor(): string | null {
    if (!editor.document_id.trim() || !editor.title.trim()) return "Document ID and title are required.";
    if (editor.sections.some((section) => !section.section.trim() || !section.content.trim())) return "Every policy section needs a heading and content.";
    return null;
  }

  async function applyMutation(action: "create" | "save" | "validate" | "index" | "publish" | "rollback") {
    const validationError = action === "publish" || action === "rollback" || action === "validate" || action === "index" ? null : validateEditor();
    if (validationError) {
      setError({ kind: "error", message: validationError, code: "invalid_policy_form" });
      return;
    }
    if (action !== "create" && !selected?.version_id) return;
    if (action === "rollback" && !targetVersion) {
      setError({ kind: "error", message: "Choose a target version before rolling back.", code: "target_version_required" });
      return;
    }

    setMutationAction(action);
    setError(null);
    setValidation(null);
    setActionStatus(null);
    try {
      let result: KnowledgePolicyMutation;
      if (action === "create") {
        result = await createKnowledgePolicy(sessionId, editor);
      } else if (action === "save") {
        result = await updateKnowledgePolicy(sessionId, selected!.version_id!, {
          expected_revision: selected!.revision ?? 0,
          release_id: editor.release_id,
          visibility: editor.visibility,
          sections: editor.sections,
        });
      } else if (action === "validate") {
        const response = await validateKnowledgePolicy(sessionId, selected!.version_id!);
        setValidation({ valid: response.valid, errors: response.errors });
        setActionStatus(response.valid ? "Validation passed." : "Validation found issues.");
        return;
      } else if (action === "index") {
        result = await indexKnowledgePolicy(sessionId, selected!.version_id!);
      } else if (action === "publish") {
        result = await publishKnowledgePolicy(sessionId, selected!.version_id!, selected!.revision ?? 0);
      } else {
        result = await rollbackKnowledgePolicy(sessionId, selected!.document_id, targetVersion, selected!.revision ?? 0);
      }
      setSelected(result);
      setEditor(editorFromPolicy(result));
      setIsCreatingDraft(false);
      setAuditEvents([]);
      const indexUnavailable = action === "index" && (result.status === "failed" || result.index_state === "UNAVAILABLE");
      setActionStatus(indexUnavailable ? "Index unavailable; publication remains blocked." : action === "create" ? "Draft created." : action === "save" ? "Draft saved." : action === "index" ? "Index refreshed." : action === "publish" ? "Policy published." : "Policy rolled back and published.");
      await loadPolicies();
      if (canEdit) setManagedVersions(await getKnowledgePolicyVersions(sessionId, result.document_id));
      if (result.version_id) setAuditEvents((await getKnowledgePolicyAudit(sessionId, result.version_id)).events);
      if (action === "rollback") setTargetVersion("");
    } catch (requestError) {
      setError(errorFrom(requestError));
    } finally {
      setMutationAction(null);
    }
  }

  async function loadAudit() {
    if (!selected) return;
    setAuditLoading(true);
    setError(null);
    try {
      if (!selected.version_id) return;
      if (selected.version_id) setAuditEvents((await getKnowledgePolicyAudit(sessionId, selected.version_id)).events);
    } catch (requestError) {
      setError(errorFrom(requestError));
    } finally {
      setAuditLoading(false);
    }
  }

  const selectedVersions = managedVersions.filter((policy) => policy.document_version !== selected?.document_version);
  const isDraft = selected ? ["draft", "indexing", "testable", "ready_for_test"].includes(selected.status) : false;
  const hasRevision = Boolean(selected?.version_id && selected?.revision !== null && selected?.revision !== undefined);

  return (
    <section className="workspace-view" aria-labelledby="knowledge-title">
      <div className="workspace-view-heading">
        <div><p className="eyebrow accent">Knowledge management</p><h2 id="knowledge-title">Maintain policy evidence safely.</h2><p className="muted">Drafts are versioned and server-authorized. Publishing and rollback carry the revision observed by this session.</p></div>
        {canEdit && <button className="primary-button" type="button" onClick={startDraft}>Create draft</button>}
      </div>
      {error && <ViewNotice error={error} />}
      <form className="knowledge-toolbar" onSubmit={submitSearch}>
        <label htmlFor="policy-search">Search policies<input id="policy-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title or policy ID" /></label>
        <label htmlFor="policy-status">Status<select id="policy-status" value={status} onChange={(event) => { setStatus(event.target.value); void loadPolicies(query, event.target.value); }}><option value="all">All statuses</option><option value="published">Published</option><option value="draft">Draft</option><option value="unpublished">Unpublished</option></select></label>
        <button className="primary-button" type="submit" disabled={loading}>{loading ? "Searching…" : "Search catalog"}</button>
      </form>
      <div className="knowledge-layout">
        <div className="policy-list" aria-label="Policy catalog">
          {loading && policies.length === 0 ? <div className="workspace-empty-state"><strong>Loading policies…</strong><span>Reading the authorized knowledge catalog.</span></div> : policies.length === 0 ? <div className="workspace-empty-state"><strong>No policies found</strong><span>Try a different search or status filter.</span></div> : policies.map((policy) => <button className={`policy-list-item ${selected?.document_id === policy.document_id && selected.document_version === policy.document_version ? "selected" : ""}`} type="button" key={`${policy.document_id}-${policy.document_version}`} onClick={() => void openPolicy(policy)}><span><strong>{policy.title}</strong><small>{policy.document_id} · {policy.document_version}</small></span><span className="policy-meta"><b>{policy.status}</b><small>{policy.section_count} sections</small></span></button>)}
        </div>
        <article className="policy-detail" aria-live="polite">
          {detailLoading ? <div className="workspace-empty-state"><strong>Loading policy detail…</strong><span>Checking the selected version.</span></div> : selected ? <>
            <div className="policy-detail-heading"><div><p className="section-label">{selected.document_id} · {selected.document_version}</p><h3>{selected.title}</h3></div><span className="state-badge">{selected.status}</span></div>
            <dl className="policy-facts"><div><dt>Visibility</dt><dd>{selected.visibility}</dd></div><div><dt>Release</dt><dd>{selected.release_id ?? "Not provided"}</dd></div><div><dt>Revision</dt><dd>{selected.revision ?? "Unknown"}</dd></div><div><dt>Index</dt><dd>{selected.index_state ?? "Not provided"}</dd></div></dl>
            {canEdit && hasRevision && <div className="policy-action-bar">{isDraft && <button className="secondary-button" type="button" onClick={() => setIsCreatingDraft(false)}>Edit current version</button>}<button className="secondary-button" type="button" onClick={() => void applyMutation("validate")} disabled={mutationAction !== null}>{mutationAction === "validate" ? "Validating…" : "Validate"}</button><button className="secondary-button" type="button" onClick={() => void applyMutation("index")} disabled={mutationAction !== null}>{mutationAction === "index" ? "Indexing…" : "Refresh index"}</button><button className="secondary-button" type="button" onClick={() => void loadAudit()} disabled={auditLoading}>{auditLoading ? "Loading audit…" : "View audit"}</button>{isDraft && <button className="primary-button" type="button" onClick={() => void applyMutation("publish")} disabled={mutationAction !== null}>{mutationAction === "publish" ? "Publishing…" : "Publish version"}</button>}</div>}
            {validation && <div className={`policy-validation ${validation.valid ? "valid" : "invalid"}`} role="status"><strong>{validation.valid ? "Validation passed" : "Validation failed"}</strong>{validation.errors.length > 0 && <ul>{validation.errors.map((item) => <li key={item}>{item}</li>)}</ul>}</div>}
            {actionStatus && <p className="policy-action-status" role="status">{actionStatus}</p>}
            <div className="policy-sections">{selected.sections.map((section) => <section key={section.section}><h4>{section.section}</h4><p>{section.content}</p></section>)}</div>
            {canEdit && hasRevision && selectedVersions.length > 0 && <div className="policy-rollback-bar"><label htmlFor="rollback-version">Rollback target<select id="rollback-version" value={targetVersion} onChange={(event) => setTargetVersion(event.target.value)}><option value="">Choose a version</option>{selectedVersions.map((version) => <option key={version.document_version} value={version.document_version}>{version.document_version} · {version.status}</option>)}</select></label><button className="secondary-button" type="button" onClick={() => void applyMutation("rollback")} disabled={mutationAction !== null || !targetVersion}>{mutationAction === "rollback" ? "Rolling back…" : "Rollback"}</button></div>}
            {auditEvents.length > 0 && <section className="policy-audit" aria-labelledby="policy-audit-title"><div className="workspace-section-heading"><div><p className="section-label">Audit trail</p><h4 id="policy-audit-title">Version events</h4></div></div><ol>{auditEvents.map((event) => <li key={event.event_id}><strong>{event.action}</strong><span>{event.actor_id} · revision {event.revision}</span><time dateTime={event.created_at}>{formatDate(event.created_at)}</time></li>)}</ol></section>}
          </> : <div className="workspace-empty-state"><strong>Select a policy</strong><span>Choose a catalog entry to inspect its version, edit permissions, and audit history.</span></div>}
        </article>
      </div>
      {canEdit && (isCreatingDraft || selected) && (isCreatingDraft || selected?.status !== "published") && (
        <form className="policy-editor-card" onSubmit={(event) => { event.preventDefault(); void applyMutation(isCreatingDraft ? "create" : "save"); }}>
          <div className="workspace-section-heading"><div><p className="section-label">{isCreatingDraft ? "New draft" : "Draft editor"}</p><h3>{isCreatingDraft ? "Create a versioned policy draft" : "Edit draft content"}</h3><p className="muted">The server rechecks role, revision, validation, and publication state.</p></div><span className="staff-demo-pill">Admin action</span></div>
          <div className="policy-editor-meta"><label>Document ID<input value={editor.document_id} onChange={(event) => updateEditor("document_id", event.target.value)} disabled={!isCreatingDraft} required /></label><label>Title<input value={editor.title} onChange={(event) => updateEditor("title", event.target.value)} required /></label><label>Version <span>(optional)</span><input value={editor.document_version} onChange={(event) => updateEditor("document_version", event.target.value)} disabled={!isCreatingDraft} placeholder="v1" /></label><label>Release ID<input value={editor.release_id} onChange={(event) => updateEditor("release_id", event.target.value)} required /></label><label>Visibility<select value={editor.visibility} onChange={(event) => updateEditor("visibility", event.target.value as PolicyEditorState["visibility"])}><option value="public">Public customer evidence</option><option value="internal">Internal staff evidence</option></select></label></div>
          <div className="policy-editor-sections"><div className="workspace-section-heading"><h4>Sections</h4><button className="secondary-button compact-button" type="button" onClick={addSection}>Add section</button></div>{editor.sections.map((section, index) => <fieldset key={`${index}-${section.section}`}><legend>Section {index + 1}</legend><label>Heading<input value={section.section} onChange={(event) => updateSection(index, "section", event.target.value)} required /></label><label>Content<textarea value={section.content} onChange={(event) => updateSection(index, "content", event.target.value)} rows={4} required /></label>{editor.sections.length > 1 && <button className="text-button" type="button" onClick={() => removeSection(index)}>Remove section</button>}</fieldset>)}</div>
          <div className="policy-editor-actions"><button className="secondary-button" type="button" onClick={() => { setIsCreatingDraft(false); if (selected) setEditor(editorFromPolicy(selected)); }}>Cancel</button><button className="primary-button" type="submit" disabled={mutationAction !== null}>{mutationAction === "create" ? "Creating draft…" : mutationAction === "save" ? "Saving draft…" : isCreatingDraft ? "Create draft" : "Save changes"}</button></div>
        </form>
      )}
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
  if (props.activeSurface === "knowledge") return <KnowledgeView sessionId={sessionId} canEdit={props.session.actor.role === "merchant_admin"} />;
  return <TeamView sessionId={sessionId} />;
}
