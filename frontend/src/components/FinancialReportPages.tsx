import LinkField from "./LinkField";
import { useEffect, useState } from "react";
import { api, errorMessage, type FinancialDrilldownResult, type FinancialLayoutInfo, type FinancialStatementResult } from "../api";
import { goTo } from "../router";

function today() { return new Date().toISOString().slice(0, 10); }
function firstDay() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`; }
function money(value: number | null | undefined) {
  if (value === null || value === undefined) return "";
  return new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}
function openDetail(layoutId: string, row: string, column: string, filters: Record<string, string | undefined>) {
  const q = new URLSearchParams({ layout: layoutId, row, column, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== undefined && v !== "")) as Record<string, string> });
  window.open(`#/financial-report-detail?${q.toString()}`, "_blank", "noopener");
}

export function FinancialReportRun({ layoutId }: { layoutId: string }) {
  const [layout, setLayout] = useState<FinancialLayoutInfo | null>(null);
  const [result, setResult] = useState<FinancialStatementResult | null>(null);
  const [fromDate, setFromDate] = useState(firstDay());
  const [toDate, setToDate] = useState(today());
  const [asOfDate, setAsOfDate] = useState(today());
  const [budgetName, setBudgetName] = useState("");
  const [dimensions, setDimensions] = useState({ cost_centre: "", branch: "", business_unit: "", project: "", department: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.financialLayout(layoutId).then(setLayout).catch((e) => setError(errorMessage(e))); }, [layoutId]);
  function reportFilters() {
    return { from_date: fromDate, to_date: toDate, as_of_date: asOfDate, budget_name: budgetName.trim() || undefined,
      ...Object.fromEntries(Object.entries(dimensions).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()])) };
  }
  async function run() {
    setBusy(true); setError("");
    try { setResult(await api.runFinancialReport(layoutId, reportFilters())); }
    catch (e) { setError(errorMessage(e)); setResult(null); }
    finally { setBusy(false); }
  }
  async function exportXlsx() {
    setBusy(true); setError("");
    try {
      const blob = await api.exportFinancialReport(layoutId, reportFilters());
      const url = URL.createObjectURL(blob); const a = document.createElement("a");
      a.href = url; a.download = `${(layout?.name || "financial_report").replace(/[^a-z0-9_-]/gi, "_")}.xlsx`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function exportPdf() {
    setBusy(true); setError("");
    try {
      const blob = await api.exportFinancialReportPdf(layoutId, reportFilters());
      const url = URL.createObjectURL(blob); const a = document.createElement("a");
      a.href = url; a.download = `${(layout?.name || "financial_report").replace(/[^a-z0-9_-]/gi, "_")}.pdf`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  return <main style={{ padding: 28, maxWidth: 1500, margin: "0 auto" }}>
    <button className="rbtn" onClick={() => goTo("#/financial-reports")}>← Back to designer</button>
    <div className="frd-header" style={{ marginTop: 18 }}><div><div className="eyebrow">FINANCIAL REPORTING / EXECUTION</div><h1>{layout?.name ?? "Financial report"}</h1><p>Run the saved statement against the active company's General Ledger.</p></div></div>
    <section className="frd-panel" style={{ padding: 18, marginBottom: 20 }}>
      <form className="report-filters report-filter-grid" onSubmit={(e) => { e.preventDefault(); void run(); }}>
        <div className="field"><label htmlFor="fr_from">From Date</label><input id="fr_from" type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} /></div>
        <div className="field"><label htmlFor="fr_to">To Date</label><input id="fr_to" type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} /></div>
        <div className="field"><label htmlFor="fr_asat">As At Date</label><input id="fr_asat" type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} /><small>Used by the Statement of Financial Position</small></div>
        <div className="field"><label htmlFor="fr_budget">Budget Name</label><input id="fr_budget" value={budgetName} onChange={(e) => setBudgetName(e.target.value)} /><small>Required for budget columns</small></div>
        {([ ["cost_centre", "Cost Centre", "Cost Centre"], ["business_unit", "Business Unit", "Business Unit"], ["department", "Department", "Department"], ["branch", "Branch", ""], ["project", "Project", ""] ] as const).map(([key, label, target]) =>
          <div className="field" key={key}><label htmlFor={`fr_${key}`}>{label}</label>
            {target ? <LinkField id={`fr_${key}`} doctype={target} value={dimensions[key]} onChange={(v) => setDimensions({ ...dimensions, [key]: v })} />
              : <input id={`fr_${key}`} value={dimensions[key]} onChange={(e) => setDimensions({ ...dimensions, [key]: e.target.value })} />}</div>
        )}
      </form>
      <button className="rbtn primary" disabled={busy || !layout} onClick={run}>{busy ? "Working…" : "Run financial report"}</button>
      {result && <><button className="rbtn" disabled={busy} onClick={exportXlsx}>Export Excel</button><button className="rbtn" disabled={busy} onClick={exportPdf}>Export PDF</button></>}
      {error && <div className="error" role="alert" style={{ marginTop: 12 }}>{error}</div>}
    </section>
    {result && <section className="frd-panel" style={{ padding: 18, overflowX: "auto" }}>
      <div className="frd-result-heading"><div><div className="eyebrow">GOVERNED FINANCIAL STATEMENT</div><h2>{result.name}</h2><p className="muted">{result.base_currency || "Company base currency"} · Posted ledger values · Click an account-backed amount to inspect its General Ledger evidence.</p></div><div className="frd-result-badge">Live ledger view</div></div>
      <div className="frd-scope-summary">{[fromDate && `From ${fromDate}`, toDate && `To ${toDate}`, asOfDate && `As at ${asOfDate}`, ...(budgetName.trim() ? [`Budget: ${budgetName.trim()}`] : []), ...Object.entries(dimensions).filter(([, value]) => value.trim()).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`)].filter(Boolean).join("  ·  ")}</div>
      <table className="frd-preview-table" style={{ width: "100%" }}>
        <thead><tr><th>Particulars</th>{result.columns.map((c) => <th key={c.code} style={{ minWidth: c.width * 7 }}><div>{c.caption}</div><small>{c.period_label}</small></th>)}</tr></thead>
        <tbody>{result.rows.map((r) => <tr key={r.code} className={r.bold ? "strong" : ""}>
          <td style={{ paddingLeft: 12 + r.indent * 18, fontStyle: r.italic ? "italic" : "normal" }}>{r.description}</td>
          {result.columns.map((c) => { const value = r.values[c.code]; const drillable = ["account", "account_range", "account_category", "dimension"].includes(r.type) && !["formula", "text", "blank", "budget"].includes(c.type) && value !== null; return <td key={c.code} style={{ textAlign: "right" }}>
            {drillable ? <button type="button" className="frd-drill-link" title="Open ledger details in a new tab" onClick={() => openDetail(layoutId, r.code, c.code, reportFilters())}>{money(value)}</button> : money(value)}
          </td>; })}
        </tr>)}</tbody>
      </table>
    </section>}
  </main>;
}

export function FinancialReportDetail({ query }: { query: Record<string, string> }) {
  const [data, setData] = useState<FinancialDrilldownResult | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!query.layout || !query.row || !query.column) { setError("The report detail link is incomplete."); setBusy(false); return; }
    api.financialReportDrilldown(query.layout, { row_code: query.row, column_code: query.column, filters: { from_date: query.from_date, to_date: query.to_date, as_of_date: query.as_of_date, cost_centre: query.cost_centre, branch: query.branch, business_unit: query.business_unit, project: query.project, department: query.department }, limit: 1000, account: query.account })
      .then(setData).catch((e) => setError(errorMessage(e))).finally(() => setBusy(false));
  }, [query.layout, query.row, query.column, query.from_date, query.to_date, query.as_of_date, query.cost_centre, query.branch, query.business_unit, query.project, query.department]);
  return <main style={{ padding: 28, maxWidth: 1500, margin: "0 auto" }}>
    <button className="rbtn" onClick={() => window.close()}>Close details</button>
    <div className="frd-header" style={{ marginTop: 18 }}><div><div className="eyebrow">GENERAL LEDGER DRILL-DOWN</div><h1>{data?.description ?? "Statement details"}</h1><p>{data?.period_label ?? "Transaction-level evidence for the selected statement figure."}</p></div></div>
    {busy && <p>Loading ledger details…</p>}
    {error && <div className="error" role="alert">{error}</div>}
    {data && <>
      <div className="frd-notice" style={{ marginBottom: 14 }}>{query.account ? `Account ledger: ${query.account}` : `Accounts: ${data.accounts.join(", ") || "No matching accounts"}`}</div>
      {data.truncated && <div className="frd-notice">The result reached the 1,000-entry display limit. Narrow the reporting period to inspect all entries.</div>}
      <section className="frd-panel" style={{ padding: 18, overflowX: "auto" }}>
        <table className="frd-preview-table" style={{ width: "100%" }}><thead><tr><th>Date</th><th>Account</th><th>Voucher type</th><th>Voucher no.</th><th>Party</th><th>Remarks</th><th>Debit</th><th>Credit</th><th>Statement amount</th></tr></thead>
          <tbody>{data.entries.map((e) => <tr key={e.name}><td>{e.posting_date}</td><td><button className="frd-drill-link" title="Open this account's ledger details" onClick={() => { const q = new URLSearchParams({ layout: query.layout, row: query.row, column: query.column, from_date: query.from_date, to_date: query.to_date, as_of_date: query.as_of_date, account: e.account }); window.open(`${window.location.pathname}#/financial-report-detail?${q.toString()}`, "_blank", "noopener"); }}>{e.account}</button></td><td>{e.voucher_type}</td><td><button className="frd-drill-link" title="Open the source voucher in another tab" onClick={() => { const target = `${window.location.pathname}#/app/${encodeURIComponent(e.voucher_type)}/${encodeURIComponent(e.voucher_no)}`; window.open(target, "_blank", "noopener"); }}>{e.voucher_no}</button></td><td>{e.party ? `${e.party_type ?? ""} ${e.party}` : ""}</td><td>{e.remarks ?? ""}{e.is_reversal ? " · Reversal" : ""}</td><td style={{ textAlign: "right" }}>{money(e.debit)}</td><td style={{ textAlign: "right" }}>{money(e.credit)}</td><td style={{ textAlign: "right" }}>{money(e.amount)}</td></tr>)}</tbody>
        </table>
        {data.entries.length === 0 && <p className="muted">No posted General Ledger entries match this statement cell.</p>}
      </section>
    </>}
  </main>;
}
