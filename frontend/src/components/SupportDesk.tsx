import { useEffect, useState } from "react";
import { errorMessage, support } from "../api";
import type { SupportSummary } from "../api";
import { Bars, Card, Kpi, Tone } from "./centre";

const hours = (h: number | null) => h == null ? "–" : h < 48 ? `${h.toLocaleString(undefined, { maximumFractionDigits: 1 })}h` : `${(h / 24).toLocaleString(undefined, { maximumFractionDigits: 1 })}d`;

/** The support queue for agents and managers: what is breaching, who is overloaded, how the service is doing. */
export default function SupportDesk() {
  const [data, setData] = useState<SupportSummary | null>(null), [error, setError] = useState(""), [filter, setFilter] = useState<"all" | "unassigned" | "risk">("all");
  const load = () => { setError(""); support.summary().then(setData).catch(e => setError(errorMessage(e))); };
  useEffect(() => { load(); const t = window.setInterval(load, 60000); return () => window.clearInterval(t); }, []);
  const k = data?.kpis;
  const rows = (data?.queue ?? []).filter(r => filter === "all" ? true : filter === "unassigned" ? !r.assigned_to : [r.response_sla, r.resolution_sla].some(s => s === "At risk" || s === "Breached"));
  const worst = (r: { response_sla: string; resolution_sla: string }) => [r.response_sla, r.resolution_sla].includes("Breached") ? "Breached" : [r.response_sla, r.resolution_sla].includes("At risk") ? "At risk" : r.response_sla === "Paused" ? "Paused" : "On track";
  const maxTrend = Math.max(1, ...(data?.trend ?? []).flatMap(t => [t.opened, t.resolved]));
  return (
    <div className="panel">
      <div className="page-head">
        <div><h1>Support Desk</h1><p className="muted">Tickets, service-level clocks and workload. Refreshes every minute.</p></div>
        <div className="head-actions"><a className="rbtn primary" href="#/app/Support%20Ticket/new">New ticket</a><a className="rbtn" href="#/app/Service%20Level%20Agreement">Service levels</a></div>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && k && <>
        <div className="brc-kpis">
          <Kpi label="Open" value={k.open} />
          <Kpi label="Breached" value={k.breached} tone={k.breached ? "bad" : "ok"} />
          <Kpi label="At risk" value={k.at_risk} tone={k.at_risk ? "warn" : "ok"} />
          <Kpi label="Unassigned" value={k.unassigned} tone={k.unassigned ? "warn" : "ok"} />
          <Kpi label="Waiting on customer" value={k.waiting} />
          <Kpi label="Resolved today" value={k.resolved_today} />
          <Kpi label="Average first response" value={hours(k.avg_first_response_hours)} />
          <Kpi label="Average resolution" value={hours(k.avg_resolution_hours)} />
          <Kpi label="Resolved within target" value={k.sla_met_percent == null ? "–" : `${k.sla_met_percent}%`} />
          <Kpi label="Customer satisfaction" value={k.satisfaction == null ? "–" : `${k.satisfaction} / 5`} />
        </div>
        <Card title="Queue" note="Breached and at-risk tickets come first, then by priority and age.">
          <div className="brc-bar">
            {([["all", "All open"], ["risk", "Breached or at risk"], ["unassigned", "Unassigned"]] as const).map(([v, label]) =>
              <button key={v} className={`rbtn${filter === v ? " primary" : ""}`} aria-pressed={filter === v} onClick={() => setFilter(v)}>{label}</button>)}
          </div>
          {rows.length === 0 ? <p className="muted">No tickets here.</p> :
            <div className="table-wrap"><table><thead><tr><th>Ticket</th><th>Subject</th><th>Priority</th><th>Status</th><th>Assigned to</th><th>Service level</th><th>Due</th><th className="num">Age</th></tr></thead>
              <tbody>{rows.map(r => <tr key={r.name}>
                <td><a href={`#/app/Support%20Ticket/${encodeURIComponent(r.name)}`}>{r.name}</a></td>
                <td>{r.subject}{r.escalation_level > 0 && <small className="brc-bad"> escalated ×{r.escalation_level}</small>}</td>
                <td>{r.priority}</td><td>{r.status}</td><td>{r.assigned_to ?? <span className="muted">Unassigned</span>}</td>
                <td><Tone state={worst(r)} /></td><td>{(r.response_sla && r.response_sla !== "Met" ? r.first_response_due : r.resolution_due)?.slice(0, 16).replace("T", " ") ?? ""}</td>
                <td className="num">{hours(r.age_hours)}</td></tr>)}</tbody></table></div>}
        </Card>
        <div className="admin-grid">
          <Card title="Workload"><Bars items={data.workload.map(w => ({ label: w.agent, value: w.open, flag: w.breached > 0, note: w.breached ? `${w.breached} breached` : "" }))} format={n => String(n)} /></Card>
          <Card title="Age of open tickets"><Bars items={data.ageing.map(a => ({ label: a.bucket, value: a.count }))} format={n => String(n)} /></Card>
          <Card title="Open tickets by category"><Bars items={data.categories.map(c => ({ label: c.category, value: c.count }))} format={n => String(n)} /></Card>
          <Card title="Last 14 days" note="Opened and resolved each day.">
            <div className="cx-trend" role="img" aria-label="Tickets opened and resolved per day over the last 14 days">
              {data.trend.map(t => <div key={t.date} className="cx-trend-day" title={`${t.date}: ${t.opened} opened, ${t.resolved} resolved`}>
                <span className="cx-trend-bar cx-in" style={{ height: `${t.opened / maxTrend * 100}%` }} /><span className="cx-trend-bar cx-out" style={{ height: `${t.resolved / maxTrend * 100}%` }} /></div>)}
            </div>
            <p className="muted"><span className="cx-key cx-in" /> Opened <span className="cx-key cx-out" /> Resolved</p>
          </Card>
        </div>
      </>}
    </div>
  );
}
