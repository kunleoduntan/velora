import { useEffect, useState } from "react";
import { downloadBlob, errorMessage, governance } from "../api";
import type { GovReport, GovReportRun } from "../api";
import { Card, Kpi, Tone } from "./centre";
import { CodeAssessment, IssbChecklist, SasbMetrics } from "./GovernanceReporting";

const TABS: [string, string][] = [["reports", "Reports"], ["exceptions", "Exceptions"], ["automation", "Automation"], ["sustainability", "Sustainability"], ["issb", "IFRS S1/S2"], ["code", "Code assessment"], ["sasb", "SASB metrics"]];
const label = (k: string) => k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
const cell = (v: unknown) => v == null || v === "" ? "–" : typeof v === "object" ? JSON.stringify(v) : String(v);

function Rows({ rows, columns, doctype }: { rows: Record<string, unknown>[]; columns: string[]; doctype?: string }) {
  if (!rows.length) return <p className="muted">Nothing to show yet.</p>;
  return <div className="table-wrap"><table><thead><tr>{columns.map(c => <th key={c}>{label(c)}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={String(r.name ?? i)}>{columns.map(c => <td key={c}>{c === "name" && doctype ? <a href={`#/app/${encodeURIComponent(doctype)}/${encodeURIComponent(String(r.name))}`}>{cell(r[c])}</a> : c === "status" || c === "severity" ? <Tone state={cell(r[c])} /> : cell(r[c])}</td>)}</tr>)}</tbody></table></div>;
}

function Reports() {
  const [cat, setCat] = useState<GovReport[]>([]), [pick, setPick] = useState(""), [run, setRun] = useState<GovReportRun | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false), [q, setQ] = useState("");
  useEffect(() => { governance.catalog().then(c => { setCat(c); setPick(c[0]?.report_id ?? ""); }).catch(e => setError(errorMessage(e))); }, []);
  useEffect(() => { if (!pick) return; setBusy(true); setError(""); governance.run(pick).then(setRun).catch(e => { setRun(null); setError(errorMessage(e)); }).finally(() => setBusy(false)); }, [pick]);
  const shown = cat.filter(c => !q.trim() || `${c.title} ${c.description} ${c.doctype}`.toLowerCase().includes(q.trim().toLowerCase()));
  const current = cat.find(c => c.report_id === pick);
  async function exportIt() { try { const f = await governance.exportXlsx(pick); downloadBlob(f.blob, f.filename); } catch (e) { setError(errorMessage(e)); } }
  return (
    <div className="gov-reports">
      <aside><input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Search reports…" aria-label="Search governance reports" />
        <ul>{shown.map(c => <li key={c.report_id}><button type="button" className={c.report_id === pick ? "on" : ""} onClick={() => setPick(c.report_id)}>{c.title}</button></li>)}</ul></aside>
      <div>
        {error && <div className="error" role="alert">{error}</div>}
        {current && <Card title={current.title} note={current.description}>
          <div className="gov-actions"><button type="button" className="btn primary" onClick={exportIt} disabled={busy}>Export to Excel</button>{run && <span className="muted">{run.summary.record_count} record(s){run.summary.overdue_records ? ` · ${run.summary.overdue_records} overdue` : ""}</span>}</div>
          {busy ? <p className="muted">Running…</p> : run && <Rows rows={run.rows} columns={run.columns.slice(0, 9)} doctype={current.doctype} />}
        </Card>}
      </div>
    </div>
  );
}

function Exceptions() {
  const [status, setStatus] = useState(""), [data, setData] = useState<Awaited<ReturnType<typeof governance.exceptions>> | null>(null), [error, setError] = useState("");
  useEffect(() => { setError(""); governance.exceptions(status).then(setData).catch(e => setError(errorMessage(e))); }, [status]);
  const k = data?.kpis ?? {};
  return (
    <>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="brc-kpis"><Kpi label="Exceptions" value={k.total ?? 0} /><Kpi label="Active" value={k.active ?? 0} /><Kpi label="Overdue" value={k.overdue_active ?? 0} tone={k.overdue_active ? "bad" : "ok"} /><Kpi label="Critical" value={k.critical_active ?? 0} tone={k.critical_active ? "bad" : "ok"} /></div>
      <Card title="Exception centre"><label>Status <select value={status} onChange={e => setStatus(e.target.value)}><option value="">All</option>{["Open", "Acknowledged", "In Progress", "Escalated", "Resolved", "Closed"].map(s => <option key={s}>{s}</option>)}</select></label>
        <Rows rows={data?.rows ?? []} columns={["name", "title", "exception_type", "severity", "status", "due_date", "overdue_days", "assigned_to"]} doctype="Governance Exception" /></Card>
    </>
  );
}

