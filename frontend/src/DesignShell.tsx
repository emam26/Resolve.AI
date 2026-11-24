import { useState, type ReactNode } from "react";
import { icons } from "./icons";
export const groups = [
  ["Operations", [["overview","Overview","grid"],["support","Conversations","inbox"],["tickets","Support tickets","receipt"],["refunds","Refund approvals","shield"],["orders","Orders","bag"]]],
  ["AI & Knowledge", [["knowledge","Knowledge base","book"],["playground","Retrieval playground","flask"],["evaluations","AI evaluations","check"]]],
  ["Setup & Governance", [["onboarding","Merchant onboarding","store"],["integrations","Store integration","plug"],["widget-preview","Customer widget","chat"],["team","Team & access","users"],["audit","Audit history","history"],["settings","Workspace settings","settings"]]],
] as const;
export type Surface = typeof groups[number][1][number][0];
export const isSurface = (value: string | null): value is Surface => groups.some(([,items])=>items.some(([id])=>id===value));
export function Icon({name,size=17}:{name:string;size?:number}) {return <span className="ico"><svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" dangerouslySetInnerHTML={{__html:icons[name] || icons.grid}} /></span>}
export function PageHeading({title,subtitle,actions}:{title:string;subtitle:string;actions?:ReactNode}) {return <div className="head-row"><div><div className="eyebrow">RESOLVEAI / MERCHANT OPERATIONS</div><h1 className="heading">{title}</h1><p className="subtitle" style={{margin:0}}>{subtitle}</p></div><div className="actions">{actions}</div></div>}
export function roleLabel(role:string, production=false):string {
  if (!production) return role;
  return ({
    customer: "Customer",
    support_agent: "Support agent",
    refund_approver: "Refund approver",
    merchant_admin: "Merchant admin",
  } as Record<string,string>)[role] ?? role.replaceAll("_", " ");
}
export function conversationStateLabel(state:string, production=false):string {
  if (!production) return state;
  return ({
    AI_ACTIVE: "AI support active",
    HANDOFF_QUEUED: "Waiting for support",
    HUMAN_ACTIVE: "Support handling",
    RESOLVED: "Resolved",
  } as Record<string,string>)[state] ?? state.replaceAll("_", " ");
}
export function refundStateLabel(state:string, production=false):string {
  if (!production) return state;
  return ({
    PENDING_REVIEW: "Pending review",
    APPROVED_EXTERNAL_ACTION_REQUIRED: "Approved — action required",
    REJECTED: "Declined",
  } as Record<string,string>)[state] ?? state.replaceAll("_", " ");
}
export function policyStatusLabel(status:string, production=false):string {
  if (!production) return status;
  return ({
    draft: "Draft",
    indexing: "Preparing",
    testable: "Ready to test",
    published: "Published",
    failed: "Needs attention",
  } as Record<string,string>)[status] ?? status.replaceAll("_", " ");
}
export function messageAuthorLabel(authorType:string, production=false):string {
  if (!production) return authorType;
  return ({customer: "You", assistant: "ResolveAI", staff: "Support"} as Record<string,string>)[authorType] ?? authorType;
}
export function DesignShell({surface,navigate,children,actor,handoffs,pending,allowed,production}:{surface:Surface;navigate:(s:Surface)=>void;children:ReactNode;actor?:string;handoffs?:number;pending?:number;allowed?:Surface[];production?:boolean}) {
  const [mobile,setMobile]=useState(false);
  const title=groups.flatMap(([,items])=>[...items]).find(([id])=>id===surface)?.[1] ?? "Overview";
  return <div className={`app-shell ${production ? "production" : "demo"}`}><div className={`overlay-mobile ${mobile?'show':''}`} onClick={()=>setMobile(false)}/><aside className={`sidebar ${mobile?'open':''}`}><div className="brand"><img className="shell-brand" src="/branding/resolveai-logo-dark.svg" alt="ResolveAI"/><div className="namestack brandsub">CUSTOMER OPERATIONS</div></div><div className="workspace-pill" aria-label="Current workspace"><div className="ws-icon" aria-hidden="true"><Icon name="store" size={17}/></div><div className="ws-meta"><b>ShopEase Workspace</b><span>{production ? "Merchant workspace" : "Synthetic merchant · local pilot"}</span></div><Icon name="chevron" size={14}/></div><nav aria-label="Application surfaces">{groups.map(([group,items])=><div key={group}><div className="navlabel">{group}</div>{items.filter(([id])=>!allowed||allowed.includes(id)).map(([id,label,ico])=><button key={id} className={`navbtn ${surface===id?'current':''}`} aria-current={surface===id?'page':undefined} title={label} onClick={()=>{navigate(id);setMobile(false)}}><Icon name={ico} size={18}/><span className="navtext">{label}</span>{id==='support'&&handoffs!==undefined&&handoffs>0?<span className="count">{handoffs}</span>:id==='refunds'&&pending!==undefined&&pending>0?<span className="count">{pending}</span>:null}</button>)}</div>)}</nav><div className="sidebar-bottom"><div className="pill-sidebar"><Icon name="shield" size={16}/> {production ? "Review-only refunds" : "Read-only commerce pilot"}</div><div className="mini">{production ? "Role-based access. Refund approvals never move money from this console." : "Local synthetic data. Refund approvals never move money from this console."}</div></div></aside><main className="main"><div className="topbar"><div className="crumb"><button className="btn sm square mobile-menu-btn" aria-label="Open navigation" aria-expanded={mobile} onClick={()=>setMobile(!mobile)}><Icon name="menu"/></button><span>Workspace</span><Icon name="chevron" size={12}/><b>{title}</b></div><div className="top-right"><span className="demo-chip">{production?"SIGNED IN":"LOCAL SYNTHETIC DEMO"}</span><span className="session-role">{actor??'Not signed in'}</span>{(!allowed||allowed.includes("widget-preview"))&&<button className="btn sm square" title="Preview customer widget" aria-label="Preview customer widget" onClick={()=>navigate('widget-preview')}><Icon name="chat"/></button>}<div className="avatar" aria-label={actor??'No session'}>{actor?.slice(0,2).toUpperCase()??'RA'}</div></div></div><div className="content">{children}</div></main></div>
}
