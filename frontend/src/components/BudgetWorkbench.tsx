import { useCallback, useEffect, useMemo, useState } from "react";
import { api, budgetPlanner, errorMessage, MONTHS } from "../api";
import type { BudgetWorkbench as WB, MonthKey, PlanRow } from "../api";
import LinkField from "./LinkField";

const num = (v: unknown) => Number(v ?? 0);
const money = (v: unknown) => num(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const short = (v: unknown) => { const n = num(v); const a = Math.abs(n); return a >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : a >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : a >= 1e3 ? `${(n / 1e3).toFixed(0)}K` : n.toFixed(0); };
const label = (m: string) => m[0].toUpperCase() + m.slice(1);
const rowTotal = (r: PlanRow) => MONTHS.reduce((s, m) => s + num(r[m]), 0);
type Tab = "plan" | "variance" | "scenarios" | "allocation" | "group";
type Item = { name: string; budget_name?: string; financial_year?: string; total_budget_amount?: number; approval_status?: string };

/** Month-by-month bars for the plan with the actual drawn as a line over them. Drawn in SVG so it needs no library. */
export function MonthChart({ budget, actual, through }: { budget: Record<MonthKey, number>; actual: Record<MonthKey, number>; through: number }) {
  const W = 640, H = 200, P = { l: 44, r: 10, t: 12, b: 24 };
  const max = Math.max(1, ...MONTHS.map(m => Math.max(num(budget[m]), num(actual[m]))));
  const bw = (W - P.l - P.r) / 12;
  const y = (v: number) => H - P.b - (v / max) * (H - P.t - P.b);
  const pts = MONTHS.slice(0, through).map((m, i) => `${P.l + i * bw + bw / 2},${y(num(actual[m]))}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Monthly budget and actual" className="bw-chart">
      {[0, 0.5, 1].map(f => <g key={f}><line x1={P.l} x2={W - P.r} y1={y(max * f)} y2={y(max * f)} className="bw-grid" /><text x={P.l - 6} y={y(max * f) + 4} textAnchor="end" className="bw-axis">{short(max * f)}</text></g>)}
      {MONTHS.map((m, i) => <g key={m}>
        <rect x={P.l + i * bw + bw * 0.18} width={bw * 0.64} y={y(num(budget[m]))} height={Math.max(0, H - P.b - y(num(budget[m])))} className="bw-bar"><title>{`${label(m)} budget ${money(budget[m])}`}</title></rect>
        <text x={P.l + i * bw + bw / 2} y={H - 8} textAnchor="middle" className="bw-axis">{label(m)}</text></g>)}
      {through > 0 && <><polyline points={pts} className="bw-line" fill="none" />{MONTHS.slice(0, through).map((m, i) => <circle key={m} cx={P.l + i * bw + bw / 2} cy={y(num(actual[m]))} r={3.5} className="bw-dot"><title>{`${label(m)} actual ${money(actual[m])}`}</title></circle>)}</>}
    </svg>
  );
}

export default function BudgetWorkbench({ name }: { name?: string }) {
  const [items, setItems] = useState<Item[]>([]);
  const [wb, setWb] = useState<WB | null>(null);
  const [plan, setPlan] = useState<PlanRow[]>([]);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState<Tab>("plan");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sel, setSel] = useState<number[]>([]);
  const [method, setMethod] = useState("Historical Pattern");
  const [growth, setGrowth] = useState("0");
  const [through, setThrough] = useState<number | undefined>(undefined);

  const loadList = useCallback(() => api.list("Financial Budget", { fields: ["name", "budget_name", "financial_year", "total_budget_amount", "approval_status"], limit: 200 })
    .then(r => setItems(r as unknown as Item[])).catch(e => setError(errorMessage(e))), []);
  useEffect(() => { void loadList(); }, [loadList]);

  const load = useCallback(async () => {
    if (!name) { setWb(null); setPlan([]); return; }
    setBusy(true); setError("");
    try { const r = await budgetPlanner.workbench(name, through); setWb(r); setPlan(r.plan.map(x => ({ ...x }))); setDirty(false); setSel([]); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }, [name, through]);
  useEffect(() => { void load(); }, [load]);

  const locked = !!wb && (wb.budget.docstatus !== 0 || wb.budget.approval_status === "Approved");
  const monthTotals = useMemo(() => Object.fromEntries(MONTHS.map(m => [m, plan.reduce((s, r) => s + num(r[m]), 0)])) as Record<MonthKey, number>, [plan]);
  const grand = MONTHS.reduce((s, m) => s + monthTotals[m], 0);

  function edit(i: number, patch: Partial<PlanRow>) {
    const same = (Object.keys(patch) as (keyof PlanRow)[]).every(k => (plan[i]?.[k] ?? "") === (patch[k] ?? ""));
    if (same) return;                                                   // a link field reports on blur even when nothing changed
    setPlan(p => p.map((r, k) => (k === i ? { ...r, ...patch } : r))); setDirty(true);
  }
  function addRow() { setPlan(p => [...p, { account: "" }]); setDirty(true); }
  function removeRows() { setPlan(p => p.filter((_, i) => !sel.includes(i))); setSel([]); setDirty(true); }
  function spread(i: number) { const r = plan[i]; const t = num(r.total ?? rowTotal(r)); if (!t) return; const each = Math.floor((t / 12) * 100) / 100; const p: Partial<PlanRow> = {}; MONTHS.forEach(m => { p[m] = each; }); p.dec = Math.round((t - each * 11) * 100) / 100; edit(i, p); }

  async function save() {
    if (!wb) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const clean = plan.filter(r => r.account).map(({ total, previous_year_actual, ...r }) => { void total; void previous_year_actual; return r; });
      await api.update("Financial Budget", wb.budget.name, { account_budgets: clean } as never);
      setNotice("Plan saved. The budget lines have been rebuilt from it.");
      await load(); await loadList();
    } catch (e) { setError(errorMessage(e)); setBusy(false); }
  }

  async function project() {
    if (!wb) return;
    const idx = sel.length ? sel : plan.map((_, i) => i).filter(i => plan[i].account);
    if (!idx.length) { setError("Add accounts to the plan first."); return; }
    setBusy(true); setError("");
    try {
      const r = await budgetPlanner.project(wb.budget.financial_year, idx.map(i => plan[i]), method, num(growth));
      setPlan(p => p.map((row, i) => { const k = idx.indexOf(i); return k < 0 ? row : { ...row, ...r.rows[k] }; })); setDirty(true);
      setNotice(`Projected ${idx.length} row(s) from last year's actuals. Review and save.`);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  async function draftFromLastYear() {
    if (!wb) return;
    setBusy(true); setError("");
    try {
      const r = await budgetPlanner.propose(wb.budget.financial_year, method, num(growth));
      if (!r.rows.length) { setNotice("No expense activity was found for last year, so there is nothing to project."); return; }
      setPlan(r.rows); setDirty(true); setNotice(`Drafted ${r.rows.length} account(s) from last year. Review, adjust and save.`);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  // ---- list screen ----
  if (!name) {
    return (
      <div className="panel bw">
        <div className="page-head"><div><h1>Budget Workbench</h1><p className="muted">Plan by month, compare with actuals, test scenarios and share budgets across branches or cost centres.</p></div>
          <a className="rbtn primary" href="#/app/Financial%20Budget/new">＋ New budget</a></div>
        {error && <div className="error" role="alert">{error}</div>}
        {!items.length ? <p className="muted">No budgets yet. Create one, then add its accounts here.</p> :
          <div className="table-wrap"><table><thead><tr><th>Budget</th><th>Financial Year</th><th className="num">Total</th><th>Status</th></tr></thead>
            <tbody>{items.map(b => <tr key={b.name} className="clickable" onClick={() => { location.hash = `#/budgets/${encodeURIComponent(b.name)}`; }}>
              <td><a href={`#/budgets/${encodeURIComponent(b.name)}`}>{b.budget_name || b.name}</a></td><td>{b.financial_year}</td><td className="num">{money(b.total_budget_amount)}</td><td><span className="pill">{b.approval_status}</span></td></tr>)}</tbody></table></div>}
      </div>
    );
  }

  const b = wb?.budget;
  const ytdBudget = wb?.variance.reduce((s, r) => s + r.budget_to_date, 0) ?? 0;
  const ytdActual = wb?.variance.reduce((s, r) => s + r.actual_to_date, 0) ?? 0;
  const thr = wb?.through_month ?? 0;

  return (
    <div className="panel bw">
      <div className="page-head"><div><h1>{b?.budget_name || name}</h1>
        <p className="muted">{b ? `${b.financial_year} · ${b.budget_type || "Operational"} · ${b.budget_against || "Whole Company"}` : "Loading…"}{b?.is_group_budget ? " · Group budget" : ""}</p></div>
        <div className="bw-actions"><a className="rbtn" href="#/budgets">← All budgets</a><a className="rbtn" href={`#/app/Financial%20Budget/${encodeURIComponent(name)}`}>Open form</a>
          {b && <span className="pill">{b.approval_status}{b.docstatus === 1 ? " · Submitted" : ""}</span>}</div></div>
      {error && <div className="error" role="alert">{error}</div>}{notice && <div className="status-pill" role="status">{notice}</div>}
      {wb && <>
        <div className="brc-kpis">
          <div className="brc-kpi"><span>Annual budget</span><strong>{money(dirty ? grand : wb.total)}</strong></div>
          <div className="brc-kpi"><span>Budget to date ({thr} mo)</span><strong>{money(ytdBudget)}</strong></div>
          <div className="brc-kpi"><span>Actual to date</span><strong>{money(ytdActual)}</strong></div>
          <div className="brc-kpi"><span>Used</span><strong className={ytdBudget && ytdActual > ytdBudget ? "brc-bad" : "brc-ok"}>{ytdBudget ? `${((ytdActual / ytdBudget) * 100).toFixed(1)}%` : "—"}</strong></div>
        </div>
        <div className="brc-tabs" role="tablist">{(["plan", "variance", "scenarios", "allocation", "group"] as Tab[]).filter(t => t !== "group" || b?.is_group_budget).map(t =>
          <button key={t} role="tab" aria-pressed={tab === t} onClick={() => setTab(t)}>{{ plan: "Monthly plan", variance: "Budget vs actual", scenarios: "Scenarios", allocation: "Allocation", group: "Roll-up" }[t]}</button>)}</div>

        {tab === "plan" && <>
          <MonthChart budget={monthTotals} actual={wb.actual_months} through={thr} />
          {locked && <p className="muted">This budget is approved or submitted, so the plan is read-only. Use a Budget Adjustment to change it.</p>}
          {!locked && <div className="bw-tools">
            <button className="rbtn" onClick={addRow}>＋ Add account</button>
            {!plan.length && <button className="rbtn" disabled={busy} onClick={() => void draftFromLastYear()}>Draft from last year</button>}
            <button className="rbtn" disabled={!sel.length} onClick={removeRows}>Remove selected</button>
            <span className="bw-sep" />
            <label>Project from last year<select value={method} onChange={e => setMethod(e.target.value)}><option>Historical Pattern</option><option>Equal Distribution</option></select></label>
            <label>Growth %<input type="number" value={growth} onChange={e => setGrowth(e.target.value)} step="0.5" /></label>
            <button className="rbtn" disabled={busy} onClick={() => void project()}>{sel.length ? `Project ${sel.length} selected` : "Project all rows"}</button>
            <span className="bw-sep" /><button className="rbtn primary" disabled={busy || !dirty} onClick={() => void save()}>Save plan</button></div>}
          <div className="table-wrap bw-grid-wrap"><table className="bw-table"><thead><tr><th /><th>Account</th><th>Cost centre</th><th>Branch</th>{MONTHS.map(m => <th key={m} className="num">{label(m)}</th>)}<th className="num">Total</th><th className="num">Last year</th><th /></tr></thead>
            <tbody>{plan.map((r, i) => <tr key={i}>
              <td><input type="checkbox" aria-label={`Select row ${i + 1}`} checked={sel.includes(i)} onChange={e => setSel(s => (e.target.checked ? [...s, i] : s.filter(x => x !== i)))} /></td>
              <td className="bw-acct"><LinkField doctype="Account" value={r.account} readOnly={locked} onChange={v => edit(i, { account: v })} ariaLabel={`Account row ${i + 1}`} /></td>
              <td className="bw-dim"><LinkField doctype="Cost Centre" value={r.cost_centre || ""} readOnly={locked} onChange={v => edit(i, { cost_centre: v || null })} ariaLabel={`Cost centre row ${i + 1}`} /></td>
              <td className="bw-dim"><LinkField doctype="Branch" value={r.branch || ""} readOnly={locked} onChange={v => edit(i, { branch: v || null })} ariaLabel={`Branch row ${i + 1}`} /></td>
              {MONTHS.map(m => <td key={m}><input className="num bw-cell" type="number" min="0" step="0.01" aria-label={`${label(m)} row ${i + 1}`} disabled={locked} value={r[m] ?? ""} onChange={e => edit(i, { [m]: e.target.value === "" ? 0 : Number(e.target.value) })} /></td>)}
              <td className="num"><strong>{money(rowTotal(r))}</strong></td><td className="num muted">{money(r.previous_year_actual)}</td>
              <td>{!locked && <button className="rbtn" title="Spread the total evenly across the twelve months" onClick={() => spread(i)}>Spread</button>}</td></tr>)}
              {!plan.length && <tr><td colSpan={19} className="muted">No accounts yet. Add accounts, or press “Project all rows” after adding them.</td></tr>}</tbody>
            <tfoot><tr><th colSpan={4}>Total</th>{MONTHS.map(m => <th key={m} className="num">{money(monthTotals[m])}</th>)}<th className="num">{money(grand)}</th><th colSpan={2} /></tr></tfoot></table></div>
        </>}

        {tab === "variance" && <>
          <label className="bw-inline">Months to compare<select value={through ?? thr} onChange={e => setThrough(Number(e.target.value))}>{Array.from({ length: 13 }, (_, i) => <option key={i} value={i}>{i === 0 ? "None" : `Jan–${label(MONTHS[i - 1])} (${i})`}</option>)}</select></label>
          <p className="muted">Variance is budget minus actual. For expenses a positive number means money left; for income it means you are behind target.</p>
          <div className="table-wrap"><table><thead><tr><th>Account</th><th>Cost centre</th><th className="num">Annual</th><th className="num">Budget to date</th><th className="num">Actual</th><th className="num">Variance</th><th className="num">Used %</th><th className="num">Year-end at this pace</th></tr></thead>
            <tbody>{wb.variance.map((v, i) => { const bad = v.better_when === "lower" ? v.variance < 0 : v.variance < 0; return <tr key={i}><td>{v.account}</td><td>{v.cost_centre || "—"}</td><td className="num">{money(v.annual_budget)}</td><td className="num">{money(v.budget_to_date)}</td><td className="num">{money(v.actual_to_date)}</td>
              <td className={`num ${bad ? "brc-bad" : "brc-ok"}`}>{money(v.variance)}</td><td className="num">{v.utilisation_percent == null ? "—" : `${v.utilisation_percent.toFixed(1)}%`}</td><td className="num">{v.projected_year_end == null ? "—" : money(v.projected_year_end)}</td></tr>; })}
              {!wb.variance.length && <tr><td colSpan={8} className="muted">Nothing to compare yet.</td></tr>}</tbody></table></div>
        </>}

        {tab === "scenarios" && <>
          <p className="muted">Scenarios are what-ifs on the base plan. They never change the approved budget. Add them on the budget form under “Scenarios”.</p>
          {!wb.scenarios.length ? <p className="muted">No scenarios yet.</p> : <>
            <div className="table-wrap"><table><thead><tr><th>Scenario</th><th>Type</th><th className="num">Change</th><th className="num">Probability</th><th className="num">Total</th><th className="num">Versus base</th></tr></thead>
              <tbody><tr><td><strong>Base plan</strong></td><td>—</td><td className="num">—</td><td className="num">—</td><td className="num">{money(wb.total)}</td><td className="num">—</td></tr>
                {wb.scenarios.map(s => <tr key={s.scenario_name} className={s.is_active ? "" : "muted"}><td>{s.scenario_name}{s.is_active ? "" : " (inactive)"}</td><td>{s.scenario_type}</td><td className="num">{s.adjustment_percent}%</td><td className="num">{s.probability}%</td><td className="num">{money(s.total_budget)}</td><td className={`num ${s.variance_from_base > 0 ? "brc-bad" : "brc-ok"}`}>{money(s.variance_from_base)}</td></tr>)}</tbody></table></div>
            {wb.scenarios[0]?.expected_total != null && <div className="brc-diff">Probability-weighted expected total: <strong>{money(wb.scenarios[0].expected_total)}</strong></div>}</>}
        </>}

        {tab === "allocation" && <>
          {!wb.allocation.length ? <p className="muted">This budget is not shared across branches or cost centres. Set “Share the plan across” on the budget form’s Allocation tab.</p> :
            <div className="table-wrap"><table><thead><tr><th>{wb.allocation_dimension === "branch" ? "Branch" : "Cost centre"}</th><th className="num">Share</th><th /><th className="num">Amount</th></tr></thead>
              <tbody>{wb.allocation.map((a, i) => <tr key={i}><td>{a.branch || a.cost_centre}{a.is_locked ? " 🔒" : ""}</td><td className="num">{a.allocation_percent.toFixed(2)}%</td>
                <td className="bw-share"><span style={{ width: `${Math.min(100, a.allocation_percent)}%` }} /></td><td className="num">{money(a.allocated_amount)}</td></tr>)}</tbody></table></div>}
        </>}

        {tab === "group" && <>
          <p className="muted">A group budget only adds up its child budgets. Postings are controlled by the child budgets, not by the group.</p>
          <div className="table-wrap"><table><thead><tr><th>Child budget</th><th>Status</th><th className="num">Total</th></tr></thead>
            <tbody>{wb.children.map(c => <tr key={c.name}><td><a href={`#/budgets/${encodeURIComponent(c.name)}`}>{c.budget_name}</a></td><td>{c.approval_status}</td><td className="num">{money(c.total_budget_amount)}</td></tr>)}
              {!wb.children.length && <tr><td colSpan={3} className="muted">No child budgets point to this one yet.</td></tr>}</tbody>
            <tfoot><tr><th colSpan={2}>Group total</th><th className="num">{money(wb.children_total)}</th></tr></tfoot></table></div>
        </>}
      </>}
    </div>
  );
}
