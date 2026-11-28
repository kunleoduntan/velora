import { askConfirm, askPrompt, askAlert } from "../ui/ask";
import { useEffect, useState } from "react";
import { api, downloadBlob, errorMessage } from "../api";

type Attachment = { id:string; file_name:string; content_type:string; size:number; uploaded_by:string; created_on:string; description?:string };

export default function AttachmentPanel({doctype,name,canWrite}:{doctype:string;name:string;canWrite:boolean}) {
  const [items,setItems]=useState<Attachment[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [description,setDescription]=useState("");
  async function load(){ try { setItems(await api.files(doctype,name)); } catch(e){setError(errorMessage(e));} }
  useEffect(()=>{void load();},[doctype,name]);
  async function upload(file?:File){
    if(!file)return;
    setBusy(true);setError("");
    try { await api.uploadAttachment(doctype,name,file,description);setDescription("");await load(); }
    catch(e){setError(errorMessage(e));}
    finally{setBusy(false);}
  }
  async function download(item:Attachment){
    try { const result=await api.downloadAttachment(item.id);downloadBlob(result.blob,result.filename||item.file_name); }
    catch(e){setError(errorMessage(e));}
  }
  async function remove(item:Attachment){
    if(!await askConfirm(`Delete attachment ${item.file_name}?`))return;
    setBusy(true);setError("");
    try{await api.deleteAttachment(item.id);await load();}
    catch(e){setError(errorMessage(e));}
    finally{setBusy(false);}
  }
  const size=(n:number)=>n<1024?`${n} B`:n<1048576?`${(n/1024).toFixed(1)} KB`:`${(n/1048576).toFixed(1)} MB`;
  const [over,setOver]=useState(false);
  function drop(e:React.DragEvent){ e.preventDefault(); setOver(false); const f=e.dataTransfer.files?.[0]; if(f&&canWrite&&!busy)void upload(f); }
  return <section className="section attachment-panel">
    <div className="section-head"><span>Attachments</span><span className="muted">{items.length ? `${items.length} file(s)` : "None yet"}</span></div>
    {error&&<div className="error" role="alert">{error}</div>}
    {items.length>0&&<div className="attachment-list">
      {items.map(item=><div className="attachment-row" key={item.id}>
        <span className="attachment-icon" aria-hidden="true">📎</span>
        <div className="attachment-meta"><b>{item.file_name}</b><small className="muted"> · {size(item.size)} · {item.uploaded_by}</small>{item.description&&<div className="muted">{item.description}</div>}</div>
        <div className="attachment-actions"><button type="button" className="rbtn" onClick={()=>void download(item)}>Download</button>
          {canWrite&&<button type="button" className="rbtn danger" disabled={busy} onClick={()=>void remove(item)}>Remove</button>}</div>
      </div>)}
    </div>}
    {canWrite&&<div className={`attachment-drop${over?" over":""}`} onDragOver={e=>{e.preventDefault();setOver(true);}} onDragLeave={()=>setOver(false)} onDrop={drop}>
      <label className="attachment-pick"><span className="rbtn">＋ Add file</span>
        <input aria-label="Choose attachment" type="file" hidden disabled={busy} onChange={e=>{const f=e.target.files?.[0];void upload(f);e.currentTarget.value="";}}/></label>
      <span className="muted">or drop a file here · up to 25 MB · stored privately in this company</span>
      <input aria-label="Attachment description" placeholder="Description (optional)" value={description} onChange={e=>setDescription(e.target.value)}/>
    </div>}
  </section>;
}
