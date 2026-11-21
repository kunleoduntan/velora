import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

export default function WorkflowGovernancePanel({workflows}:{workflows:any[]}) {
  const [selected,setSelected]=useState("");
  const [versions,setVersions]=useState<any[]>([]);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState("");
  const [detail,setDetail]=useState<any>(null);
  useEffect(()=>{if(!selected&&workflows.length)setSelected(workflows[0].name);},[workflows,selected]);
  async function load(){if(!selected)return;setBusy(true);setError("");try{setVersions(await api.workflowVersions(selected));}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  useEffect(()=>{void load();},[selected]);
  async function restore(v:number){if(!window.confirm(`Restore workflow version ${v}? This publishes its definition as a NEW version. Running instances keep their original frozen version.`))return;setBusy(true);setError("");setNotice("");try{await api.restoreWorkflowVersion(selected,v);setNotice(`Version ${v} restored as a new current version.`);await load();}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  const current=versions[0];
  return <section className="admin-card"><div className="object-studio-heading"><div><h2>Workflow governance & version history</h2><p className="muted">Review immutable workflow revisions and publish a previous definition as a new version. Running workflows retain their frozen definition.</p></div><button className="rbtn" onClick={()=>void load()} disabled={busy||!selected}>Refresh</button></div>
    <label>Workflow definition</label><select value={selected} onChange={e=>{setSelected(e.target.value);setDetail(null);}}><option value="">Select workflow</option>{workflows.map(w=><option key={w.name} value={w.name}>{w.name}</option>)}</select>
    {error&&<div className="error" role="alert">{error}</div>}{notice&&<div className="success" role="status">{notice}</div>}
    {selected&&<><p className="muted">{versions.length} recorded version(s) · Current version {current?.version??"not available"}</p>
      <div className="table-wrap"><table className="dgrid"><thead><tr><th>Version</th><th>Created by</th><th>Created on</th><th>Definition</th><th>Action</th></tr></thead><tbody>
      {versions.map(v=><tr key={v.id}><td><strong>v{v.version}</strong>{v.version===current?.version&&<span className="status-pill">Current</span>}</td><td>{v.created_by||"—"}</td><td>{v.created_on?new Date(v.created_on).toLocaleString():"—"}</td><td><button className="rbtn" onClick={()=>setDetail(detail?.id===v.id?null:v)}> {detail?.id===v.id?"Hide":"Inspect"} </button></td><td><button className="rbtn" disabled={busy||v.version===current?.version} onClick={()=>void restore(v.version)}>Publish as current</button></td></tr>)}
      {!versions.length&&<tr><td colSpan={5} className="muted">No version history found. Save the workflow definition to create its first version.</td></tr>}
      </tbody></table></div>
      {detail&&<div className="extension-card"><h3>Workflow version {detail.version} definition</h3><pre>{JSON.stringify(detail.definition,null,2)}</pre></div>}
    </>}
  </section>;
}
