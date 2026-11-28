import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api";

type Finding = { severity: "critical" | "warning" | "info"; area: string; title: string; detail: string; route?: string | null };
const money = (v: string | number) => Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const SHORTCUTS: { group: string; items: { label: string; href: string }[] }[] = [
  { group: "Record", items: [
    { label: "Tax Journal (withholding tax)", href: "#/app/Tax Journal" }, { label: "Income Tax Computation", href: "#/app/Income Tax Computation" },
    { label: "Tax Return", href: "#/app/Tax Return" }, { label: "Tax Obligations", href: "#/app/Tax Obligation" } ] },
  { group: "Set up", items: [
    { label: "Tax Rules (rates)", href: "#/app/Tax Rule" }, { label: "Tax Jurisdictions", href: "#/app/Tax Jurisdiction" }, { label: "Tax Categories", href: "#/app/Tax Category" },
    { label: "Tax Settings", href: "#/app/Tax Settings" }, { label: "Accounts (tax treatment)", href: "#/app/Account" } ] },
  { group: "Reports", items: [
    { label: "Tax Ledger", href: "#/report/Tax Ledger" }, { label: "Tax Return Summary", href: "#/report/Tax Return Summary" }, { label: "Tax Obligation Calendar", href: "#/report/Tax Obligation Calendar" },
    { label: "WHT All Sources", href: "#/report/WHT All Sources" }, { label: "WHT Register", href: "#/report/WHT Register" }, { label: "WHT Position by Party", href: "#/report/WHT Position by Party" },
    { label: "Income Tax Computation Summary", href: "#/report/Income Tax Computation Summary" }, { label: "Tax Treatment of Accounts", href: "#/report/Tax Treatment of Accounts" }, { label: "VAT Return", href: "#/report/VAT Return" } ] },
];

export default function TaxCentre() {
  const [note, setNote] = useState(""), [dash, setDash] = useState<any>(null), [finds, setFinds] = useState<Finding[]>([]), [cat, setCat] = useState<any>(null), [q, setQ] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true); setError("");
    try { const [d, f] = await Promise.all([api.taxDashboard(), api.taxAdviser()]); setDash(d); setFinds(f.findings); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { api.taxCatalogue().then(setCat).catch(() => setCat(null)); }, []);
  async function samples() { try { const r = await api.installSamplePrintFormats(); setNote(r.installed.length ? `Installed: ${r.installed.join(", ")}.` : "The sample print formats are already installed."); } catch (e) { setError(errorMessage(e)); } }
  const kpi: [string, string, string?][] = dash ? [
    ["VAT output (year to date)", money(dash.vat_output)], ["VAT input (year to date)", money(dash.vat_input)], ["VAT net payable", money(dash.vat_net)],
    ["Withholding tax payable", money(dash.wht_payable)], ["Withholding tax credits", money(dash.wht_credit)],
    ...(Number(dash.exposure) > 0 ? [["Estimated tax, penalty and interest overdue", money(dash.exposure), "Rates are set in Tax Settings"] as [string, string, string]] : []),
    ["Open deadlines", String(dash.open_obligations), dash.overdue_obligations ? `${dash.overdue_obligations} overdue` : dash.next_due ? `Next: ${dash.next_due.tax_type} ${dash.next_due.due_date}` : ""],
  ] : [];
  const max = Math.max(1, ...(dash?.months ?? []).flatMap((m: any) => [m.output, m.input]));
  return <main className="tax-centre">
    <header className="page-head"><div><h1>Tax Centre</h1><p className="muted">Your tax position, what needs attention, and a way into every tax document and report. The adviser reads the books and the tax setup; it never posts or changes anything.</p></div>
      <button className="btn" onClick={() => void load()} disabled={busy}>{busy ? "Refreshing…" : "Refresh"}</button></header>
    {error && <div className="panel error" role="alert">{error}</div>}
    <div className="application-kpi-grid">{kpi.map(([l, v, n]) => <section className="application-kpi-card" key={l}><small>{l}</small><strong>{v}</strong>{n ? <small>{n}</small> : null}</section>)}</div>
    {cat && <section className="panel"><h2>Report library</h2>
      <p className="muted">{cat.executable} tax reports run on your books today. Every one listed here opens; reports that would need data this system does not hold are not shown.</p>
      <input aria-label="Search reports" placeholder="Search reports" value={q} onChange={e => setQ(e.target.value)} />
      {cat.domains.map((d: any) => { const rows = cat.reports.filter((r: any) => r.domain === d.domain && r.report_name.toLowerCase().includes(q.toLowerCase())); return rows.length ? <details key={d.domain} open={!!q}><summary><b>{d.domain}</b> <small>{d.executable}</small></summary>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "6px 0" }}>{rows.map((r: any) => <a className="btn" key={r.id} href={r.status === "Tax Report Library" ? `#/report/Tax Report Library?report=${encodeURIComponent(r.report_name)}` : `#/report/${encodeURI(r.status)}`}>{r.report_name}</a>)}</div></details> : null; })}
    </section>}
    <section className="panel"><h2>Tax adviser</h2>
      {dash && <p className="muted">{dash.findings.critical} critical · {dash.findings.warning} to review · {dash.findings.info} for information. These checks apply the rules you have approved; they are not legal advice.</p>}
      {!finds.length && dash && <p>Nothing needs attention.</p>}
      {finds.map((f, i) => <div className="workflow-row" key={i} style={{ borderLeft: `4px solid ${f.severity === "critical" ? "#b3261e" : f.severity === "warning" ? "#b26a00" : "#5b6b7a"}`, paddingLeft: 10 }}>
        <div><b>{f.title}</b><small>{f.area} · {f.severity}</small><p>{f.detail}</p></div>
        {f.route && <a className="btn" href={f.route.includes(" ") && !["Tax Rule", "Tax Settings", "Tax Obligation", "Income Tax Computation"].includes(f.route) ? `#/report/${encodeURIComponent(f.route)}` : `#/app/${encodeURIComponent(f.route)}`}>Open</a>}
      </div>)}
    </section>
    {dash?.months?.length > 0 && <section className="panel"><h2>VAT by month</h2>
      <div style={{ display: "grid", gap: 6 }}>{dash.months.map((m: any) => <div key={m.month} style={{ display: "grid", gridTemplateColumns: "70px 1fr 110px", gap: 8, alignItems: "center" }}>
        <small>{m.month}</small>
        <div aria-hidden><div style={{ height: 8, width: `${(m.output / max) * 100}%`, background: "#0f6cbd" }} /><div style={{ height: 8, marginTop: 2, width: `${(m.input / max) * 100}%`, background: "#2e7d32" }} /></div>
        <small>Out {money(m.output)} · In {money(m.input)}</small></div>)}</div>
      <p className="muted">Blue is output tax, green is input tax.</p></section>}
    <section className="panel"><h2>Documents, setup and reports</h2>
      {SHORTCUTS.map(g => <div key={g.group}><h3>{g.group}</h3><div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>{g.items.map(i => <a className="btn" key={i.label} href={encodeURI(i.href)}>{i.label}</a>)}</div></div>)}
      <h3>Printing</h3><button className="btn" onClick={() => void samples()}>Install sample Receipt, Official Receipt and Payment Voucher print formats</button>{note && <p className="muted" role="status">{note}</p>}
    </section>
  </main>;
}
