import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Doc } from "../types";

type Row = Record<string, any>;
type Preview = { policy:string; policy_name:string; policy_version:number; leave_period:string; period_start:string; period_end:string; eligible_employee_count:number; allocation_count:number; skipped_count:number; rows:Row[] };
const today = () => { const d=new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; };
const fmt = (v:any) => Number(v || 0).toLocaleString(undefined,{maximumFractionDigits:2});
async function listAll(doctype:string,options:Record<string,any>={}){const rows:Doc[]=[];let offset=0;while(true){const batch=await api.list(doctype,{...options,limit:1000,offset});rows.push(...batch);if(batch.length<1000)break;offset+=batch.length;if(offset>=50000)throw new Error(`${doctype} contains more than 50,000 matching records. Narrow the reporting period or filters before loading the Leave Management Centre.`);}return rows;}

export default function LeaveManagementCentre({canSubmit}:{canSubmit:boolean}) {
  const [tab,setTab] = useState("Overview");
  const [policies,setPolicies] = useState<Row[]>([]);
  const [periods,setPeriods] = useState<Row[]>([]);
  const [employees,setEmployees] = useState<Row[]>([]);
  const [allocations,setAllocations] = useState<Row[]>([]);
  const [applications,setApplications] = useState<Row[]>([]);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [message,setMessage] = useState("");
  const [policy,setPolicy] = useState("");
  const [period,setPeriod] = useState("");
  const [assignmentDate,setAssignmentDate] = useState(today());
  const [selectionMode,setSelectionMode] = useState("All Eligible Employees");
  const [selectedEmployees,setSelectedEmployees] = useState<string[]>([]);
  const [preview,setPreview] = useState<Preview|null>(null);
  const [compareA,setCompareA] = useState("");
  const [compareB,setCompareB] = useState("");
  const [policyDocs,setPolicyDocs] = useState<Record<string,Row>>({});
  const [search,setSearch] = useState("");
  const [calendarMonth,setCalendarMonth] = useState(()=>new Date(new Date().getFullYear(),new Date().getMonth(),1));

  const load = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const [p,lp,e,a,la] = await Promise.all([
        listAll("Leave Policy",{fields:["name","policy_code","policy_name","policy_version","effective_from","effective_to","status"],order_by:"policy_name asc"}),
        listAll("Leave Period",{fields:["name","period_name","from_date","to_date","period_status"],order_by:"from_date desc"}),
        listAll("Employee",{filters:[["disabled","=",0]],fields:["name","employee_code","employee_name","department","designation","branch","disabled"],order_by:"employee_name asc"}),
        listAll("Leave Allocation",{filters:[["allocation_status","=","Approved"]],fields:["name","employee","leave_type","period_start","period_end","allocated_days","carry_forward_days","adjustment_days","used_days","pending_days","available_days","allocation_status","leave_policy"],order_by:"period_end desc"}),
        listAll("Leave Application",{filters:[["workflow_status","in",["Pending Approval","Approved","Completed"]]],fields:["name","employee","leave_type","from_date","to_date","total_days","workflow_status","reason","leave_allocation"],order_by:"from_date asc"}),
      ]);
      setPolicies(p); setPeriods(lp); setEmployees(e.filter(x=>!x.disabled)); setAllocations(a); setApplications(la);
      if(!policy && p.length) setPolicy(String(p.find(x=>x.status==="Active")?.name || p[0].name));
      if(!period && lp.length) setPeriod(String(lp.find(x=>x.period_status==="Open")?.name || lp[0].name));
    } catch(e:any) { setError(e?.message || "Unable to load Leave Management data."); }
    finally { setBusy(false); }
  },[policy,period]);
  useEffect(()=>{void load();},[load]);

  const selectedPeriod = periods.find(x=>x.name===period);
  const scopedAllocations = allocations.filter(x=>x.allocation_status==="Approved" && (!selectedPeriod || (String(x.period_start)<=String(selectedPeriod.to_date) && String(x.period_end)>=String(selectedPeriod.from_date))));
  const activeAllocations = scopedAllocations.map((a:Row):Row=>{const related=applications.filter(l=>l.leave_allocation===a.name);const used=related.filter(l=>l.workflow_status==="Completed").reduce((n,l)=>n+Number(l.total_days||0),0);const pending=related.filter(l=>["Pending Approval","Approved"].includes(l.workflow_status)).reduce((n,l)=>n+Number(l.total_days||0),0);const entitled=Number(a.allocated_days||0)+Number(a.carry_forward_days||0)+Number(a.adjustment_days||0);return {...a,used_days:used,pending_days:pending,available_days:entitled-used-pending};});
  const totalEntitled = activeAllocations.reduce((n,x)=>n+Number(x.allocated_days||0)+Number(x.carry_forward_days||0)+Number(x.adjustment_days||0),0);
  const totalUsed = activeAllocations.reduce((n,x)=>n+Number(x.used_days||0),0);
  const totalPending = activeAllocations.reduce((n,x)=>n+Number(x.pending_days||0),0);
  const totalAvailable = activeAllocations.reduce((n,x)=>n+Number(x.available_days ?? (Number(x.allocated_days||0)+Number(x.carry_forward_days||0)+Number(x.adjustment_days||0)-Number(x.used_days||0)-Number(x.pending_days||0))),0);
  const upcoming = applications.filter(x=>x.workflow_status==="Approved" && String(x.to_date)>=today()).slice(0,100);
  const balanceByType = useMemo(()=>{
    const map = new Map<string,{entitled:number;used:number;pending:number;available:number;employees:Set<string>}>();
    for(const a of activeAllocations){const k=String(a.leave_type||"Unspecified");const v=map.get(k)||{entitled:0,used:0,pending:0,available:0,employees:new Set<string>()};v.entitled+=Number(a.allocated_days||0)+Number(a.carry_forward_days||0)+Number(a.adjustment_days||0);v.used+=Number(a.used_days||0);v.pending+=Number(a.pending_days||0);v.available+=Number(a.available_days??0);v.employees.add(String(a.employee));map.set(k,v);}
    return [...map.entries()].map(([leave_type,v])=>({leave_type,...v,employees:v.employees.size})).sort((a,b)=>a.leave_type.localeCompare(b.leave_type));
  },[activeAllocations]);
  const filteredBalances = activeAllocations.filter(x=>!search || `${x.employee} ${x.leave_type}`.toLowerCase().includes(search.toLowerCase()));

  async function runPreview(){setBusy(true);setError("");setMessage("");setPreview(null);try{
    const result=await api.hrLeavePolicyPreview({policy,leave_period:period,assignment_date:assignmentDate,selection_mode:selectionMode,selected_employees:selectedEmployees.map(employee=>({employee}))});
    setPreview(result);
  }catch(e:any){setError(e?.message||"Could not preview policy eligibility.");}finally{setBusy(false);}}

  async function createAssignment(){if(!preview)return;setBusy(true);setError("");setMessage("");try{
    const created=await api.create("Leave Policy Assignment",{policy,assignment_date:assignmentDate,leave_period:period,selection_mode:selectionMode,selected_employees:selectedEmployees.map(employee=>({employee})),preview_employee_count:preview.eligible_employee_count} as Doc);
    await api.action("Leave Policy Assignment",String(created.name),"submit");
    setMessage(`Assignment ${created.name} submitted. ${preview.allocation_count} allocations were expected from the preview.`);setPreview(null);await load();
  }catch(e:any){setError(e?.message||"Assignment could not be submitted.");}finally{setBusy(false);}}

  async function clonePolicy(name:string){setBusy(true);setError("");setMessage("");try{
    const source=await api.get("Leave Policy",name) as Row;const nextVersion=Number(source.policy_version||1)+1;
    const clean=(v:any):any=>Array.isArray(v)?v.map(clean):v&&typeof v==="object"?Object.fromEntries(Object.entries(v).filter(([k])=>!['name','parent','parenttype','parentfield','creation','modified','owner','modified_by','docstatus','idx'].includes(k)).map(([k,x])=>[k,clean(x)])):v;
    const copy=clean(source);delete copy.name;delete copy.modified;
    copy.policy_code=`${source.policy_code}-V${nextVersion}`;copy.policy_version=nextVersion;copy.status="Draft";copy.effective_from=today();copy.effective_to=null;
    const made=await api.create("Leave Policy",copy as Doc);setMessage(`Draft policy version created: ${made.name}. Review and activate it when ready.`);await load();
  }catch(e:any){setError(e?.message||"Policy version could not be cloned.");}finally{setBusy(false);}}

  async function loadCompare(){const names=[compareA,compareB].filter(Boolean);if(names.length!==2)return;setBusy(true);try{const docs=await Promise.all(names.map(n=>api.get("Leave Policy",n)));setPolicyDocs({[names[0]]:docs[0] as Row,[names[1]]:docs[1] as Row});}catch(e:any){setError(e?.message||"Could not load policies for comparison.");}finally{setBusy(false);}}

  const tabs=["Overview","Policy Designer","Eligibility Preview","Leave Balances","Team Calendar","Reports"];
  return <div className="leave-centre">
    <div className="leave-head"><div><div className="eyebrow">HR & PEOPLE</div><h1>Leave Management Centre</h1><p>Manage leave policies, eligibility, employee entitlements and workforce absence from one place.</p></div><div className="leave-head-actions"><button className="secondary" onClick={()=>void load()} disabled={busy}>Refresh</button><a className="primary" href="#/app/Leave Policy">New Leave Policy</a></div></div>
    {error&&<div className="leave-alert error" role="alert">{error}</div>}{message&&<div className="leave-alert success" role="status">{message}</div>}
    <nav className="leave-tabs">{tabs.map(t=><button key={t} className={tab===t?"active":""} onClick={()=>setTab(t)}>{t}</button>)}</nav>
    {tab==="Overview"&&<>
      <div className="leave-kpis"><Kpi label="Employees with approved allocations" value={new Set(activeAllocations.map(x=>x.employee)).size}/><Kpi label="Total entitlement (days)" value={fmt(totalEntitled)}/><Kpi label="Days used" value={fmt(totalUsed)}/><Kpi label="Days pending" value={fmt(totalPending)}/><Kpi label="Available leave (days)" value={fmt(totalAvailable)}/></div>
      <div className="leave-columns"><section className="leave-card"><h2>Leave balances by type</h2><BalanceTable rows={balanceByType}/></section><section className="leave-card"><h2>Policy administration</h2><p className="muted">Configure policies with multiple leave types, eligibility groups, proration and carry-forward rules.</p><a className="primary" href="#/app/Leave Policy">Open Policy Designer</a><a href="#/app/Leave Policy Assignment">View Policy Assignments</a><a href="#/app/Leave Allocation">View Employee Allocations</a></section></div>
      <section className="leave-card"><h2>Upcoming approved leave</h2><ApplicationTable rows={upcoming.slice(0,10)}/></section>
    </>}
    {tab==="Policy Designer"&&<>
      <div className="leave-card"><div className="leave-section-head"><div><h2>Leave policy library</h2><p className="muted">Each policy can contain multiple leave entitlements and effective-dated eligibility rules.</p></div><a className="primary" href="#/app/Leave Policy">Create policy</a></div>
        <div className="leave-table-wrap"><table><thead><tr><th>Policy</th><th>Version</th><th>Effective</th><th>Status</th><th>Actions</th></tr></thead><tbody>{policies.map(p=><tr key={p.name}><td><strong>{p.policy_name}</strong><small>{p.policy_code}</small></td><td>v{p.policy_version}</td><td>{p.effective_from} – {p.effective_to||"Open ended"}</td><td><span className={`leave-status ${String(p.status).toLowerCase()}`}>{p.status}</span></td><td className="leave-actions"><a href={`#/app/Leave Policy/${encodeURIComponent(p.name)}`}>Open</a><button onClick={()=>void clonePolicy(p.name)} disabled={busy}>Clone version</button></td></tr>)}</tbody></table></div>
      </div>
      <div className="leave-card"><h2>Compare two policies</h2><div className="leave-form-row"><select value={compareA} onChange={e=>setCompareA(e.target.value)}><option value="">Select first policy</option>{policies.map(p=><option key={p.name} value={p.name}>{p.policy_name} · v{p.policy_version}</option>)}</select><select value={compareB} onChange={e=>setCompareB(e.target.value)}><option value="">Select second policy</option>{policies.map(p=><option key={p.name} value={p.name}>{p.policy_name} · v{p.policy_version}</option>)}</select><button className="primary" onClick={()=>void loadCompare()} disabled={!compareA||!compareB||compareA===compareB||busy}>Compare</button></div>
        {Object.keys(policyDocs).length===2&&<PolicyComparison a={policyDocs[compareA]} b={policyDocs[compareB]}/>}
      </div>
    </>}
    {tab==="Eligibility Preview"&&<>
      <section className="leave-card"><h2>Preview policy eligibility</h2><p className="muted">Review every employee and every entitlement before creating an assignment. This preview does not create or modify allocations.</p>
        <div className="leave-form-grid"><label>Leave Policy<select value={policy} onChange={e=>{setPolicy(e.target.value);setPreview(null);}}><option value="">Select policy</option>{policies.filter(p=>p.status==="Active").map(p=><option key={p.name} value={p.name}>{p.policy_name} · v{p.policy_version}</option>)}</select></label><label>Leave Period<select value={period} onChange={e=>{setPeriod(e.target.value);setPreview(null);}}><option value="">Select period</option>{periods.filter(p=>p.period_status==="Open").map(p=><option key={p.name} value={p.name}>{p.period_name||p.name} ({p.from_date} to {p.to_date})</option>)}</select></label><label>Assignment Date<input type="date" value={assignmentDate} onChange={e=>{setAssignmentDate(e.target.value);setPreview(null);}}/></label><label>Employee Selection<select value={selectionMode} onChange={e=>{setSelectionMode(e.target.value);setPreview(null);}}><option>All Eligible Employees</option><option>Selected Employees</option></select></label></div>
        {selectionMode==="Selected Employees"&&<label className="leave-multi">Selected employees <select multiple value={selectedEmployees} onChange={e=>setSelectedEmployees((Array.from(e.target.selectedOptions) as HTMLOptionElement[]).map(o=>o.value))}>{employees.map(e=><option key={e.name} value={e.name}>{e.employee_name||e.name} · {e.department||"No department"}</option>)}</select><small>Use Ctrl or Command to select multiple employees.</small></label>}
        <button className="primary" onClick={()=>void runPreview()} disabled={busy||!policy||!period||!assignmentDate||(selectionMode==="Selected Employees"&&!selectedEmployees.length)}>{busy?"Working…":"Preview eligible employees"}</button>
      </section>
      {preview&&<section className="leave-card"><div className="leave-kpis compact"><Kpi label="Eligible employees" value={preview.eligible_employee_count}/><Kpi label="Allocations to create" value={preview.allocation_count}/><Kpi label="Skipped" value={preview.skipped_count}/></div><div className="leave-section-head"><h2>Employee-level preview</h2>{canSubmit?<button className="primary" onClick={()=>void createAssignment()} disabled={busy||preview.allocation_count===0}>Confirm and create allocations</button>:<span className="muted">Preview only · HR Manager approval required to create allocations</span>}</div><div className="leave-table-wrap"><table><thead><tr><th>Employee</th><th>Department</th><th>Designation</th><th>Leave Type</th><th>Days</th><th>Result</th></tr></thead><tbody>{preview.rows.map((r,i)=><tr key={`${r.employee}-${r.leave_type}-${i}`}><td>{r.employee_name}<small>{r.employee}</small></td><td>{r.department||"—"}</td><td>{r.designation||"—"}</td><td>{r.leave_type}</td><td>{fmt(r.entitlement_days)}</td><td><span className={`leave-status ${r.result==="Will Create"?"active":"retired"}`}>{r.result}</span></td></tr>)}</tbody></table></div></section>}
    </>}
    {tab==="Leave Balances"&&<section className="leave-card"><div className="leave-section-head"><div><h2>Employee leave balances</h2><p className="muted">Approved allocation balances for the selected leave period.</p></div><select value={period} onChange={e=>setPeriod(e.target.value)}>{periods.map(p=><option key={p.name} value={p.name}>{p.period_name||p.name}</option>)}</select></div><input className="leave-search" placeholder="Search employee or leave type" value={search} onChange={e=>setSearch(e.target.value)}/><div className="leave-table-wrap"><table><thead><tr><th>Employee</th><th>Leave Type</th><th>Period</th><th>Entitled</th><th>Used</th><th>Pending</th><th>Available</th><th>Status</th></tr></thead><tbody>{filteredBalances.map(x=><tr key={x.name}><td>{x.employee}</td><td>{x.leave_type}</td><td>{x.period_start} – {x.period_end}</td><td>{fmt(Number(x.allocated_days||0)+Number(x.carry_forward_days||0)+Number(x.adjustment_days||0))}</td><td>{fmt(x.used_days)}</td><td>{fmt(x.pending_days)}</td><td><strong>{fmt(x.available_days)}</strong></td><td>{x.allocation_status}</td></tr>)}</tbody></table></div></section>}
    {tab==="Team Calendar"&&<section className="leave-card"><div className="leave-section-head"><div><h2>Approved leave calendar</h2><p className="muted">Monthly view of approved absences across the accessible workforce.</p></div><a href="#/app/Leave Application">Leave applications</a></div><LeaveMonthCalendar rows={upcoming} month={calendarMonth} onMonth={setCalendarMonth}/></section>}
    {tab==="Reports"&&<>
      <div className="leave-kpis"><Kpi label="Leave entitlement" value={`${fmt(totalEntitled)} days`}/><Kpi label="Used" value={`${fmt(totalUsed)} days`}/><Kpi label="Pending reservations" value={`${fmt(totalPending)} days`}/><Kpi label="Outstanding balance" value={`${fmt(totalAvailable)} days`}/></div>
      <section className="leave-card"><h2>Leave utilisation by type</h2><div className="leave-table-wrap"><table><thead><tr><th>Leave Type</th><th>Employees</th><th>Entitled Days</th><th>Used Days</th><th>Pending Days</th><th>Outstanding Days</th><th>Utilisation</th></tr></thead><tbody>{balanceByType.map(x=><tr key={x.leave_type}><td>{x.leave_type}</td><td>{x.employees}</td><td>{fmt(x.entitled)}</td><td>{fmt(x.used)}</td><td>{fmt(x.pending)}</td><td>{fmt(x.available)}</td><td><div className="leave-progress"><span style={{width:`${Math.min(100,x.entitled?x.used/x.entitled*100:0)}%`}}/></div>{fmt(x.entitled?x.used/x.entitled*100:0)}%</td></tr>)}</tbody></table></div><p className="muted">Outstanding leave is reported in days. Monetary leave liability is intentionally excluded until the organisation configures and approves its valuation basis and accounting treatment.</p></section>
    </>}
    {busy&&<div className="leave-loading" role="status">Processing…</div>}
  </div>;
}
function LeaveMonthCalendar({rows,month,onMonth}:{rows:Row[];month:Date;onMonth:(d:Date)=>void}){
 const year=month.getFullYear(),m=month.getMonth(),first=new Date(year,m,1),last=new Date(year,m+1,0);
 const offset=(first.getDay()+6)%7,days=Array.from({length:offset+last.getDate()},(_,i)=>i-offset+1);
 const names=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
 const onDay=(day:number)=>`${year}-${String(m+1).padStart(2,"0")}-${String(day).padStart(2,"0")}`;
 return <div className="leave-calendar"><div className="leave-calendar-nav"><button onClick={()=>onMonth(new Date(year,m-1,1))}>← Previous</button><strong>{month.toLocaleDateString(undefined,{month:"long",year:"numeric"})}</strong><button onClick={()=>onMonth(new Date(year,m+1,1))}>Next →</button></div><div className="leave-calendar-grid">{names.map(n=><div className="leave-calendar-weekday" key={n}>{n}</div>)}{days.map((day,i)=>{const valid=day>0&&day<=last.getDate(),date=valid?onDay(day):"";const events=valid?rows.filter(r=>String(r.from_date)<=date&&String(r.to_date)>=date):[];return <div key={i} className={`leave-calendar-day ${valid?"":"outside"} ${date===today()?"today":""}`}><span className="leave-calendar-date">{valid?day:""}</span>{events.slice(0,3).map((r,j)=><div className="leave-calendar-event" key={`${r.name}-${j}`} title={`${r.employee} · ${r.leave_type}`}>{r.employee} · {r.leave_type}</div>)}{events.length>3&&<small>+{events.length-3} more</small>}</div>})}</div><p className="muted">Only approved leave applications are displayed. Draft, pending, rejected and cancelled requests are excluded.</p></div>;
}

