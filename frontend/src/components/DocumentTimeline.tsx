import { useEffect, useState } from "react";
import { api, type ActivityItem, errorMessage } from "../api";
import Icon from "../ui/Icon";

const KIND: Record<string,string> = {created:"success",updated:"info",submitted:"success",cancelled:"danger",deleted:"danger",workflow:"purple",approval:"success",login:"muted",admin:"warning",automation:"purple",integration:"info",comment:"warning"};
const LABEL: Record<string,string> = {created:"Created",updated:"Updated",submitted:"Submitted",cancelled:"Cancelled",deleted:"Deleted",workflow:"Workflow",approval:"Approved",login:"Sign-in",admin:"Administration",automation:"Automation",integration:"Integration",comment:"Comment"};
export default function DocumentTimeline({doctype,name,defaultCollapsed=true}:{doctype:string;name:string;defaultCollapsed?:boolean}) {
  const [open,setOpen]=useState(!defaultCollapsed),[items,setItems]=useState<ActivityItem[]>([]),[error,setError]=useState(""),[loading,setLoading]=useState(false);
  useEffect(()=>{if(!open)return;let live=true;setLoading(true);api.documentActivity(doctype,name,{limit:50}).then(r=>{if(live)setItems(r.items||[])}).catch(e=>{if(live)setError(errorMessage(e))}).finally(()=>{if(live)setLoading(false)});return()=>{live=false}},[doctype,name,open]);
  return <section className={`document-timeline ${open?"is-open":"is-collapsed"}`}>
    <button type="button" className="document-timeline-head" aria-expanded={open} onClick={()=>setOpen(v=>!v)}>
      <span className="timeline-heading-icon"><Icon name="activity"/></span><span className="timeline-heading-copy"><b>Activity & Audit Timeline</b><small>Document history, changes, approvals and system events</small></span><span className="timeline-count">{items.length} events</span><Icon name={open?"up":"down"}/>
    </button>
    {open&&<div className="document-timeline-body">{loading?<div className="muted">Loading document history…</div>:error?<div className="error">{error}</div>:items.length===0?<div className="timeline-empty">No recorded activity yet. Events will appear here as this document is used.</div>:<ol className="document-timeline-list">{items.map((item)=><li key={item.id} className={`timeline-event tone-${KIND[item.event_type]||"muted"}`}><span className="timeline-dot"/><div className="timeline-event-card"><div className="timeline-event-top"><span className={`timeline-event-kind tone-label-${KIND[item.event_type]||"muted"}`}>{LABEL[item.event_type]||item.event_type}</span><time>{new Date(item.at).toLocaleString()}</time></div><b>{item.title}</b>{item.summary&&<p>{item.summary}</p>}{item.changed_fields?.length>0&&<small>Fields: {item.changed_fields.join(", ")}</small>}<div className="timeline-event-by">{item.actor} · {item.source}</div></div></li>)}</ol>}</div>}
  </section>;
}
