import { useState } from "react";
import { controlsCheck, errorMessage } from "../api";
import type { ControlFinding, ControlsResult } from "../api";

const today = () => new Date().toISOString().slice(0, 10);
const yearStart = () => `${new Date().getFullYear()}-01-01`;
const head = (k: string) => k.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
const cell = (v: string | number) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v);

function Finding({ f }: { f: ControlFinding }) {
  const [open, setOpen] = useState(f.count > 0 && f.severity === "Error");
  const cols = f.rows[0] ? Object.keys(f.rows[0]) : [];
  return (
    <section className={`admin-card cc-card cc-${f.count ? f.severity.toLowerCase() : "clear"}`}>
      <button className="cc-head" aria-expanded={open} onClick={() => f.count > 0 && setOpen(o => !o)}>
        <span className="cc-dot" aria-hidden="true" /><strong>{f.title}</strong>
        <span className="pill">{f.count ? `${f.count} found` : "All clear"}</span>
        {f.count > 0 && f.amount != null && <span className="muted">{f.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>}
      </button>
      {open && f.count > 0 && <>
        <p className="muted">{f.why}</p>
        <div className="table-wrap"><table><thead><tr>{cols.map(c => <th key={c}>{head(c)}</th>)}</tr></thead>
          <tbody>{f.rows.map((r, i) => <tr key={i}>{cols.map(c => <td key={c} className={typeof r[c] === "number" ? "num" : ""}>{cell(r[c])}</td>)}</tr>)}</tbody></table></div>
        {f.truncated && <p className="muted">Showing the first {f.rows.length} of {f.count}. Narrow the dates to see the rest.</p>}
      </>}
    </section>
  );
}

/** Read-only controls: duplicates, old balances, credit limits, bills above their order, and control accounts against party balances. */
export default function ControlsCheck() {
  const [from, setFrom] = useState(yearStart()), [to, setTo] = useState(today()), [scope, setScope] = useState("Both"), [stale, setStale] = useState("90");
  const [res, setRes] = useState<ControlsResult | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function run() { setBusy(true); setError(""); try { setRes(await controlsCheck.run(from, to, scope, Number(stale) || 90)); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  const order = { Error: 0, Warning: 1, Info: 2 } as const;
  const sorted = res ? [...res.findings].sort((a, b) => (b.count ? 1 : 0) - (a.count ? 1 : 0) || order[a.severity] - order[b.severity]) : [];
  return (
    <div className="panel">
      <div className="page-head"><div><h1>Receivables &amp; Payables Check</h1><p className="muted">Looks for what an auditor would ask about. It only reads: nothing is changed or posted.</p></div></div>
      <div className="brc-bar">
        <label>From<input type="date" value={from} onChange={e => setFrom(e.target.value)} /></label>
        <label>To<input type="date" value={to} onChange={e => setTo(e.target.value)} /></label>
        <label>Check<select value={scope} onChange={e => setScope(e.target.value)}><option value="Both">Receivables and payables</option><option value="Receivables">Receivables only</option><option value="Payables">Payables only</option></select></label>
        <label>Old balance after (days)<input type="number" min={1} value={stale} onChange={e => setStale(e.target.value)} /></label>
        <button className="rbtn primary" disabled={busy} onClick={() => void run()}>{busy ? "Checking…" : "Run check"}</button>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {res && <>
        <div className="brc-kpis">
          <div className="brc-kpi"><span>Checks run</span><strong>{res.summary.checks}</strong></div>
          <div className="brc-kpi"><span>Need attention</span><strong className={res.summary.with_findings ? "brc-bad" : "brc-ok"}>{res.summary.with_findings}</strong></div>
          <div className="brc-kpi"><span>Errors</span><strong className={res.summary.errors ? "brc-bad" : "brc-ok"}>{res.summary.errors}</strong></div>
          <div className="brc-kpi"><span>Warnings</span><strong>{res.summary.warnings}</strong></div>
        </div>
        {sorted.map(f => <Finding key={f.code} f={f} />)}
      </>}
    </div>
  );
}