function Kpi({label,value}:{label:string;value:any}){return <div className="leave-kpi"><span>{label}</span><strong>{value}</strong></div>}
function BalanceTable({rows}:{rows:Row[]}){return <div className="leave-table-wrap"><table><thead><tr><th>Leave Type</th><th>Employees</th><th>Entitled</th><th>Used</th><th>Pending</th><th>Available</th></tr></thead><tbody>{rows.map(r=><tr key={r.leave_type}><td>{r.leave_type}</td><td>{r.employees}</td><td>{fmt(r.entitled)}</td><td>{fmt(r.used)}</td><td>{fmt(r.pending)}</td><td><strong>{fmt(r.available)}</strong></td></tr>)}</tbody></table></div>}
function ApplicationTable({rows}:{rows:Row[]}){return <div className="leave-table-wrap"><table><thead><tr><th>Employee</th><th>Leave Type</th><th>From</th><th>To</th><th>Days</th><th>Status</th></tr></thead><tbody>{rows.length?rows.map(r=><tr key={r.name}><td>{r.employee}</td><td>{r.leave_type}</td><td>{r.from_date}</td><td>{r.to_date}</td><td>{fmt(r.total_days)}</td><td>{r.workflow_status}</td></tr>):<tr><td colSpan={6} className="muted">No approved leave found.</td></tr>}</tbody></table></div>}
function PolicyComparison({a,b}:{a:Row;b:Row}){const left=a.entitlements||[],right=b.entitlements||[];const names=[...new Set([...left.map((x:Row)=>x.leave_type),...right.map((x:Row)=>x.leave_type)])];const find=(rows:Row[],n:string)=>rows.find(x=>x.leave_type===n);return <div className="leave-table-wrap"><table><thead><tr><th>Entitlement</th><th>{a.policy_name} · v{a.policy_version}</th><th>{b.policy_name} · v{b.policy_version}</th><th>Difference</th></tr></thead><tbody>{names.map(n=>{const x=find(left,n),y=find(right,n),xd=Number(x?.annual_entitlement_days||0),yd=Number(y?.annual_entitlement_days||0);return <tr key={n}><td>{n}</td><td>{x?fmt(xd)+" days":"Not included"}</td><td>{y?fmt(yd)+" days":"Not included"}</td><td>{x&&y?`${yd-xd>0?"+":""}${fmt(yd-xd)} days`:"Added / Removed"}</td></tr>})}</tbody></table></div>}
