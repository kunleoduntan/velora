import { useCallback, useEffect, useMemo, useState } from "react";
import { api, getProfile, getSession } from "../api";
import type { Doc } from "../types";

type Row = Record<string, any>;
const today = () => new Date().toISOString().slice(0, 10);
const statusTone = (s: string) => /published|accepted|closed|complete/i.test(s) ? "success" : /reject|overdue|failed/i.test(s) ? "danger" : "warning";

export default function HRGovernanceCentre() {
  const [tab, setTab] = useState<"handovers"|"policies"|"acknowledgements">("handovers");
  const [handovers, setHandovers] = useState<Row[]>([]);
  const [policies, setPolicies] = useState<Row[]>([]);
  const [acks, setAcks] = useState<Row[]>([]);
  const [employees, setEmployees] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [handover, setHandover] = useState({employee:"", handover_type:"Leave", source_doctype:"Leave Application", source_reference:"", start_date:today(), end_date:"", receiving_employee:"", handover_owner:"", handover_notes:""});
  const [policy, setPolicy] = useState({policy_code:"", policy_title:"", policy_category:"Employment", policy_owner:"", department:"", policy_status:"Draft", confidentiality:"Internal", review_cycle_months:"12", next_review_date:"", acknowledgement_required:true});
  const [version, setVersion] = useState({version_number:"1.0", version_title:"Initial version", version_content:"", change_summary:"Initial issue", effective_from:today(), effective_to:"", version_status:"Draft", attachment:""});
  const [selectedPolicy, setSelectedPolicy] = useState("");
  const [selectedHandover, setSelectedHandover] = useState("");
  const [item, setItem] = useState({task:"", description:"", category:"Responsibilities", assigned_to:"", due_date:"", handover_status:"Pending", evidence_reference:""});

  const load = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const [h,p,a,e] = await Promise.all([
        api.list("Handover Management",{limit:1000,order_by:"modified desc"}),
        api.list("HR Policy Document",{limit:1000,order_by:"modified desc"}),
        api.list("HR Policy Acknowledgement",{limit:1000,order_by:"modified desc"}),
        api.list("Employee",{limit:5000,filters:[["disabled","=",0]],fields:["name","employee_name","department"]})
      ]);
      setHandovers(h as Row[]); setPolicies(p as Row[]); setAcks(a as Row[]); setEmployees(e as Row[]);
      if (!selectedPolicy && p.length) setSelectedPolicy(String(p[0].name));
      if (!selectedHandover && h.length) setSelectedHandover(String(h[0].name));
    } catch (e:any) { setError(e?.message || "Unable to load HR governance records."); }
    finally { setBusy(false); }
  }, [selectedPolicy, selectedHandover]);

  useEffect(() => { void load(); }, [load]);
  const employeeName = (id:string) => employees.find(x=>x.name===id)?.employee_name || id || "—";
  const visibleHandovers = useMemo(() => handovers.filter(x => [x.name,x.employee,x.receiving_employee,x.handover_type,x.handover_status].join(" ").toLowerCase().includes(search.toLowerCase())),[handovers,search]);
  const visiblePolicies = useMemo(() => policies.filter(x => [x.name,x.policy_code,x.policy_title,x.policy_status,x.policy_category].join(" ").toLowerCase().includes(search.toLowerCase())),[policies,search]);
  const selected = handovers.find(x=>x.name===selectedHandover);
  const selectedPolicyDoc = policies.find(x=>x.name===selectedPolicy);
  const notify = (s:string) => { setMessage(s); setError(""); };

  async function createHandover(e:React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const created = await api.create("Handover Management", {...handover, handover_status:"Draft", outstanding_count:0, handover_items:[]} as Doc);
      setSelectedHandover(String(created.name)); setHandover({...handover,source_reference:"",handover_notes:""}); notify("Handover created. Add tasks and submit it for recipient review."); await load();
    } catch(e:any) { setError(e?.message || "Unable to create handover."); } finally { setBusy(false); }
  }
  async function addItem(e:React.FormEvent) {
    e.preventDefault(); if(!selected) return; setBusy(true);
    try {
      const rows = [...(selected.handover_items || []), item];
      await api.update("Handover Management", selected.name, {...selected, handover_items:rows, outstanding_count:rows.filter((x:Row)=>x.handover_status!=="Accepted").length} as Doc);
      setItem({task:"",description:"",category:"Responsibilities",assigned_to:"",due_date:"",handover_status:"Pending",evidence_reference:""}); notify("Handover item added."); await load();
    } catch(e:any) { setError(e?.message || "Unable to add handover item."); } finally { setBusy(false); }
  }
  async function setHandoverStatus(status:string) {
    if(!selected) return;
    if(status==="Accepted" && (selected.handover_items||[]).some((x:Row)=>x.handover_status!=="Accepted")) { setError("Every handover item must be accepted before the overall handover can be accepted."); return; }
    setBusy(true);
    try {
      await api.update("Handover Management",selected.name,{...selected,handover_status:status,submitted_on:status==="Submitted"?new Date().toISOString():selected.submitted_on,accepted_on:status==="Accepted"?new Date().toISOString():selected.accepted_on} as Doc);
      notify(`Handover marked ${status}.`); await load();
    } catch(e:any) { setError(e?.message || "Unable to update handover."); } finally { setBusy(false); }
  }
  async function createPolicy(e:React.FormEvent) {
    e.preventDefault(); setBusy(true);
    try {
      const created=await api.create("HR Policy Document",{...policy,current_version:"",versions:[]} as Doc);
      setSelectedPolicy(String(created.name)); setPolicy({policy_code:"",policy_title:"",policy_category:"Employment",policy_owner:"",department:"",policy_status:"Draft",confidentiality:"Internal",review_cycle_months:"12",next_review_date:"",acknowledgement_required:true});
      notify("Policy register entry created. Add its first controlled version."); await load();
    } catch(e:any) { setError(e?.message || "Unable to create policy."); } finally { setBusy(false); }
  }
  async function addVersion(e:React.FormEvent) {
    e.preventDefault(); if(!selectedPolicyDoc) return; setBusy(true);
    try {
      const versions=[...(selectedPolicyDoc.versions||[]),{...version,version_status:"Draft"}];
      await api.update("HR Policy Document",selectedPolicyDoc.name,{...selectedPolicyDoc,versions} as Doc);
      setVersion({version_number:"",version_title:"",version_content:"",change_summary:"",effective_from:today(),effective_to:"",version_status:"Draft",attachment:""});
      notify("New draft version added. It is not yet approved or published."); await load();
    } catch(e:any) { setError(e?.message || "Unable to add policy version."); } finally { setBusy(false); }
  }
  async function approvePolicy() {
    if(!selectedPolicyDoc) return; const versions=[...(selectedPolicyDoc.versions||[])];
    if(!versions.length) { setError("Add a policy version before approval."); return; }
    const i=versions.length-1; if(versions[i].version_status!=="Draft" && versions[i].version_status!=="In Review") { setError("Only a draft or in-review version can be approved."); return; }
    versions[i]={...versions[i],version_status:"Approved",approved_by:getSession()?.user || getProfile()?.user.email || "Authenticated HR Approver",approved_on:new Date().toISOString()}; setBusy(true);
    try { await api.update("HR Policy Document",selectedPolicyDoc.name,{...selectedPolicyDoc,versions,policy_status:"Approved"} as Doc); notify("Latest policy version approved. It can now be published."); await load(); }
    catch(e:any) { setError(e?.message || "Unable to approve policy."); } finally { setBusy(false); }
  }
  async function issueAcknowledgements() {
    if(!selectedPolicyDoc || !selectedPolicyDoc.acknowledgement_required || !selectedPolicyDoc.current_version) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const current = String(selectedPolicyDoc.current_version);
      const existing = await api.list("HR Policy Acknowledgement",{filters:[["policy_document","=",selectedPolicyDoc.name],["policy_version","=",current]],fields:["employee","policy_version"]});
      const done = new Set(existing.map((x:any)=>String(x.employee)));
      const targets = employees.filter((e:any)=>!selectedPolicyDoc.department || e.department===selectedPolicyDoc.department).filter((e:any)=>!done.has(String(e.name)));
      const due = new Date(); due.setDate(due.getDate()+14);
      for(const employee of targets) {
        await api.create("HR Policy Acknowledgement",{policy_document:selectedPolicyDoc.name,policy_version:current,employee:employee.name,assigned_on:new Date().toISOString(),due_date:due.toISOString().slice(0,10),acknowledgement_status:"Pending",acknowledgement_method:"Employee Portal"} as Doc);
      }
      notify(`${targets.length} acknowledgement request(s) issued; existing requests were skipped.`);
      await load();
    } catch(e:any) { setError(e?.message || "Unable to issue policy acknowledgements."); }
    finally { setBusy(false); }
  }
  async function publishPolicy() {
    if(!selectedPolicyDoc) return; const versions=[...(selectedPolicyDoc.versions||[])];
    if(!versions.length) { setError("Add a policy version before publishing."); return; }
    const latest=versions[versions.length-1];
    if(!latest.version_content || !latest.effective_from) { setError("The latest version requires content and an effective date."); return; }
    if(latest.version_status!=="Approved") { setError("Only an approved version can be published."); return; }
    versions[versions.length-1]={...latest,version_status:"Published",approved_by:latest.approved_by || getSession()?.user || getProfile()?.user.email || "Authenticated HR Approver",published_on:new Date().toISOString()};
    setBusy(true);
    try {
      await api.update("HR Policy Document",selectedPolicyDoc.name,{...selectedPolicyDoc,versions,current_version:latest.version_number,policy_status:"Published"} as Doc);
      notify(`Policy version ${latest.version_number} published.`); await load();
    } catch(e:any) { setError(e?.message || "Unable to publish policy."); } finally { setBusy(false); }
  }
  const employeeOptions = employees.map(x=><option key={x.name} value={x.name}>{x.employee_name || x.name}</option>);
  return <main className="hr-governance-centre">
    <header className="page-header"><div><h1>HR Governance Centre</h1><p className="muted">Manage employee handovers, controlled HR policies and acknowledgement compliance.</p></div><button className="btn" onClick={()=>void load()} disabled={busy}>Refresh</button></header>
    {error && <div className="panel error" role="alert">{error}</div>}{message && <div className="panel success" role="status">{message}</div>}
    <nav className="tabs"><button className={tab==="handovers"?"active":""} onClick={()=>setTab("handovers")}>Handover Management <span>{handovers.length}</span></button><button className={tab==="policies"?"active":""} onClick={()=>setTab("policies")}>Policy Library <span>{policies.length}</span></button><button className={tab==="acknowledgements"?"active":""} onClick={()=>setTab("acknowledgements")}>Acknowledgements <span>{acks.length}</span></button></nav>
    <div className="toolbar"><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search records..." /><span className="muted">{busy?"Loading…":`${tab==="handovers"?visibleHandovers.length:tab==="policies"?visiblePolicies.length:acks.length} records`}</span></div>
    {tab==="handovers" && <div className="hr-governance-grid">
      <section className="panel"><h2>Create handover</h2><form className="form-grid" onSubmit={createHandover}>
        <label>Employee<select required value={handover.employee} onChange={e=>setHandover({...handover,employee:e.target.value})}><option value="">Select employee</option>{employeeOptions}</select></label>
        <label>Handover type<select value={handover.handover_type} onChange={e=>setHandover({...handover,handover_type:e.target.value,source_doctype:e.target.value==="Leave"?"Leave Application":"Employee Separation"})}><option>Leave</option><option>Separation</option></select></label>
        <label>Source reference<input required value={handover.source_reference} onChange={e=>setHandover({...handover,source_reference:e.target.value})} placeholder="Leave or separation reference"/></label>
        <label>Receiving employee<select required value={handover.receiving_employee} onChange={e=>setHandover({...handover,receiving_employee:e.target.value})}><option value="">Select recipient</option>{employeeOptions}</select></label>
        <label>Handover owner<select value={handover.handover_owner} onChange={e=>setHandover({...handover,handover_owner:e.target.value})}><option value="">Select owner</option>{employeeOptions}</select></label>
        <label>Start date<input type="date" value={handover.start_date} onChange={e=>setHandover({...handover,start_date:e.target.value})}/></label>
        <label>End / return date<input type="date" value={handover.end_date} onChange={e=>setHandover({...handover,end_date:e.target.value})}/></label>
        <label className="span-2">Handover notes<textarea value={handover.handover_notes} onChange={e=>setHandover({...handover,handover_notes:e.target.value})}/></label>
        <button className="btn primary" disabled={busy}>Create handover</button>
      </form></section>
      <section className="panel"><h2>Handover register</h2><div className="record-list">{visibleHandovers.map(x=><button key={x.name} className={`record-row ${selectedHandover===x.name?"selected":""}`} onClick={()=>setSelectedHandover(x.name)}><span><b>{x.name}</b><small>{employeeName(x.employee)} · {x.handover_type} · To {employeeName(x.receiving_employee)}</small></span><em className={`status-${statusTone(x.handover_status||"Draft")}`}>{x.handover_status||"Draft"}</em></button>)}</div></section>
      <section className="panel span-2">{selected?<><div className="section-heading"><div><h2>{selected.name}</h2><p>{employeeName(selected.employee)} → {employeeName(selected.receiving_employee)} · {selected.handover_type}</p></div><div className="actions"><button className="btn" disabled={busy||selected.handover_status!=="Draft"} onClick={()=>void setHandoverStatus("Submitted")}>Submit for acceptance</button><button className="btn primary" disabled={busy||selected.handover_status!=="Submitted"} onClick={()=>void setHandoverStatus("Accepted")}>Accept handover</button></div></div><div className="record-list">{(selected.handover_items||[]).map((x:Row,i:number)=><div className="record-row" key={i}><span><b>{x.task}</b><small>{x.description} · Owner: {employeeName(x.assigned_to)} · Due: {x.due_date||"—"}</small></span><span className="actions"><em className={`status-${statusTone(x.handover_status||"Pending")}`}>{x.handover_status||"Pending"}</em><button type="button" className="btn small" disabled={busy||selected.handover_status!=="Submitted"||x.handover_status==="Accepted"} onClick={async()=>{const rows=[...(selected.handover_items||[])];rows[i]={...rows[i],handover_status:"Accepted",completed_on:new Date().toISOString()};try{await api.update("Handover Management",selected.name,{...selected,handover_items:rows,outstanding_count:rows.filter((z:Row)=>z.handover_status!=="Accepted").length} as Doc);notify("Handover task accepted.");await load();}catch(err:any){setError(err?.message||"Unable to accept task.");}}}>Accept task</button></span></div>)}</div><form className="form-grid compact" onSubmit={addItem}><h3 className="span-2">Add handover task</h3><label>Task<input required value={item.task} onChange={e=>setItem({...item,task:e.target.value})}/></label><label>Category<select value={item.category} onChange={e=>setItem({...item,category:e.target.value})}><option>Responsibilities</option><option>Open Transactions</option><option>Projects</option><option>Customers</option><option>Suppliers</option><option>Systems Access</option><option>Assets</option><option>Documents</option><option>Other</option></select></label><label>Assigned to<select value={item.assigned_to} onChange={e=>setItem({...item,assigned_to:e.target.value})}><option value="">Select owner</option>{employeeOptions}</select></label><label>Due date<input type="date" value={item.due_date} onChange={e=>setItem({...item,due_date:e.target.value})}/></label><label className="span-2">Description<textarea value={item.description} onChange={e=>setItem({...item,description:e.target.value})}/></label><button className="btn" disabled={busy||selected.handover_status!=="Draft"}>Add task</button></form></>:<p className="muted">Select a handover to review its tasks.</p>}</section>
    </div>}
    {tab==="policies" && <div className="hr-governance-grid">
      <section className="panel"><h2>Register policy</h2><form className="form-grid" onSubmit={createPolicy}>
        <label>Policy code<input required value={policy.policy_code} onChange={e=>setPolicy({...policy,policy_code:e.target.value})}/></label><label>Policy title<input required value={policy.policy_title} onChange={e=>setPolicy({...policy,policy_title:e.target.value})}/></label>
        <label>Category<select value={policy.policy_category} onChange={e=>setPolicy({...policy,policy_category:e.target.value})}><option>Employment</option><option>Leave</option><option>Attendance</option><option>Compensation</option><option>Conduct</option><option>Disciplinary</option><option>Health and Safety</option><option>Information Security</option><option>Data Protection</option><option>Learning and Development</option><option>Benefits</option><option>Separation</option><option>Other</option></select></label>
        <label>Policy owner<select value={policy.policy_owner} onChange={e=>setPolicy({...policy,policy_owner:e.target.value})}><option value="">Select owner</option>{employeeOptions}</select></label>
        <label>Department<input value={policy.department} onChange={e=>setPolicy({...policy,department:e.target.value})}/></label><label>Review cycle (months)<input type="number" min="1" value={policy.review_cycle_months} onChange={e=>setPolicy({...policy,review_cycle_months:e.target.value})}/></label>
        <label>Next review date<input type="date" value={policy.next_review_date} onChange={e=>setPolicy({...policy,next_review_date:e.target.value})}/></label><label>Confidentiality<select value={policy.confidentiality} onChange={e=>setPolicy({...policy,confidentiality:e.target.value})}><option>All Employees</option><option>Managers</option><option>HR Only</option><option>Restricted</option></select></label>
        <label className="check-field"><input type="checkbox" checked={policy.acknowledgement_required} onChange={e=>setPolicy({...policy,acknowledgement_required:e.target.checked})}/> Employee acknowledgement required</label><button className="btn primary" disabled={busy}>Create policy</button>
      </form></section>
      <section className="panel"><h2>Policy register</h2><div className="record-list">{visiblePolicies.map(x=><button key={x.name} className={`record-row ${selectedPolicy===x.name?"selected":""}`} onClick={()=>setSelectedPolicy(x.name)}><span><b>{x.policy_code} · {x.policy_title}</b><small>{x.policy_category} · Current version {x.current_version||"Not issued"}</small></span><em className={`status-${statusTone(x.policy_status||"Draft")}`}>{x.policy_status||"Draft"}</em></button>)}</div></section>
      <section className="panel span-2">{selectedPolicyDoc?<><div className="section-heading"><div><h2>{selectedPolicyDoc.policy_title}</h2><p>{selectedPolicyDoc.policy_code} · {selectedPolicyDoc.policy_status} · Current version {selectedPolicyDoc.current_version||"—"}</p></div><div className="actions"><button className="btn" disabled={busy||!(selectedPolicyDoc.versions||[]).length} onClick={()=>void approvePolicy()}>Approve latest version</button><button className="btn primary" disabled={busy||!(selectedPolicyDoc.versions||[]).length} onClick={()=>void publishPolicy()}>Publish approved version</button><button className="btn" disabled={busy||selectedPolicyDoc.policy_status!=="Published"||!selectedPolicyDoc.acknowledgement_required} onClick={()=>void issueAcknowledgements()}>Issue acknowledgements</button></div></div><h3>Version history</h3><div className="record-list">{(selectedPolicyDoc.versions||[]).map((v:Row,i:number)=><div className="record-row" key={i}><span><b>Version {v.version_number} · {v.version_title}</b><small>{v.change_summary} · Effective {v.effective_from||"Not set"}</small></span><em className={`status-${statusTone(v.version_status||"Draft")}`}>{v.version_status||"Draft"}</em></div>)}</div><form className="form-grid compact" onSubmit={addVersion}><h3 className="span-2">Add a new version</h3><label>Version number<input required value={version.version_number} onChange={e=>setVersion({...version,version_number:e.target.value})}/></label><label>Version title<input required value={version.version_title} onChange={e=>setVersion({...version,version_title:e.target.value})}/></label><label>Effective from<input required type="date" value={version.effective_from} onChange={e=>setVersion({...version,effective_from:e.target.value})}/></label><label>Effective to<input type="date" value={version.effective_to} onChange={e=>setVersion({...version,effective_to:e.target.value})}/></label><label className="span-2">Policy content<textarea required rows={8} value={version.version_content} onChange={e=>setVersion({...version,version_content:e.target.value})}/></label><label className="span-2">Change summary<textarea value={version.change_summary} onChange={e=>setVersion({...version,change_summary:e.target.value})}/></label><button className="btn" disabled={busy}>Save draft version</button></form></>:<p className="muted">Select a policy to inspect its version history.</p>}</section>
    </div>}
    {tab==="acknowledgements" && <section className="panel"><h2>Policy acknowledgement register</h2><p className="muted">Acknowledgement records are linked to the exact policy version. Employee acknowledgement must not be inferred from publication.</p><div className="table-wrap"><table><thead><tr><th>Employee</th><th>Policy</th><th>Version</th><th>Assigned</th><th>Due</th><th>Status</th><th>Acknowledged</th></tr></thead><tbody>{acks.map(a=><tr key={a.name}><td>{employeeName(a.employee)}</td><td>{policies.find(p=>p.name===a.policy_document)?.policy_title||a.policy_document}</td><td>{a.policy_version}</td><td>{a.assigned_on||"—"}</td><td>{a.due_date||"—"}</td><td><em className={`status-${statusTone(a.acknowledgement_status||"Pending")}`}>{a.acknowledgement_status||"Pending"}</em></td><td>{a.acknowledged_on||"—"}</td></tr>)}</tbody></table></div></section>}
  </main>;
}
