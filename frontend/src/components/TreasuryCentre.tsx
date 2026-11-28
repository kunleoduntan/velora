import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api";

type Finding = { severity: "critical" | "warning" | "info"; area: string; title: string; detail: string; route?: string | null };
const money = (v: string | number | null | undefined) => Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const colour = (s: string) => (s === "critical" ? "#b3261e" : s === "warning" ? "#b26a00" : "#5b6b7a");
const STATUS: Record<string, string> = { Compliant: "#2e7d32", Warning: "#b26a00", Breach: "#b3261e", "Never tested": "#5b6b7a" };
const SHORTCUTS: { group: string; items: { label: string; href: string }[] }[] = [
  { group: "Borrow and repay", items: [
    { label: "Financing Drawdown", href: "#/app/Financing Drawdown" }, { label: "Financing Repayment", href: "#/app/Financing Repayment" },
    { label: "Interest Accrual", href: "#/app/Interest Accrual" }, { label: "Facility Amendment (rate change)", href: "#/app/Facility Amendment" }, { label: "Covenant Test", href: "#/app/Covenant Test" } ] },
  { group: "Set up", items: [
    { label: "Financial Institutions (lenders)", href: "#/app/Financial Institution" }, { label: "Financing Facilities", href: "#/app/Financing Facility" }, { label: "Treasury Settings", href: "#/app/Treasury Settings" } ] },
  { group: "Reports", items: ["Debt Portfolio", "Debt Maturity Ladder", "Debt Service Schedule", "Loan Amortisation Schedule", "Interest Expense and Accrual", "Facility Utilisation and Headroom", "Liquidity Forecast",
    "FX Exposure and Sensitivity", "Overdue Repayments", "Covenant Monitor", "Borrowing Cost by Lender", "Security Register"].map(n => ({ label: n, href: `#/report/${n}` })) },
];

function Bar({ pct, colourName }: { pct: number; colourName?: string }) {
  return <div aria-hidden style={{ background: "#e6ebf0", borderRadius: 4, height: 10 }}><div style={{ width: `${Math.max(0, Math.min(100, pct))}%`, height: 10, borderRadius: 4, background: colourName || "#00577a" }} /></div>;
}

