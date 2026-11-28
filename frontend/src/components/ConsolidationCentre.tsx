import { useEffect, useMemo, useState } from "react";
import { api, consolidation, downloadBlob, errorMessage } from "../api";
import type { ConsCompany, ConsResult } from "../api";
import { Card, Kpi, money } from "./centre";

const VIEWS: [string, string][] = [["worksheet", "Worksheet"], ["income", "Income statement"], ["balance", "Balance sheet"], ["eliminations", "Eliminations"], ["checks", "Checks"]];
const yearStart = () => `${new Date().getFullYear()}-01-01`;
const today = () => new Date().toISOString().slice(0, 10);
const n2 = (v: number) => money(v, 2);
const ROOTS = ["Asset", "Liability", "Equity", "Income", "Expense"];

function Setup({ companies, onDone }: { companies: ConsCompany[]; onDone: (name: string) => void }) {
  const [name, setName] = useState("My Group"), [cur, setCur] = useState("NGN"), [error, setError] = useState("");
  const [pick, setPick] = useState<Record<string, { on: boolean; pct: number; method: string }>>(() => Object.fromEntries(companies.map(c => [c.id, { on: true, pct: 100, method: "Full" }])));
  async function create() {
    setError("");
    const members = companies.filter(c => pick[c.id]?.on).map(c => ({ company_id: c.id, include: 1, ownership_percent: pick[c.id].pct, method: pick[c.id].method }));
    if (!members.length) { setError("Choose at least one company."); return; }
    try { const d = await api.create("Consolidation Group", { group_name: name.trim(), presentation_currency: cur.trim().toUpperCase(), members }); onDone(String(d.name)); } catch (e) { setError(errorMessage(e)); }
  }
  return (
    <Card title="Set up a consolidation group" note="Pick the companies that report together and the currency the group reports in. Add elimination rules and account mapping afterwards, on the group itself.">
      <div className="cons-setup">
        <label>Group name<input value={name} onChange={e => setName(e.target.value)} /></label>
        <label>Reporting currency<input value={cur} maxLength={3} onChange={e => setCur(e.target.value)} /></label>
      </div>
      <div className="table-wrap"><table><thead><tr><th /><th>Company</th><th className="num">Ownership %</th><th>Method</th></tr></thead><tbody>
        {companies.map(c => { const p = pick[c.id]; return (
          <tr key={c.id}><td><input type="checkbox" aria-label={`Include ${c.name}`} checked={p.on} onChange={e => setPick({ ...pick, [c.id]: { ...p, on: e.target.checked } })} /></td>
            <td>{c.name}{c.current ? <small> (this company)</small> : null}</td>
            <td className="num"><input type="number" min={1} max={100} value={p.pct} aria-label={`Ownership of ${c.name}`} onChange={e => setPick({ ...pick, [c.id]: { ...p, pct: Number(e.target.value) } })} /></td>
            <td><select value={p.method} aria-label={`Method for ${c.name}`} onChange={e => setPick({ ...pick, [c.id]: { ...p, method: e.target.value } })}><option>Full</option><option>Proportionate</option></select></td></tr>); })}
      </tbody></table></div>
      {error && <div className="error" role="alert">{error}</div>}
      <button type="button" className="btn primary" onClick={create}>Create group</button>
    </Card>
  );
}

function Statement({ rows, title, total }: { rows: { key: string; label: string; amount: number }[]; title: string; total: number }) {
  return (<tbody><tr className="cons-head"><th colSpan={2}>{title}</th></tr>{rows.map(r => <tr key={r.key}><td>{r.label}</td><td className="num">{n2(r.amount)}</td></tr>)}<tr className="cons-total"><td>Total {title.toLowerCase()}</td><td className="num">{n2(total)}</td></tr></tbody>);
}

