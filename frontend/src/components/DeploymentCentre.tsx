import { askConfirm, askPrompt, askAlert } from "../ui/ask";
import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api";

type Profile = {name:string;source:string;target:string;apps:string[]};
export default function DeploymentCentre() {
  const [profiles,setProfiles]=useState<Profile[]>([]);
  const [name,setName]=useState(""); const [source,setSource]=useState(""); const [target,setTarget]=useState("");
  const [apps,setApps]=useState(""); const [selected,setSelected]=useState("");
  const [plan,setPlan]=useState<any>(null); const [result,setResult]=useState<any>(null);
  const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  const refresh=useCallback(async()=>{try{setProfiles(await api.deploymentProfiles());setError("");}catch(e){setError(errorMessage(e));}},[]);
  useEffect(()=>{void refresh();},[refresh]);
  async function create(){setBusy(true);setError("");try{const row=await api.createDeploymentProfile({name,source,target,apps:apps.split(",").map(x=>x.trim()).filter(Boolean)});setSelected(row.name);setName("");setApps("");await refresh();setPlan(null);setResult(null);}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  async function inspect(){if(!selected)return;setBusy(true);setError("");try{setPlan(await api.deploymentPlan(selected));setResult(null);}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  async function promote(dry:boolean){if(!selected)return;if(!dry&&!await askConfirm("LIVE DEPLOYMENT: application source and database schemas on the target workspace may change. A backup is attempted first. Continue?"))return;setBusy(true);setError("");try{setResult(await api.promoteDeployment(selected,dry,!dry));if(!dry)await inspect();}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  return <section className="section"><div className="builder-body">
    <div className="object-studio-heading"><div><h3>Production Deployment Centre</h3><p className="muted">Define source-to-target releases, inspect package compatibility, rehearse a dry run and promote only after approval.</p></div><button className="rbtn" onClick={()=>void refresh()} disabled={busy}>Refresh</button></div>
    {error&&<div className="error" role="alert">{error}</div>}
    <div className="extension-card"><h4>Create deployment profile</h4><div className="creator-opts">
      <div className="field"><label>Profile name</label><input value={name} onChange={e=>setName(e.target.value)} placeholder="production_release"/></div>
      <div className="field"><label>Source workspace path</label><input value={source} onChange={e=>setSource(e.target.value)} placeholder="/srv/velora-dev"/></div>
      <div className="field"><label>Target workspace path</label><input value={target} onChange={e=>setTarget(e.target.value)} placeholder="/srv/velora-production"/></div>
      <div className="field"><label>Applications (comma separated)</label><input value={apps} onChange={e=>setApps(e.target.value)} placeholder="accounts, inventory"/></div>
    </div><button className="rbtn primary" disabled={busy||!name||!source||!target||!apps.trim()} onClick={()=>void create()}>Create profile</button></div>
    <div className="field"><label>Deployment profile</label><select value={selected} onChange={e=>{setSelected(e.target.value);setPlan(null);setResult(null);}}><option value="">Select profile</option>{profiles.map(p=><option key={p.name} value={p.name}>{p.name} · {p.source} → {p.target}</option>)}</select></div>
    <div className="toolbar"><button className="rbtn" disabled={busy||!selected} onClick={()=>void inspect()}>Build release plan</button><button className="rbtn" disabled={busy||!selected} onClick={()=>void promote(true)}>Run dry run</button><button className="rbtn primary" disabled={busy||!selected||!plan} onClick={()=>void promote(false)}>Approve & promote</button></div>
    {plan&&<div className="extension-card"><h4>Release plan · {plan.profile}</h4><p className="muted">{plan.source} → {plan.target} · {plan.target_count} target(s)</p><table className="dgrid"><thead><tr><th>Application</th><th>Version</th><th>Files</th><th>Package digest</th><th>Validation</th></tr></thead><tbody>{plan.packages?.map((p:any)=><tr key={p.name}><td>{p.name}</td><td>{p.version}</td><td>{p.file_count}</td><td><code>{p.sha256?.slice(0,20)}…</code></td><td>{p.valid?"Valid":"Invalid"}</td></tr>)}</tbody></table><h4>Targets</h4><ul>{plan.targets?.map((t:any)=><li key={t.id}>{t.label}</li>)}</ul><p className="muted">Preflight validates packages and dependencies. A live promotion should first be rehearsed against a staging copy; database restore and application rollback depend on the configured database backup/restore facilities.</p></div>}
    {result&&<div className={result.status==="dry_run"?"success":"panel"} role="status"><strong>{result.status==="dry_run"?"Dry run complete":(result.status==="success"?"Promotion successful":`Promotion ${result.status}`)}</strong><pre>{JSON.stringify(result,null,2)}</pre></div>}
    {!profiles.length&&<p className="muted">No deployment profiles yet. Create a profile to begin controlled promotion.</p>}
  </div></section>;
}