function Automation() {
  const [data, setData] = useState<Awaited<ReturnType<typeof governance.history>> | null>(null), [error, setError] = useState(""), [note, setNote] = useState("");
  const load = () => { setError(""); governance.history().then(setData).catch(e => setError(errorMessage(e))); };
  useEffect(load, []);
  async function retry(name: string) { setNote(""); try { await governance.retry(name); setNote(`${name} was queued to run again.`); load(); } catch (e) { setError(errorMessage(e)); } }
  const rows = data?.rows ?? [];
  return (
    <Card title="Automation history" note="Scheduled governance work: what ran, what failed and what can be run again.">
      {error && <div className="error" role="alert">{error}</div>}{note && <div className="notice" role="status">{note}</div>}
      {rows.length === 0 ? <p className="muted">Nothing has run yet.</p> :
        <div className="table-wrap"><table><thead><tr><th>Run</th><th>Status</th><th>Started</th><th>Message</th><th /></tr></thead><tbody>
          {rows.map(r => <tr key={String(r.name)}><td><a href={`#/app/Governance%20Automation%20Execution/${encodeURIComponent(String(r.name))}`}>{String(r.name)}</a></td><td><Tone state={cell(r.status)} /></td><td>{cell(r.started_on ?? r.creation).slice(0, 16)}</td><td>{cell(r.error_message ?? r.summary ?? r.message)}</td>
            <td>{["Failed", "Dead"].includes(String(r.status)) && <button type="button" className="btn" onClick={() => retry(String(r.name))}>Retry</button>}</td></tr>)}</tbody></table></div>}
    </Card>
  );
}

function Sustainability() {
  const [d, setD] = useState<Record<string, unknown> | null>(null), [error, setError] = useState("");
  useEffect(() => { governance.sustainability().then(setD).catch(e => setError(errorMessage(e))); }, []);
  const n = (k: string) => Number(d?.[k] ?? 0);
  const periods = (d?.period_summary as Record<string, unknown>[] | undefined) ?? [];
  return (
    <>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="brc-kpis"><Kpi label="Reporting periods" value={n("periods")} /><Kpi label="Disclosures ready" value={`${n("disclosures_ready")} / ${n("disclosures_total")}`} /><Kpi label="Readiness" value={`${n("readiness_percent")}%`} tone={n("readiness_percent") >= 80 ? "ok" : "warn"} /><Kpi label="Tasks overdue" value={n("tasks_overdue")} tone={n("tasks_overdue") ? "bad" : "ok"} /><Kpi label="Reviews pending" value={n("reviews_pending")} /></div>
      <Card title="By reporting period">{periods.length ? <Rows rows={periods} columns={Object.keys(periods[0]).slice(0, 7)} /> : <p className="muted">No reporting periods yet. Create one under Sustainability Reporting Period.</p>}</Card>
    </>
  );
}

/** Governance reports, exceptions, automation and sustainability, on one page with a tab per area. */
export default function GovernanceCentre({ page = "reports" }: { page?: string }) {
  const tab = TABS.some(t => t[0] === page) ? page : "reports";
  return (
    <div className="panel gov-centre">
      <div className="hub-head"><div><a className="hub-back" href="#/hub/governance">← Governance hub</a><h1>Governance</h1><p className="muted">Reports with Excel export, the exception centre, scheduled automation and sustainability reporting.</p></div></div>
      <div className="hub-tabs" role="tablist">{TABS.map(([id, l]) => <a key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} href={`#/governance/${id}`}>{l}</a>)}</div>
      {tab === "reports" && <Reports />}{tab === "exceptions" && <Exceptions />}{tab === "automation" && <Automation />}{tab === "sustainability" && <Sustainability />}{tab === "issb" && <IssbChecklist />}{tab === "code" && <CodeAssessment />}{tab === "sasb" && <SasbMetrics />}
    </div>
  );
}
