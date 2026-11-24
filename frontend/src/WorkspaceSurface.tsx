import { Icon, PageHeading, type Surface } from "./DesignShell";
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

export type WorkspaceSurfaceName = "overview" | "knowledge" | "team" | "settings";

interface WorkspaceSurfaceProps {
  activeSurface: WorkspaceSurfaceName;
  session: DemoLoginResponse | null;
  isStarting: boolean;
  onStartSession: () => void;
  onLogout: () => void;
  isLoggingOut: boolean;
  navigate: (surface: Surface) => void;
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

function OverviewView({ sessionId, navigate, name }: { sessionId: string; navigate: (s:Surface)=>void; name:string }) {
  const [summary, setSummary] = useState<OpsSummary | null>(null);
  const [published,setPublished]=useState<number|null>(null);
  const [error, setError] = useState<ViewError | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setSummary(await getOpsSummary(sessionId));
      try {setPublished((await getKnowledgePolicies(sessionId,{query:"",status:"published"})).total);} catch {setPublished(null);}
    } catch (requestError) {
      setSummary(null);
      setError(errorFrom(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [sessionId]);

  return <section className="workspace-view" aria-label="Operations overview"><PageHeading title={`Welcome, ${name}.`} subtitle="See what needs attention across support, knowledge, and your store connection." actions={<><button className="btn" onClick={()=>navigate('support')}><Icon name="inbox"/> Open inbox</button><button className="btn primary" onClick={()=>navigate('playground')}><Icon name="flask"/> Test AI</button></>}/><div className="flag warning"><Icon name="info"/><span><b>Local synthetic pilot.</b> No live Shopify, payment or qualified hosted model connection is asserted.</span></div><div className="pilot-banner"><div><div className="eyebrow" style={{color:'#64dfc4'}}>MERCHANT PILOT</div><h2>One connected workflow. Real evidence. Human control.</h2><p>Connect your store, publish trusted policies, answer customers, and resolve escalations—with refund execution remaining in your own system.</p></div><button className="btn primary" onClick={()=>navigate('onboarding')}><Icon name="arrow"/> Finish setup</button></div>{error&&<ViewNotice error={error}/>}<div className="grid g4" style={{marginBottom:17}}>{[['Active conversations',summary?.active_conversations,'Currently in progress','chat'],['Handoffs queued',summary?.waiting_for_human,'Awaiting an assigned agent','headset'],['Refunds awaiting review',summary?.pending_refund_reviews,'No payment action taken','shield'],['Published policy sources',published,'Published catalog entries','book']].map(([label,value,note,ico])=><div className="card metric" key={label}><div className="metric-name">{label}</div><div className="metric-icon"><Icon name={String(ico)}/></div><div className="metric-value">{value??'—'}</div><div className="metric-foot">{note}</div></div>)}</div><div className="grid g73"><section className="card pad"><div className="section-head"><div><div className="section-title">Support activity</div><div className="section-sub">Current authorized snapshot · weekly series unavailable</div></div><button className="btn sm" onClick={()=>void load()} disabled={loading}>{loading?'Refreshing…':'Refresh overview'}</button></div><div className="snapshot-chart">{[['Active',summary?.active_conversations],['Waiting for human',summary?.waiting_for_human],['Resolved',summary?.resolved_conversations]].map(([label,count])=><div key={label}><span>{label}</span><div className="progress-track"><span style={{width:`${summary&&typeof count==='number'?Math.min(100,count/Math.max(1,summary.total_conversations)*100):0}%`}}/></div><b>{count??'—'}</b></div>)}</div><p className="helper">Total conversations: {summary?.total_conversations??'—'}</p></section><section className="card pad"><div className="section-title">Needs your attention</div><div className="section-sub">Queues connected to the core workflow</div><div className="stack" style={{marginTop:18}}>{[['inbox',`${summary?.waiting_for_human??'—'} human handoffs`,'Customer waiting for an agent','support','Open'],['shield',`${summary?.pending_refund_reviews??'—'} pending refund reviews`,'Decision and execution remain separate','refunds','Review'],['book','Policy management','Index, test and publish','knowledge','Manage']].map(([icon,title,sub,route,button])=><div className="info-card" key={route}><div className="tile-icon"><Icon name={icon}/></div><div style={{flex:1}}><strong>{title}</strong><p>{sub}</p></div><button className="btn sm" onClick={()=>navigate(route as Surface)}>{button}</button></div>)}</div></section></div><div className="grid g73" style={{marginTop:17}}><section className="card pad"><div className="section-head"><div><div className="section-title">Recent customer conversations</div><div className="section-sub">Activity returned by the authorized workspace API</div></div><button className="link" onClick={()=>navigate('support')}>View inbox →</button></div><div className="tablewrap"><table className="table"><thead><tr><th>Conversation</th><th>Activity</th><th>Time</th></tr></thead><tbody>{summary?.recent_activity.map(item=><tr key={item.activity_id}><td className="maincell">{item.label}</td><td>{item.kind}</td><td>{formatDate(item.occurred_at)}</td></tr>)}</tbody></table></div>{!summary?.recent_activity.length&&<p className="helper">{loading?'Loading overview…':'No recent activity returned.'}</p>}</section><section className="card pad"><div className="section-title">Pilot readiness</div><div className="section-sub">Backend gates, not decorative checkmarks</div>{[['Shopify access','Not connected'],['Published knowledge',published===null?'Not verified':`${published} catalog entries`],['Staff permissions','Local authenticated demo session'],['Widget installation','Local preview only']].map(([label,sub],i)=><div className="checkline" key={label}><div className={`checkball ${i===1&&published!==null?'':'wait'}`}><Icon name={i===1&&published!==null?'check':'clock'}/></div><div className="desc"><strong>{label}</strong><span>{sub}</span></div></div>)}</section></div></section>;

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
        <div><p className="eyebrow accent">Knowledge management</p><h2 id="knowledge-title">Knowledge base</h2><p className="muted">Drafts are versioned and server-authorized. Publishing and rollback carry the revision observed by this session.</p></div>
        {canEdit && <button className="primary-button" type="button" onClick={startDraft}>Create draft</button>}
      </div>
      {error && <ViewNotice error={error} />}
      <form className="knowledge-toolbar" onSubmit={submitSearch}>
        <label htmlFor="policy-search">Search policies<input id="policy-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title or policy ID" /></label>
        <label htmlFor="policy-status">Status<select id="policy-status" value={status} onChange={(event) => { setStatus(event.target.value); void loadPolicies(query, event.target.value); }}><option value="all">All statuses</option><option value="published">Published</option><option value="draft">Draft</option><option value="unpublished">Unpublished</option></select></label>
        <button className="primary-button" type="submit" disabled={loading}>{loading ? "Searching…" : "Search catalog"}</button>
      </form>
      <div className="grid g3 knowledge-metrics">{[["Published sources",policies.filter(p=>p.status==='published').length],["Draft / review",policies.filter(p=>['draft','indexing','testable'].includes(p.status)).length],["Other versions",policies.filter(p=>!['published','draft','indexing','testable'].includes(p.status)).length]].map(([label,value])=><div className="card metric" key={label}><div className="metric-name">{label}</div><div className="metric-value">{loading||error?'—':value}</div><div className="metric-foot">Current filtered catalog</div></div>)}</div><div className="knowledge-layout">
        <div className="policy-list card pad" aria-label="Policy catalog"><div className="section-title">Policy documents</div><div className="section-sub">Published releases and isolated drafts</div>
          {loading && policies.length === 0 ? <div className="workspace-empty-state"><strong>Loading policies…</strong><span>Reading the authorized knowledge catalog.</span></div> : policies.length === 0 ? <div className="workspace-empty-state"><strong>No policies found</strong><span>Try a different search or status filter.</span></div> : policies.map((policy) => <button className={`policy-list-item ${selected?.document_id === policy.document_id && selected.document_version === policy.document_version ? "selected" : ""}`} type="button" key={`${policy.document_id}-${policy.document_version}`} onClick={() => void openPolicy(policy)}><span><strong>{policy.title}</strong><small>{policy.document_id} · {policy.document_version}</small></span><span className="policy-meta"><b>{policy.status}</b><small>{policy.section_count} sections</small></span></button>)}
        </div>
        <article className="policy-detail card pad" aria-live="polite">
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
          <div className="policy-editor-sections"><div className="workspace-section-heading"><h4>Sections</h4><button className="secondary-button compact-button" type="button" onClick={addSection}>Add section</button></div>{editor.sections.map((section, index) => <fieldset key={index}><legend>Section {index + 1}</legend><label>Heading<input value={section.section} onChange={(event) => updateSection(index, "section", event.target.value)} required /></label><label>Content<textarea value={section.content} onChange={(event) => updateSection(index, "content", event.target.value)} rows={4} required /></label>{editor.sections.length > 1 && <button className="text-button" type="button" onClick={() => removeSection(index)}>Remove section</button>}</fieldset>)}</div>
          <div className="policy-editor-actions"><button className="secondary-button" type="button" onClick={() => { setIsCreatingDraft(false); if (selected) setEditor(editorFromPolicy(selected)); }}>Cancel</button><button className="primary-button" type="submit" disabled={mutationAction !== null}>{mutationAction === "create" ? "Creating draft…" : mutationAction === "save" ? "Saving draft…" : isCreatingDraft ? "Create draft" : "Save changes"}</button></div>
        </form>
      )}
    </section>
  );
}

