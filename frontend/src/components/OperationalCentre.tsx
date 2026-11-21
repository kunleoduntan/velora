import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api";

type Centre = {summary:Record<string,number>;approvals:any[];tasks:any[];exceptions:any[];workflow:any;read_only:boolean};
export default function OperationalCentre(){
 const [data,setData]=useState<Centre|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false),[tab,setTab]=useState("Approvals");
 const load=useCallback(async()=>{setBusy(true);setError("");try{setData(await api.operationalCentre());}catch(e){setError(errorMessage(e));}finally{setBusy(false);}},[]);
 useEffect(()=>{void load();},[load]);
 async function complete(id:string){setBusy(true);try{await api.completeWorkflowTask(id);await load();}catch(e){setError(errorMessage(e));setBusy(false);}}
 const s=data?.summary||{};
 return <main className="operational-centre">
  <header className="page-head"><div><h1>Operational Centre</h1><p className="muted">One place to review approvals, assigned work and cross-functional exceptions. All business records remain controlled by their owning modules.</p></div><button className="rbtn" onClick={()=>void load()} disabled={busy}>Refresh</button></header>
  {error&&<div className="panel error" role="alert">{error}</div>}
  <div className="application-kpi-grid">
   {[['Approvals',s.approvals??0],['Assigned tasks',s.assigned_tasks??0],['Draft / pending records',s.draft_and_pending??0],['Overdue workflows',s.overdue_workflows??0]].map(([label,value])=><section className="application-kpi-card" key={String(label)}><small>{label}</small><strong>{value===null?'—':Number(value).toLocaleString()}</strong></section>)}
  </div>
  <nav className="tabs"><button className={tab==='Approvals'?'active':''} onClick={()=>setTab('Approvals')}>Approval inbox ({data?.approvals.length??0})</button><button className={tab==='Tasks'?'active':''} onClick={()=>setTab('Tasks')}>My tasks ({data?.tasks.length??0})</button><button className={tab==='Exceptions'?'active':''} onClick={()=>setTab('Exceptions')}>Exceptions ({data?.exceptions.filter(x=>x.count>0).length??0})</button><button className={tab==='Workflow'?'active':''} onClick={()=>setTab('Workflow')}>Workflow health</button></nav>
  {!data&&busy&&<section className="panel">Loading operational information…</section>}
  {data&&tab==='Approvals'&&<section className="panel"><h2>My approval inbox</h2>{data.approvals.length?data.approvals.map((x:any)=><div className="workflow-row" key={`${x.id}-${x.action}-${x.step||''}`}><div><b>{x.label||x.action}</b><small>{x.doctype} · {x.document_name} · {x.state}</small></div><a className="rbtn primary" href={x.route}>Open record</a></div>):<p className="muted">No pending approvals assigned to you.</p>}</section>}
  {data&&tab==='Tasks'&&<section className="panel"><h2>My assigned tasks</h2>{data.tasks.length?data.tasks.map((x:any)=><div className="workflow-row" key={x.id}><div><b>{x.title}</b><small>{x.description||'Workflow task'} · Due {x.due_on?new Date(x.due_on).toLocaleDateString():'Not set'}</small></div><button className="rbtn" disabled={busy} onClick={()=>void complete(x.id)}>Mark complete</button></div>):<p className="muted">No open tasks assigned to you.</p>}</section>}
  {data&&tab==='Exceptions'&&<section className="panel"><h2>Business exceptions and work queues</h2><div className="table-wrap"><table><thead><tr><th>Area</th><th>Queue</th><th>Outstanding</th><th>Action</th></tr></thead><tbody>{data.exceptions.map((x:any)=><tr key={x.doctype}><td>{x.area}</td><td>{x.label}</td><td><b>{Number(x.count).toLocaleString()}</b></td><td><a href={x.route}>Open register</a></td></tr>)}</tbody></table></div><p className="muted">Queues are included only when the DocType and its read permission are available. A zero means no matching records were found; unavailable queues are omitted.</p></section>}
  {data&&tab==='Workflow'&&<section className="panel"><h2>Workflow health</h2><div className="application-kpi-grid">{data.workflow?<><div className="application-kpi-card"><small>Active workflows</small><strong>{data.workflow.active_instances??0}</strong></div><div className="application-kpi-card"><small>Overdue workflow SLAs</small><strong>{data.workflow.overdue_active_instances??0}</strong></div><div className="application-kpi-card"><small>Completed in last 90 days</small><strong>{data.workflow.completed_last_90_days??0}</strong></div><div className="application-kpi-card"><small>Average completion hours</small><strong>{data.workflow.average_completion_hours_90_days??'—'}</strong></div></>:<p className="muted">Company-wide workflow analytics are restricted to management roles.</p>}</div><a className="rbtn" href="#/settings/workflows">Workflow administration</a></section>}
  <p className="muted">Read-only command centre: approvals, posting, payroll processing, settlement and other business actions must be completed in their authorised workflows.</p>
 </main>;
}
