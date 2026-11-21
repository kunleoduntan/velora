import { useEffect, useState } from "react";
import { api, errorMessage, type ActivityItem, type AuditCase, type AuditCaseNote } from "../api";

type Scope = "company" | "mine";
const EVENTS = ["","created","updated","submitted","cancelled","deleted","workflow","approval","admin","automation","integration","login","comment"];
export default function ActivityCentre(){
  const [items,setItems]=useState<ActivityItem[]>([]),[error,setError]=useState(""),[loading,setLoading]=useState(true);
  const [scope,setScope]=useState<Scope>("company"),[eventType,setEventType]=useState(""),[doctype,setDoctype]=useState("");
  const [actor,setActor]=useState(""),[search,setSearch]=useState(""),[from,setFrom]=useState(""),[to,setTo]=useState("");
  const [tab,setTab]=useState<"events"|"cases">("events"),[cases,setCases]=useState<AuditCase[]>([]);
  const [caseTitle,setCaseTitle]=useState(""),[caseDescription,setCaseDescription]=useState(""),[casePriority,setCasePriority]=useState("Normal");
  const [selected,setSelected]=useState<{case:AuditCase;notes:AuditCaseNote[]}|null>(null),[caseNote,setCaseNote]=useState("");
  const [caseStatus,setCaseStatus]=useState("Open"),[caseError,setCaseError]=useState("");
  async function load(){
    try{setError("");const r=await api.activity({limit:200,scope,event_type:eventType||undefined,doctype:doctype||undefined,actor:actor||undefined,search:search||undefined,from_date:from||undefined,to_date:to||undefined});setItems(r.items);}
    catch(e){setError(errorMessage(e));}finally{setLoading(false);}
  }
  async function loadCases(){try{setCaseError("");const r=await api.auditCases({limit:100});setCases(r.items);}catch(e){setCaseError(errorMessage(e));}}
  useEffect(()=>{setLoading(true);void load();const timer=window.setInterval(()=>void load(),30000);return()=>window.clearInterval(timer);},[scope,eventType,doctype,actor,search,from,to]);
  useEffect(()=>{if(tab==="cases")void loadCases();},[tab]);
  async function exportCsv(){
    try{const r=await api.exportActivity({scope,event_type:eventType||undefined,doctype:doctype||undefined,actor:actor||undefined,search:search||undefined,from_date:from||undefined,to_date:to||undefined});
      const url=URL.createObjectURL(new Blob([r.content],{type:"text/csv;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download=r.filename;a.click();URL.revokeObjectURL(url);}
    catch(e){setError(errorMessage(e));}
  }
  async function openCase(id:string){try{const r=await api.getAuditCase(id);setSelected(r);setCaseStatus(r.case.status);}catch(e){setCaseError(errorMessage(e));}}
  async function createCase(){
    try{const r=await api.createAuditCase({title:caseTitle,description:caseDescription,priority:casePriority});setCaseTitle("");setCaseDescription("");await loadCases();await openCase(r.id);}
    catch(e){setCaseError(errorMessage(e));}
  }
  async function saveCase(){
    if(!selected)return;
    try{const r=await api.updateAuditCase(selected.case.id,{status:caseStatus,note:caseNote||undefined});setSelected(r);setCaseNote("");await loadCases();}
    catch(e){setCaseError(errorMessage(e));}
  }
  return <div className="panel">
    <div className="page-head"><div><h1>Audit Investigation & Compliance Centre</h1><p className="muted">Search the tenant-local audit ledger, export evidence and manage documented investigations.</p></div></div>
    <div className="ribbon">
      <button className={`rbtn${tab==="events"?" primary":""}`} onClick={()=>setTab("events")}>Audit events</button>
      <button className={`rbtn${tab==="cases"?" primary":""}`} onClick={()=>setTab("cases")}>Investigation cases</button>
    </div>
    {tab==="events"?<>
      <section className="section"><div className="builder-body">
        <div className="form-grid">
          <div className="field"><label>Activity scope</label><select value={scope} onChange={e=>setScope(e.target.value as Scope)}><option value="company">Company</option><option value="mine">My activity</option></select></div>
          <div className="field"><label>Event type</label><select value={eventType} onChange={e=>setEventType(e.target.value)}>{EVENTS.map(x=><option key={x} value={x}>{x||"All event types"}</option>)}</select></div>
          <div className="field"><label>DocType</label><input value={doctype} onChange={e=>setDoctype(e.target.value)} placeholder="e.g. Payment"/></div>
          <div className="field"><label>Actor</label><input value={actor} onChange={e=>setActor(e.target.value)} placeholder="User ID"/></div>
          <div className="field"><label>Search text</label><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Title, document or summary"/></div>
          <div className="field"><label>From date</label><input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></div>
          <div className="field"><label>To date</label><input type="date" value={to} onChange={e=>setTo(e.target.value)}/></div>
        </div>
        <button className="rbtn" onClick={()=>void load()}>Refresh</button> <button className="rbtn primary" onClick={()=>void exportCsv()}>Export CSV</button>
      </div></section>
      {error&&<div className="error" role="alert">{error}</div>}
      {loading?<p className="muted">Loading audit events…</p>:items.length===0?<div className="empty-state"><h3>No matching audit events</h3><p className="muted">Change the filters or wait for new activity.</p></div>:
      <div className="activity-list">{items.map(x=><article className="activity-entry" key={x.id}>
        <div className="activity-entry-head"><strong>{x.title}</strong><time>{new Date(x.at).toLocaleString()}</time></div>
        <p className="muted">{x.actor} · {x.event_type}{x.doctype?` · ${x.doctype}${x.document_name?` / ${x.document_name}`:""}`:""}</p>
        {x.summary&&<p>{x.summary}</p>}{x.changed_fields?.length>0&&<small className="muted">Changed fields: {x.changed_fields.join(", ")}</small>}
      </article>)}</div>}
      <p className="muted">Showing up to 200 matching events. Export is capped at 200 rows per request. Event history is read-only.</p>
    </>:<>
      {caseError&&<div className="error" role="alert">{caseError}</div>}
      <section className="section"><div className="builder-body"><h3>Open an investigation</h3>
        <div className="field"><label>Case title</label><input value={caseTitle} onChange={e=>setCaseTitle(e.target.value)} maxLength={240}/></div>
        <div className="field"><label>Description</label><textarea rows={3} value={caseDescription} onChange={e=>setCaseDescription(e.target.value)}/></div>
        <div className="field"><label>Priority</label><select value={casePriority} onChange={e=>setCasePriority(e.target.value)}>{["Low","Normal","High","Critical"].map(x=><option key={x}>{x}</option>)}</select></div>
        <button className="rbtn primary" disabled={!caseTitle.trim()} onClick={()=>void createCase()}>Create investigation</button>
      </div></section>
      <div className="activity-list">{cases.map(c=><article className="activity-entry" key={c.id}>
        <div className="activity-entry-head"><strong>{c.title}</strong><span>{c.status} · {c.priority}</span></div>
        <p className="muted">Owner: {c.owner}{c.assigned_to?` · Assigned: ${c.assigned_to}`:""} · {new Date(c.created_on).toLocaleString()}</p>
        {c.description&&<p>{c.description}</p>}<button className="rbtn" onClick={()=>void openCase(c.id)}>Open case</button>
      </article>)}</div>
      {selected&&<section className="section"><div className="builder-body"><h3>{selected.case.title}</h3>
        <p className="muted">Case reference: {selected.case.id}</p>
        <div className="field"><label>Status</label><select value={caseStatus} onChange={e=>setCaseStatus(e.target.value)}>{["Open","In Review","On Hold","Closed"].map(x=><option key={x}>{x}</option>)}</select></div>
        <div className="field"><label>Investigation note</label><textarea rows={3} value={caseNote} onChange={e=>setCaseNote(e.target.value)} placeholder="Record findings, evidence references or next steps"/></div>
        <button className="rbtn primary" onClick={()=>void saveCase()}>Save status and note</button>
        <h4>Case history</h4>{selected.notes.map(n=><article className="activity-entry" key={n.id}><p>{n.body}</p><small className="muted">{n.actor} · {new Date(n.created_on).toLocaleString()}</small></article>)}
      </div></section>}
    </>}
  </div>;
}
