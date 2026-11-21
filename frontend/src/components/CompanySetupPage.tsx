import { useEffect, useState } from "react";
import { raw, errorMessage } from "../api";

type Check = {code:string; title:string; category:string; status:"complete"|"attention"|"incomplete"; severity:"blocking"|"warning"; detail:string};
type Result = {status:string;score:number;completed:number;total:number;blocking_issues:number;warnings:number;checks:Check[]};

export default function CompanySetupPage(){
  const [data,setData]=useState<Result|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);setError("");try{const response=await raw("GET","/api/company/setup-readiness");const body=await response.json();if(!response.ok)throw new Error(body.message||"Could not load company setup readiness");setData(body.data);}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  useEffect(()=>{load();},[]);
  const groups=[...new Set((data?.checks||[]).map(x=>x.category))];
  return <div className="panel"><div className="page-head"><div><h1>Company Setup Readiness</h1><p className="muted">A company-specific control checklist for the foundational configuration required before live operations.</p></div><button className="rbtn" onClick={load} disabled={busy}>{busy?"Checking…":"Refresh assessment"}</button></div>
    {error&&<div className="error" role="alert">{error}</div>}
    {data&&<><section className="admin-card"><div className="object-studio-heading"><div><h2>{data.status==="ready"?"Core setup complete":"Configuration requires attention"}</h2><p className="muted">{data.completed} of {data.total} checks complete · {data.blocking_issues} blocking issue(s) · {data.warnings} warning(s)</p></div><strong className="dashboard-number">{data.score}%</strong></div><div className="kpi-track"><i style={{width:`${data.score}%`}}/></div></section>
    {groups.map(group=><section className="admin-card" key={group}><h2>{group}</h2><div className="table-wrap"><table><thead><tr><th>Control</th><th>Status</th><th>Priority</th><th>Action / Result</th></tr></thead><tbody>{data.checks.filter(x=>x.category===group).map(item=><tr key={item.code}><td><b>{item.title}</b><div className="muted">{item.code}</div></td><td><span className={`status-pill ${item.status!=="complete"?"warning":""}`}>{item.status.replace("_"," ")}</span></td><td>{item.severity}</td><td>{item.detail}</td></tr>)}</tbody></table></div></section>)}
    <p className="muted">This assessment checks company records currently available to VeloraERP. It does not certify tax compliance, opening-balance accuracy, account mapping correctness or production readiness.</p></>}
  </div>;
}
