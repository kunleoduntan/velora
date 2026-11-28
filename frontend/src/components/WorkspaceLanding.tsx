import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import DashboardChart from "./DashboardChart";
export default function WorkspaceLanding(){
 const [workspace,setWorkspace]=useState<any>(null),[error,setError]=useState("");
 useEffect(()=>{let live=true;api.landingWorkspace().then(x=>{if(live)setWorkspace(x);}).catch(e=>{if(live)setError(errorMessage(e));});return()=>{live=false;};},[]);
 if(error)return <div className="panel"><div className="error" role="alert">{error}</div><p className="muted">Open the Application Workspace Designer to review your landing page. New here? Read the <a href="#/welcome">welcome guide</a>.</p><a href="#/workspaces" className="rbtn">Workspace Designer</a></div>;
 if(!workspace)return <div className="panel"><h1>Welcome to Velora</h1><p className="muted">Your application workspace is ready to be configured. New here? Read the <a href="#/welcome">welcome guide</a>.</p><a href="#/workspaces" className="rbtn primary">Design your workspace</a></div>;
 return <div className="panel"><div className="page-head"><div><h1>{workspace.name}</h1><p className="muted">{workspace.description||"Your application workspace"}</p></div><a href="#/workspaces" className="rbtn">Edit workspace</a></div>
  <div className="dashboard-widgets workspace-landing-grid">{(workspace.results||[]).map((w:any,i:number)=><div className="dashboard-widget" key={i} style={{gridColumn:`span ${Math.max(1,Math.min(4,w.width||2))}`}}>
   <h3>{w.title}</h3>{w.type==="shortcut"?<><p className="muted">{w.description}</p><a className="rbtn primary" href={w.route}>Open</a></>:w.type==="activity"?<div className="workspace-activity">{(w.value||[]).length?(w.value||[]).map((a:any)=><div className="workspace-activity-item" key={a.id}><strong>{a.title}</strong><small className="muted">{a.actor} · {new Date(a.at).toLocaleString()}</small>{a.doctype&&<small className="muted">{a.doctype}{a.document_name?` / ${a.document_name}`:""}</small>}</div>):<p className="muted">No activity has been recorded yet.</p>}<a href="#/activity" className="link">Open Activity Centre</a></div>:w.type==="number"?(w.status==="unavailable"?<p className="muted">Not available to your role</p>:<strong className="dashboard-number">{Number(w.value).toLocaleString()}</strong>):w.type==="aggregate"?Object.entries(w.value||{}).map(([k,v])=><p key={k}>{k}: <b>{String(v??"—")}</b></p>):<DashboardChart data={(w.value||[]).map((r:any)=>({value:r.value,count:r.count,label:r.label}))} kind="bar"/>}
  </div>)}</div>
 </div>;
}
