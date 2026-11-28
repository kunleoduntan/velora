import { useState } from "react";
import { errorMessage, glReview } from "../api";
import type { GlReview as Review } from "../api";
import { Card, Kpi, money, today } from "./centre";

const addYears = (iso: string, n: number) => { const d = new Date(iso); d.setUTCFullYear(d.getUTCFullYear() + n); return d.toISOString().slice(0, 10); };

/** Analytical review of the ledger (ISA 520 style): what moved, what is new, what looks unusual. Read-only. */
export default function GlReview() {
  const year = new Date().getFullYear();
  const [from, setFrom] = useState(`${year}-01-01`), [to, setTo] = useState(today());
  const [pFrom, setPFrom] = useState(`${year - 1}-01-01`), [pTo, setPTo] = useState(addYears(today(), -1));
  const [threshold, setThreshold] = useState("50"), [floor, setFloor] = useState("10000");
  const [res, setRes] = useState<Review | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function run() {
    setBusy(true); setError("");
    try { setRes(await glReview.run(from, to, pFrom, pTo, Number(threshold) || 0, Number(floor) || 0)); } catch (e) { setError(errorMessage(e)); setRes(null); } finally { setBusy(false); }
  }
  const s = res?.summary;
  return (
    <div className="panel">
      <div className="page-head"><div><h1>General Ledger Review</h1><p className="muted">Compares a period with an earlier one and lists what an auditor would ask about. Each item says why it was raised; none is an accusation.</p></div></div>
      <div className="brc-bar">
        <label>Review from<input type="date" value={from} onChange={e => setFrom(e.target.value)} /></label>
        <label>to<input type="date" value={to} onChange={e => setTo(e.target.value)} /></label>
        <label>Compare with, from<input type="date" value={pFrom} onChange={e => setPFrom(e.target.value)} /></label>
        <label>to<input type="date" value={pTo} onChange={e => setPTo(e.target.value)} /></label>
        <label>Change of at least (%)<input type="number" min={0} value={threshold} onChange={e => setThreshold(e.target.value)} /></label>
        <label>and an amount of at least<input type="number" min={0} value={floor} onChange={e => setFloor(e.target.value)} /></label>
        <button className="rbtn primary" disabled={busy} onClick={() => void run()}>{busy ? "Reviewing…" : "Run review"}</button>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {res && s && <>
        <div className="brc-kpis">
          <Kpi label="Accounts with activity" value={s.accounts_current} />
          <Kpi label="Accounts flagged" value={s.flagged} tone={s.flagged ? "warn" : "ok"} />
          <Kpi label="Suspense / clearing lines" value={s.suspense_lines} tone={s.suspense_lines ? "warn" : "ok"} />
          <Kpi label="Journals flagged" value={s.journals_flagged} tone={s.journals_flagged ? "warn" : "ok"} />
          <Kpi label="Month-end clusters" value={s.months_clustered} tone={s.months_clustered ? "warn" : "ok"} />
        </div>
        <Card title="Accounts to look at" note="Net movement is debit minus credit, so income normally shows as a negative number.">
          {res.flagged_accounts.length === 0 ? <p className="muted">Nothing crossed the thresholds.</p> :
            <div className="table-wrap"><table><thead><tr><th>Account</th><th className="num">This period</th><th className="num">Earlier period</th><th className="num">Change</th><th className="num">%</th><th>Why</th></tr></thead>
              <tbody>{res.flagged_accounts.map(a => <tr key={a.account}><td>{a.code} {a.name}<small>{a.root_type}</small></td><td className="num">{money(a.current)}</td><td className="num">{money(a.prior)}</td><td className="num">{money(a.change)}</td><td className="num">{a.change_percent}%</td><td>{a.reasons.join("; ")}</td></tr>)}</tbody></table></div>}
        </Card>
        {res.suspense.length > 0 && <Card title="Suspense and clearing accounts" note="Balances here should be temporary. Each line needs a home.">
          <div className="table-wrap"><table><thead><tr><th>Date</th><th>Account</th><th>Document</th><th className="num">Debit</th><th className="num">Credit</th><th>Description</th></tr></thead>
            <tbody>{res.suspense.map((r, i) => <tr key={i}><td>{r.date}</td><td>{r.account}</td><td>{r.document}</td><td className="num">{money(r.debit)}</td><td className="num">{money(r.credit)}</td><td>{r.description}</td></tr>)}</tbody></table></div></Card>}
        {res.journals.length > 0 && <Card title="Journals worth a second look">
          <div className="table-wrap"><table><thead><tr><th>Document</th><th>Date</th><th className="num">Amount</th><th>Why</th></tr></thead>
            <tbody>{res.journals.map(j => <tr key={j.document}><td>{j.document}</td><td>{j.date}</td><td className="num">{money(j.amount)}</td><td>{j.reasons.join("; ")}</td></tr>)}</tbody></table></div></Card>}
        <Card title="Postings in the last three days of each month" note="A heavy share can mean results are being shaped at period end.">
          <div className="table-wrap"><table><thead><tr><th>Month</th><th className="num">Total debits</th><th className="num">Last three days</th><th className="num">Share</th><th>Note</th></tr></thead>
            <tbody>{res.period_end.map(m => <tr key={m.month}><td>{m.month}</td><td className="num">{money(m.total)}</td><td className="num">{money(m.last_three_days)}</td><td className="num">{m.share_percent}%</td><td className={m.reason ? "cx-over-text" : ""}>{m.reason}</td></tr>)}</tbody></table></div></Card>
        <Card title="Largest movements"><div className="table-wrap"><table><thead><tr><th>Account</th><th className="num">This period</th><th className="num">Earlier period</th><th className="num">Change</th></tr></thead>
          <tbody>{res.top_movements.map(a => <tr key={a.account}><td>{a.code} {a.name}</td><td className="num">{money(a.current)}</td><td className="num">{money(a.prior)}</td><td className="num">{money(a.change)}</td></tr>)}</tbody></table></div></Card>
      </>}
    </div>
  );
}
