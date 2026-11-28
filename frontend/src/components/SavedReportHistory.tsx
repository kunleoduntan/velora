import { askConfirm, askPrompt, askAlert } from "../ui/ask";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

export default function SavedReportHistory({id,canEdit,onRestored}:{id:string;canEdit:boolean;onRestored:()=>void}) {
 const [rows,setRows]=useState<any[]>([]),[error,setError]=useState(""),[busy,setBusy]=useState(false),[detail,setDetail]=useState<any>(null),[notice,setNotice]=useState("");
 async function load(){setError("");try{setRows(await api.savedReportVersions(id));}catch(e){setError(errorMessage(e));}}
 useEffect(()=>{void load();},[id]);
 async function restore(version:number){if(!await askConfirm(`Restore saved report version ${version}? This creates a new revision.`))return;setBusy(true);setError("");setNotice("");try{await api.restoreSavedReportVersion(id,version);setNotice(`Revision ${version} restored as a new version.`);await load();onRestored();}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
 return <section className="section"><div className="builder-body"><div className="object-studio-heading"><div><h3>Report version history</h3><p className="muted">Immutable report-definition revisions. Restoring a revision publishes it as a new version.</p></div><button className="rbtn" onClick={()=>void load()}>Refresh</button></div>
 {error&&<div className="error" role="alert">{error}</div>}{notice&&<div className="success" role="status">{notice}</div>}
 <div className="table-wrap"><table className="dgrid"><thead><tr><th>Version</th><th>Name</th><th>Author</th><th>Created</th><th>Action</th></tr></thead><tbody>
 {rows.map((r,i)=><tr key={r.id}><td><b>v{r.version}</b>{i===0&&<span className="status-pill">Latest</span>}</td><td>{r.name}</td><td>{r.author||"—"}</td><td>{r.created_on?new Date(r.created_on).toLocaleString():"—"}</td><td><button className="rbtn" onClick={()=>setDetail(detail?.id===r.id?null:r)}>Inspect</button>{canEdit&&i!==0&&<button className="rbtn" disabled={busy} onClick={()=>void restore(r.version)}>Restore</button>}</td></tr>)}
 {!rows.length&&<tr><td colSpan={5} className="muted">No saved revisions yet.</td></tr>}
 </tbody></table></div>{detail&&<div className="extension-card"><h4>Revision {detail.version}</h4><pre>{JSON.stringify(detail.spec,null,2)}</pre></div>}
 </div></section>;
}