export default function ConsolidationCentre() {
  const [companies, setCompanies] = useState<ConsCompany[] | null>(null), [groups, setGroups] = useState<string[] | null>(null), [group, setGroup] = useState("");
  const [from, setFrom] = useState(yearStart), [to, setTo] = useState(today), [res, setRes] = useState<ConsResult | null>(null), [view, setView] = useState("worksheet");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [note, setNote] = useState(""), [setup, setSetup] = useState(false);
  const loadGroups = (pick?: string) => api.list("Consolidation Group", { fields: ["name", "status"] } as never).then(rows => { const names = rows.filter(r => r.status !== "Inactive").map(r => String(r.name)); setGroups(names); setGroup(pick ?? names[0] ?? ""); }).catch(e => { setGroups([]); setError(errorMessage(e)); });
  useEffect(() => { consolidation.companies().then(setCompanies).catch(e => { setCompanies([]); setError(errorMessage(e)); }); loadGroups(); }, []);
  const names = useMemo(() => Object.fromEntries((companies ?? []).map(c => [c.id, c.name])), [companies]);

  async function run(save = false) {
    setBusy(true); setError(""); setNote("");
    try { const r = await consolidation.run(group, from, to, save); setRes(r); if (r.saved_as) setNote(`Saved as ${r.saved_as}.`); } catch (e) { setRes(null); setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function exportIt() { try { const f = await consolidation.exportXlsx(group, from, to, view === "eliminations" ? "worksheet" : view); downloadBlob(f.blob, f.filename); } catch (e) { setError(errorMessage(e)); } }

  if (companies === null || groups === null) return <div className="panel"><p className="muted">Loading…</p></div>;
  const errors = res?.checks.filter(c => c.level === "error") ?? [], warnings = res?.checks.filter(c => c.level === "warning") ?? [];
  const lines = res?.lines ?? [];
  return (
    <div className="panel cons-centre">
      <div className="hub-head"><div><a className="hub-back" href="#/hub/finance">← Finance hub</a><h1>Consolidation Centre</h1><p className="muted">Report several companies as one: translated into one currency, with what the companies owe each other removed.</p></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      {(groups.length === 0 || setup) ? <Setup companies={companies} onDone={name => { setSetup(false); loadGroups(name); }} /> : (
        <div className="cons-bar">
          <label>Group<select value={group} onChange={e => { setGroup(e.target.value); setRes(null); }}>{groups.map(g => <option key={g}>{g}</option>)}</select></label>
          <label>From<input type="date" value={from} onChange={e => setFrom(e.target.value)} /></label>
          <label>To<input type="date" value={to} onChange={e => setTo(e.target.value)} /></label>
          <button type="button" className="btn primary" onClick={() => run(false)} disabled={busy || !group}>{busy ? "Consolidating…" : "Consolidate"}</button>
          <a className="btn" href={`#/app/Consolidation%20Group/${encodeURIComponent(group)}`}>Rules & mapping</a>
          <button type="button" className="btn" onClick={() => setSetup(true)}>New group</button>
          <a className="btn" href="#/app/Consolidation%20Run">Saved runs</a>
        </div>
      )}
      {res && (<>
        <div className={`cons-status ${res.ok ? "ok" : "bad"}`} role="status">{res.ok ? `Ready: ${res.members.length} company(ies) consolidated into ${res.currency}${warnings.length ? `, with ${warnings.length} thing(s) to look at.` : "."}` : `Not ready to rely on: ${errors.length} problem(s) need fixing first.`}</div>
        <div className="brc-kpis">
          <Kpi label={`Profit (${res.currency})`} value={n2(res.income_statement.profit)} /><Kpi label="Total assets" value={n2(res.balance_sheet.assets.total)} />
          <Kpi label="Total equity" value={n2(res.balance_sheet.total_equity)} /><Kpi label="Non-controlling interest" value={n2(res.balance_sheet.non_controlling_interest)} />
          <Kpi label="Balance check" value={n2(res.balance_sheet.check)} tone={Math.abs(res.balance_sheet.check) < 0.01 ? "ok" : "bad"} />
        </div>
        <div className="hub-tabs" role="tablist">{VIEWS.map(([id, l]) => <button key={id} type="button" role="tab" aria-selected={view === id} className={view === id ? "on" : ""} onClick={() => setView(id)}>{l}{id === "checks" && (errors.length + warnings.length) ? ` (${errors.length + warnings.length})` : ""}</button>)}</div>
        <div className="gov-actions">{view !== "eliminations" && <button type="button" className="btn" onClick={exportIt}>Export to Excel</button>}<button type="button" className="btn" onClick={() => run(true)} disabled={busy}>Save this consolidation</button>{note && <span className="muted" role="status">{note}</span>}</div>
        {view === "worksheet" && <div className="table-wrap"><table className="cons-table"><thead><tr><th>Account</th>{res.members.map(m => <th key={m.company_id} className="num" title={`${m.ownership}% · ${m.method} · ${m.currency}`}>{m.name}</th>)}<th className="num">Eliminations</th><th className="num">Consolidated</th></tr></thead>
          {ROOTS.map(root => { const rows = lines.filter(l => l.root_type === root); return rows.length ? (<tbody key={root}><tr className="cons-head"><th colSpan={res.members.length + 3}>{root}</th></tr>
            {rows.map(l => <tr key={l.key}><td>{l.key.startsWith("~") ? l.label : `${l.key} · ${l.label}`}</td>{res.members.map(m => <td key={m.company_id} className="num">{l.cells[m.company_id] ? n2(l.cells[m.company_id]) : "–"}</td>)}<td className="num">{l.elimination ? n2(l.elimination) : "–"}</td><td className="num"><b>{n2(l.total)}</b></td></tr>)}</tbody>) : null; })}</table></div>}
        {view === "income" && <table className="cons-table"><Statement title="Income" rows={res.income_statement.income.rows} total={res.income_statement.income.total} /><Statement title="Expenses" rows={res.income_statement.expense.rows} total={res.income_statement.expense.total} />
          <tbody><tr className="cons-total"><td>Profit for the period</td><td className="num">{n2(res.income_statement.profit)}</td></tr><tr><td>Attributable to owners of the group</td><td className="num">{n2(res.income_statement.profit_attributable_to_owners)}</td></tr><tr><td>Attributable to non-controlling interests</td><td className="num">{n2(res.income_statement.non_controlling_profit)}</td></tr></tbody></table>}
        {view === "balance" && <table className="cons-table"><Statement title="Assets" rows={res.balance_sheet.assets.rows} total={res.balance_sheet.assets.total} /><Statement title="Liabilities" rows={res.balance_sheet.liabilities.rows} total={res.balance_sheet.liabilities.total} />
          <Statement title="Equity" rows={[...res.balance_sheet.equity.rows, { key: "~PROFIT", label: "Profit for the period", amount: res.balance_sheet.current_result }]} total={res.balance_sheet.total_equity} />
          <tbody><tr><td>of which non-controlling interests</td><td className="num">{n2(res.balance_sheet.non_controlling_interest)}</td></tr><tr><td>Equity attributable to owners</td><td className="num">{n2(res.balance_sheet.equity_attributable_to_owners)}</td></tr></tbody></table>}
        {view === "eliminations" && (res.eliminations.length === 0 ? <p className="muted">Nothing was eliminated. Add elimination rules on the group to remove what the companies owe or earn from each other.</p> :
          <div className="table-wrap"><table><thead><tr><th>Rule</th><th>Between</th><th className="num">Eliminated</th></tr></thead><tbody>{res.eliminations.map((e, i) => <tr key={i}><td>{e.description}</td><td>{names[e.company_one] ?? e.company_one} {e.account_one} ↔ {names[e.company_two] ?? e.company_two} {e.account_two}</td><td className="num">{n2(e.amount)}</td></tr>)}</tbody></table></div>)}
        {view === "checks" && <ul className="cons-checks">{res.checks.map((c, i) => <li key={i} className={`cons-${c.level}`}><b>{c.level === "error" ? "Fix" : c.level === "warning" ? "Look" : "Note"}</b> {c.message}</li>)}</ul>}
        {view !== "checks" && errors.length > 0 && <div className="error" role="alert">{errors[0].message}{errors.length > 1 ? ` (and ${errors.length - 1} more under Checks)` : ""}</div>}
      </>)}
    </div>
  );
}