function TeamView({ sessionId, surface }: { sessionId: string; surface: "team"|"settings" }) {
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
      <div className="workspace-view-heading"><div><p className="eyebrow accent">Team and settings</p><h2 id="team-title">{surface==='team'?'Team & access':'Workspace settings'}</h2><p className="muted">Role grants and workspace settings are displayed from the authorized API. This view does not offer unsupported mutations.</p></div><button className="secondary-button" type="button" onClick={() => void load()} disabled={loading}>{loading ? "Refreshing…" : "Refresh workspace"}</button></div>
      {error && <ViewNotice error={error} />}
      {loading && !settings ? <div className="workspace-empty-state" role="status"><strong>Loading workspace…</strong><span>Checking team grants and settings.</span></div> : settings ? surface==='team'?<section className="card pad"><div className="section-head"><div><div className="section-title">Staff role model</div><div className="section-sub">Actual grants from the authorized workspace API</div></div><span className="badge blue">LOCAL DEMO</span></div><div className="tablewrap"><table className="table"><thead><tr><th>Member</th><th>Actor ID</th><th>Role</th><th>Permissions</th></tr></thead><tbody>{members.map(member=><tr key={member.actor_id}><td className="maincell">{member.display_name}</td><td>{member.actor_id}</td><td>{member.role}</td><td style={{whiteSpace:'normal'}}>{member.permissions.join(' · ')||'None returned'}</td></tr>)}</tbody></table></div>{members.length===0&&<p className="helper">No team members returned.</p>}<div className="flag soft" style={{marginTop:18}}><Icon name="lock"/> Roles are server-controlled. No user provisioning or permission changes are available here.</div></section>:<div className="grid g64"><section className="card pad"><div className="section-title">Workspace profile</div><div className="section-sub">Read-only configuration from the server</div><div className="grid g2" style={{marginTop:18}}>{[['Workspace',settings.merchant_name],['Environment',settings.environment],['Retrieval',settings.retrieval_mode],['Generation',settings.generation_mode],['Data mode',settings.synthetic_data?'Synthetic local records':'Not marked synthetic']].map(([label,value])=><label className="field" key={label}>{label}<input className="input" value={value} readOnly/></label>)}</div></section><section className="card pad"><div className="section-title">Non-configurable security boundaries</div><div className="section-sub">Required backend safeguards, not user toggles</div>{['Customer and staff authorization','Order ownership checks','Separate human refund approval','No autonomous refund writes','Internal policy isolation'].map(label=><div className="kv" key={label}><span className="key">{label}</span><span className="badge gray">REQUIRED</span></div>)}<div className="notice-inline"><Icon name="lock"/> These are release requirements, not fresh security test results.</div></section></div>:null}
    </section>
  );
}

export default function WorkspaceSurface(props: WorkspaceSurfaceProps) {
  if (!props.session) return <><PageHeading title={{overview:"Overview",knowledge:"Knowledge base",team:"Team & access",settings:"Workspace settings"}[props.activeSurface]} subtitle="Establish a local demo session to view authorized workspace records."/><WorkspaceLogin isStarting={props.isStarting} onStartSession={props.onStartSession} /></>;
  const sessionId = props.session.session_id;
  return (
    <>
      <div className="workspace-session-toolbar">
        <span>Signed in as {props.session.actor.display_name}</span>
        <button className="secondary-button compact-button" type="button" onClick={props.onLogout} disabled={props.isLoggingOut}>
          {props.isLoggingOut ? "Ending..." : "End session"}
        </button>
      </div>
      {props.activeSurface === "overview" && <OverviewView sessionId={sessionId} navigate={props.navigate} name={props.session.actor.display_name} />}
      {props.activeSurface === "knowledge" && <KnowledgeView sessionId={sessionId} canEdit={props.session.actor.role === "merchant_admin"} />}
      {(props.activeSurface === "team" || props.activeSurface === "settings") && <TeamView sessionId={sessionId} surface={props.activeSurface} />}
    </>
  );
}
