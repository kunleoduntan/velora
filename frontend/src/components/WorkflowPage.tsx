import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../api";
import LinkField from "./LinkField";
import WorkflowBuilder from "./WorkflowBuilder";
import SimpleWorkflow from "./SimpleWorkflow";
import WorkflowGovernancePanel from "./WorkflowGovernancePanel";
import ScriptManager from "./ScriptManager";

type Tab = "design" | "approvals" | "monitoring" | "governance" | "automation" | "delegation";
const TABS: { id: Tab; label: string }[] = [
  { id: "design", label: "Workflow Designer" }, { id: "approvals", label: "Approvals & Tasks" },
  { id: "monitoring", label: "Monitoring" }, { id: "governance", label: "Version Governance" },
  { id: "automation", label: "Automation" }, { id: "delegation", label: "Delegation" },
];

export default function WorkflowPage() {
  const [tab, setTab] = useState<Tab>("design");
  const [advanced, setAdvanced] = useState(false);
  const [doctype, setDoctype] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [inbox, setInbox] = useState<any[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);
  const [metrics, setMetrics] = useState<any>(null);
  const [error, setError] = useState("");
  const [instanceId, setInstanceId] = useState("");
  const [instance, setInstance] = useState<any>(null);
  const [action, setAction] = useState("");
  const [comment, setComment] = useState("");
  const [approvalStep, setApprovalStep] = useState("");
  const [documentName, setDocumentName] = useState("");
  const [selectedWorkflow, setSelectedWorkflow] = useState("");
  const [simulation, setSimulation] = useState<any>(null);
  const [simulationData, setSimulationData] = useState("{}");
  const [eventName, setEventName] = useState("");
  const [eventAction, setEventAction] = useState("");
  const [eventPayload, setEventPayload] = useState("{}");
  const [automationName, setAutomationName] = useState("");
  const [automationEvent, setAutomationEvent] = useState("after_insert");
  const [automationHandler, setAutomationHandler] = useState("");
  const [automationConditions, setAutomationConditions] = useState("[]");
  const [slaMinutes, setSlaMinutes] = useState(1440);
  const [slaLevels, setSlaLevels] = useState("[]");
  const [delegator, setDelegator] = useState("");
  const [delegate, setDelegate] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const all = await api.workflows();
    setItems(all);
    try { setInbox(await api.workflowInbox()); } catch { setInbox([]); }
    try { setTasks(await api.workflowTasks("Open")); } catch { setTasks([]); }
    try { setMetrics(await api.workflowAnalytics()); } catch { setMetrics(null); }
  }
  useEffect(() => { load().catch((e) => setError(errorMessage(e))); }, []);

  const scoped = useMemo(() => items.filter((w) => !doctype || w.doctype === doctype), [items, doctype]);
  useEffect(() => { if (!scoped.some((w) => w.name === selectedWorkflow)) setSelectedWorkflow(scoped[0]?.name || ""); }, [scoped, selectedWorkflow]);

  async function openApproval(id: string, initialAction?: string, step?: string) {
    setError(""); setBusy(true);
    try { const doc = await api.workflowInstance(id); setInstance(doc); setInstanceId(id); setAction(initialAction || doc.available_actions?.[0]?.action || ""); setApprovalStep(step || ""); setTab("approvals"); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function refreshInstance() {
    if (!instanceId) return;
    setBusy(true); setError("");
    try { setInstance(await api.workflowInstance(instanceId)); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function submitAction() {
    if (!instanceId || !action) return;
    setBusy(true); setError("");
    try { setInstance(await api.workflowAction(instanceId, action, comment, approvalStep || undefined)); setComment(""); await load(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function startWorkflow() {
    if (!selectedWorkflow || !doctype || !documentName.trim()) return;
    setBusy(true); setError("");
    try { const result = await api.startWorkflow(selectedWorkflow, doctype, documentName.trim()); setInstance(result); setInstanceId(result.id); setTab("approvals"); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function saveAutomation() {
    setBusy(true); setError("");
    try { await api.saveWorkflowAutomation({ name: automationName, event: automationEvent, doctype, handler: automationHandler, conditions: JSON.parse(automationConditions) }); setError("Automation rule saved."); }
    catch (e) { setError(e instanceof SyntaxError ? "Conditions must be valid JSON." : errorMessage(e)); } finally { setBusy(false); }
  }
  async function createDelegation() {
    setBusy(true); setError("");
    try { await api.createWorkflowDelegation({ delegator, delegate, valid_from: new Date().toISOString(), valid_until: new Date(validUntil).toISOString() }); setDelegator(""); setDelegate(""); setValidUntil(""); setError("Delegation saved."); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  return <div className="panel workflow-studio">
    <header className="page-head"><div><h1>Workflow & Business Process Automation</h1><p className="muted">Configure approvals one DocType at a time. All workflow definitions are company-configurable; no business DocType is hardcoded.</p></div>
      <button className="rbtn" onClick={() => load().catch((e) => setError(errorMessage(e)))}>Refresh</button>
    </header>
    {error && <div className="notice" role="status">{error}</div>}
    <section className="admin-card workflow-scope">
      <div><h2>Document type</h2><p className="muted">Select one DocType to create, edit and govern its workflow.</p></div>
      <div className="workflow-scope-field"><LinkField doctype="DocType" value={doctype} onChange={(v) => { setDoctype(v); setInstance(null); setError(""); }} placeholder="Search DocTypes…" ariaLabel="Select DocType for workflow" /></div>
      <div className="workflow-scope-meta">{doctype ? <><strong>{scoped.length}</strong> workflow definition(s) for <strong>{doctype}</strong></> : "No DocType selected"}</div>
    </section>
    <nav className="workflow-tabs" aria-label="Workflow sections">{TABS.map((t) => <button key={t.id} type="button" className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>{t.label}</button>)}</nav>

    {tab === "design" && <>
      {!doctype ? <section className="admin-card"><p className="muted">Select a DocType above to open its workflow designer.</p></section> :
        advanced ? <><button type="button" className="rbtn" onClick={() => setAdvanced(false)}>← Simple tables</button><WorkflowBuilder key={doctype} workflows={scoped} selectedDoctype={doctype} onSaved={() => load().catch((e) => setError(errorMessage(e)))} /></>
          : <SimpleWorkflow key={doctype + (scoped[0]?.name ?? "")} workflows={scoped} selectedDoctype={doctype} onAdvanced={() => setAdvanced(true)} onSaved={() => load().catch((e) => setError(errorMessage(e)))} />}
    </>}

    {tab === "approvals" && <div className="workflow-section-grid">
      <section className="admin-card"><div className="section-heading"><div><h2>My approval inbox</h2><p className="muted">Only approvals assigned to you or your roles are shown.</p></div><button className="rbtn" onClick={() => load().catch((e) => setError(errorMessage(e)))}>Refresh</button></div>
        {inbox.filter((x) => !doctype || x.doctype === doctype).map((x) => <div className="workflow-row" key={`${x.id}-${x.action}-${x.step || ""}`}><b>{x.label || x.action}</b><small>{x.doctype} · {x.document_name} · {x.state}</small><button className="rbtn" onClick={() => openApproval(x.id, x.action, x.step)}>Open approval</button></div>)}
        {!inbox.some((x) => !doctype || x.doctype === doctype) && <p className="muted">No pending approvals for this DocType and user.</p>}
      </section>
      <section className="admin-card"><h2>My assigned tasks</h2><button className="rbtn" onClick={() => api.workflowTasks("Open").then(setTasks).catch((e) => setError(errorMessage(e)))}>Refresh tasks</button>
        {tasks.filter((x) => !doctype || x.doctype === doctype).map((t) => <div className="workflow-row" key={t.id}><b>{t.title}</b><small>{t.doctype} · {t.description || "Workflow task"} · Due {t.due_on || "—"}</small><button className="rbtn" onClick={() => api.completeWorkflowTask(t.id).then(() => api.workflowTasks("Open").then(setTasks)).catch((e) => setError(errorMessage(e)))}>Mark complete</button></div>)}
        {!tasks.some((x) => !doctype || x.doctype === doctype) && <p className="muted">No open tasks for this DocType.</p>}
      </section>
      <section className="admin-card wide"><h2>Approval instance</h2><div className="form-grid"><label>Instance ID<input value={instanceId} onChange={(e) => setInstanceId(e.target.value)} /></label><div className="field"><span>&nbsp;</span><button className="rbtn" disabled={!instanceId || busy} onClick={() => void refreshInstance()}>Load instance</button></div></div>
        {instance && <><p><strong>{instance.doctype}</strong> · {instance.document_name} · {instance.state} · {instance.status}</p><div className="form-grid"><label>Action<select value={action} onChange={(e) => setAction(e.target.value)}>{(instance.available_actions || []).map((a: any) => <option key={a.action} value={a.action}>{a.action}</option>)}</select></label><label>Approval branch<select value={approvalStep} onChange={(e) => setApprovalStep(e.target.value)}><option value="">Default</option>{(instance.available_actions?.find((a: any) => a.action === action)?.parallel_steps || []).map((b: any) => <option key={b.key} value={b.key}>{b.label}</option>)}</select></label><label className="wide">Comment<input value={comment} onChange={(e) => setComment(e.target.value)} /></label></div><button className="rbtn primary" disabled={busy || instance.status !== "Active" || !action} onClick={() => void submitAction()}>Submit action</button><h3>Audit history</h3>{(instance.history || []).map((h: any) => <div className="workflow-row" key={h.id}><b>{h.action}</b><small>{h.actor} · {h.from_state || "—"} → {h.to_state}</small><small>{h.comment}</small></div>)}</>}
      </section>
    </div>}

    {tab === "monitoring" && <div className="workflow-section-grid">
      {metrics && <section className="admin-card wide"><h2>Process performance</h2><div className="form-grid"><div><b>{metrics.active_instances}</b><small>Active workflows</small></div><div><b>{metrics.completed_instances}</b><small>Completed workflows</small></div><div><b>{metrics.overdue_active_instances}</b><small>Overdue SLAs</small></div><div><b>{metrics.average_completion_hours_90_days ?? "—"}</b><small>Average completion hours (90 days)</small></div></div></section>}
      <section className="admin-card"><h2>Start a workflow</h2><label>Workflow definition<select value={selectedWorkflow} onChange={(e) => setSelectedWorkflow(e.target.value)}><option value="">Select workflow</option>{scoped.map((w) => <option key={w.name} value={w.name}>{w.name}</option>)}</select></label><label>Document ID<input value={documentName} onChange={(e) => setDocumentName(e.target.value)} placeholder="Existing document name" /></label><button className="rbtn primary" disabled={!doctype || !selectedWorkflow || !documentName.trim() || busy} onClick={() => void startWorkflow()}>Start workflow</button></section>
      <section className="admin-card"><h2>Simulate workflow routing</h2><label>Workflow<select value={selectedWorkflow} onChange={(e) => setSelectedWorkflow(e.target.value)}><option value="">Select workflow</option>{scoped.map((w) => <option key={w.name} value={w.name}>{w.name}</option>)}</select></label><label>Sample document data (JSON)<textarea rows={5} value={simulationData} onChange={(e) => setSimulationData(e.target.value)} /></label><button className="rbtn" disabled={!selectedWorkflow || busy} onClick={async () => { try { setSimulation(await api.simulateWorkflow(selectedWorkflow, JSON.parse(simulationData))); setError(""); } catch (e) { setError(e instanceof SyntaxError ? "Document data must be valid JSON." : errorMessage(e)); } }}>Test routing</button>{simulation && <pre>{JSON.stringify(simulation, null, 2)}</pre>}</section>
    </div>}

    {tab === "governance" && <>{doctype ? <WorkflowGovernancePanel workflows={scoped} /> : <section className="admin-card"><p className="muted">Select a DocType to review its workflow versions.</p></section>}</>}

    {tab === "automation" && <div className="workflow-section-grid">
      <section className="admin-card"><h2>Document event automation</h2><p className="muted">Rules apply to the selected DocType and use registered application handlers.</p><label>Rule name<input value={automationName} onChange={(e) => setAutomationName(e.target.value)} /></label><label>Event<select value={automationEvent} onChange={(e) => setAutomationEvent(e.target.value)}>{["before_insert", "after_insert", "before_save", "after_save", "on_submit", "on_cancel", "after_delete"].map((v) => <option key={v}>{v}</option>)}</select></label><label>Registered handler<input value={automationHandler} onChange={(e) => setAutomationHandler(e.target.value)} placeholder="my_app.jobs.handle_document" /></label><label>Conditions (JSON)<textarea rows={4} value={automationConditions} onChange={(e) => setAutomationConditions(e.target.value)} /></label><button className="rbtn primary" disabled={!doctype || !automationName || !automationHandler || busy} onClick={() => void saveAutomation()}>Save automation</button></section>
      <section className="admin-card"><h2>Event gateway</h2><p className="muted">Publish and subscribe to named events for an active workflow instance.</p><label>Workflow instance ID<input value={instanceId} onChange={(e) => setInstanceId(e.target.value)} /></label><label>Event name<input value={eventName} onChange={(e) => setEventName(e.target.value)} placeholder="finance.payment.confirmed" /></label><label>Action<input value={eventAction} onChange={(e) => setEventAction(e.target.value)} /></label><button className="rbtn" disabled={!instanceId || !eventName || !eventAction} onClick={() => api.subscribeWorkflowEvent(instanceId, eventName, eventAction).then(() => setError("Event subscription saved.")).catch((e) => setError(errorMessage(e)))}>Subscribe event</button><label>Payload (JSON)<textarea rows={4} value={eventPayload} onChange={(e) => setEventPayload(e.target.value)} /></label><button className="rbtn" disabled={!eventName} onClick={() => { try { api.publishWorkflowEvent(eventName, JSON.parse(eventPayload)).then((r) => setError(`Event matched ${r.matched_count} subscription(s).`)).catch((e) => setError(errorMessage(e))); } catch { setError("Payload must be valid JSON."); } }}>Publish event</button></section>
      <section className="admin-card wide"><ScriptManager /></section>
    </div>}

    {tab === "delegation" && <section className="admin-card"><h2>Approval delegation</h2><p className="muted">Allow a named user to act for another approver during a defined period.</p><div className="form-grid"><label>Approver email<input type="email" value={delegator} onChange={(e) => setDelegator(e.target.value)} /></label><label>Delegate email<input type="email" value={delegate} onChange={(e) => setDelegate(e.target.value)} /></label><label>Valid until<input type="datetime-local" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} /></label></div><button className="rbtn primary" disabled={!delegator || !delegate || !validUntil || busy} onClick={() => void createDelegation()}>Create delegation</button></section>}
  </div>;
}