export default function TreasuryCentre() {
  const [d, setD] = useState<any>(null), [lq, setLq] = useState<any>(null), [fx, setFx] = useState<any[]>([]), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true); setError("");
    try { const [a, b, c] = await Promise.all([api.treasuryDashboard(), api.treasuryLiquidity(), api.treasuryFx()]); setD(a); setLq(b); setFx(c.rows); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const ccy = d?.base_currency || "";
  const kpi: [string, string, string?][] = d ? [
    [`Total debt (${ccy})`, money(d.total_debt), `${d.loans} loan(s) on ${d.facilities} facilit${d.facilities === 1 ? "y" : "ies"}`],
    ["Net debt (debt less cash)", money(d.net_debt), `Cash ${money(d.cash)}`],
    ["Weighted interest rate", `${Number(d.weighted_rate || 0).toFixed(2)}%`, `${Number(d.floating_share || 0).toFixed(0)}% floating`],
    ["Undrawn and available", money(d.undrawn)],
    ["Debt service, next 30 days", money(d.debt_service_30), `90 days: ${money(d.debt_service_90)}`],
    ["Accrued interest unpaid", money(d.accrued_unpaid)],
    [`If rates rise ${d.rate_shock_points} points`, money(d.rate_shock_cost), "extra yearly interest on floating loans"],
    ...(Number(d.overdue_amount) > 0 ? [["Overdue repayments", money(d.overdue_amount), `${d.overdue_loans} loan(s)`] as [string, string, string]] : []),
  ] : [];
  const ladderMax = Math.max(1, ...(d?.ladder ?? []).map((l: any) => Number(l.principal)));
  const cashMax = Math.max(1, ...(lq?.rows ?? []).map((r: any) => Math.abs(Number(r.closing))));
  const cov = d?.covenants || {};
  return <main className="treasury-centre">
    <header className="page-head"><div><h1>Treasury Centre</h1><p className="muted">What you owe, what falls due, how much room is left on your facilities, and what the adviser would raise with you this morning. Nothing here posts or changes a record.</p></div>
      <button className="btn" onClick={() => void load()} disabled={busy}>{busy ? "Refreshing…" : "Refresh"}</button></header>
    {error && <div className="panel error" role="alert">{error}</div>}
    <div className="application-kpi-grid">{kpi.map(([l, v, n]) => <section className="application-kpi-card" key={l}><small>{l}</small><strong>{v}</strong>{n ? <small>{n}</small> : null}</section>)}</div>
    {d && <section className="panel"><h2>Treasury adviser</h2>
      <p className="muted">{d.finding_counts.critical} critical · {d.finding_counts.warning} to review · {d.finding_counts.info} for information. The adviser reads the loans, schedules, covenants and ledger; it is guidance, not financial advice.</p>
      {!d.findings.length && <p>Nothing needs attention.</p>}
      {d.findings.map((f: Finding, i: number) => <div className="workflow-row" key={i} style={{ borderLeft: `4px solid ${colour(f.severity)}`, paddingLeft: 10 }}>
        <div><b>{f.title}</b><small>{f.area} · {f.severity}</small><p>{f.detail}</p></div>
        {f.route && <a className="btn" href={`#/app/${encodeURIComponent(f.route)}`}>Open</a>}
      </div>)}
    </section>}
    {d?.ladder?.length > 0 && <section className="panel"><h2>When the debt falls due</h2>
      <div style={{ display: "grid", gap: 6 }}>{d.ladder.map((l: any) => <div key={l.bucket} style={{ display: "grid", gridTemplateColumns: "120px 1fr 130px", gap: 8, alignItems: "center" }}>
        <small>{l.bucket}</small><Bar pct={(Number(l.principal) / ladderMax) * 100} colourName={l.bucket === "Overdue" ? "#b3261e" : undefined} /><small>{money(l.principal)}</small></div>)}</div>
      <p className="muted">Principal only, in {ccy}. A tall bar far out is a refinancing date to plan for.</p></section>}
    {d?.facility_usage?.length > 0 && <section className="panel"><h2>Facility headroom</h2>
      <div style={{ display: "grid", gap: 8 }}>{d.facility_usage.map((f: any) => <div key={f.name}>
        <div style={{ display: "flex", justifyContent: "space-between" }}><b>{f.name}</b><small>{money(f.outstanding)} of {money(f.limit)} {f.currency} · {Number(f.percent || 0).toFixed(0)}% used · availability ends {String(f.expires)}</small></div>
        <Bar pct={Number(f.percent || 0)} colourName={Number(f.percent) >= 90 ? "#b3261e" : Number(f.percent) >= 75 ? "#b26a00" : undefined} /></div>)}</div></section>}
    {lq?.rows?.length > 0 && <section className="panel"><h2>Cash runway by week</h2>
      <p className="muted">Opening cash {money(lq.opening)}. {lq.assumption}</p>
      <div style={{ display: "grid", gap: 4 }}>{lq.rows.map((r: any) => <div key={r.week} style={{ display: "grid", gridTemplateColumns: "60px 1fr 120px 90px", gap: 8, alignItems: "center" }}>
        <small>Week {r.week}</small><Bar pct={(Math.abs(Number(r.closing)) / cashMax) * 100} colourName={r.short ? "#b3261e" : r.below_buffer ? "#b26a00" : "#2e7d32"} />
        <small>{money(r.closing)}</small><small>{r.short ? "Short" : r.below_buffer ? "Below buffer" : ""}</small></div>)}</div></section>}
    <section className="panel"><h2>Covenants</h2>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{["Compliant", "Warning", "Breach", "Never tested"].map(s => <span key={s} style={{ borderLeft: `4px solid ${STATUS[s]}`, paddingLeft: 8 }}><b>{cov[s] || 0}</b> <small>{s}</small></span>)}</div>
      {d && d.tests_overdue > 0 && <p className="muted">{d.tests_overdue} covenant test(s) are overdue.</p>}
      <a className="btn" href="#/report/Covenant Monitor">Open Covenant Monitor</a></section>
    {d?.lenders?.length > 0 && <section className="panel"><h2>Lenders</h2>
      <div style={{ display: "grid", gap: 6 }}>{d.lenders.map((l: any) => <div key={l.lender} style={{ display: "grid", gridTemplateColumns: "180px 1fr 130px", gap: 8, alignItems: "center" }}>
        <small>{l.lender}</small><Bar pct={Number(l.percent)} /><small>{money(l.amount)} · {Number(l.percent).toFixed(0)}%</small></div>)}</div></section>}
    {fx.length > 0 && <section className="panel"><h2>Currency exposure</h2>
      <table className="grid"><thead><tr><th>Currency</th><th>Receivables</th><th>Payables</th><th>Debt</th><th>Net</th><th>If it weakens</th></tr></thead>
        <tbody>{fx.map(r => <tr key={r.currency}><td>{r.currency}</td><td>{money(r.receivables)}</td><td>{money(r.payables)}</td><td>{money(r.debt)}</td><td>{money(r.net)}</td><td>{money(r.loss_if_weaker)} {ccy}</td></tr>)}</tbody></table></section>}
    <section className="panel"><h2>Documents, setup and reports</h2>
      {SHORTCUTS.map(g => <div key={g.group}><h3>{g.group}</h3><div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>{g.items.map(i => <a className="btn" key={i.label} href={encodeURI(i.href)}>{i.label}</a>)}</div></div>)}
    </section>
  </main>;
}
