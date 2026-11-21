import { useEffect, useState } from "react";
import { errorMessage, investments } from "../api";
import type { Portfolio } from "../api";
import { Bars, Card, Kpi, money, pct, today } from "./centre";

/** The whole investment book on one screen: what is held, where the money sits, what is coming due, and what needs attention. */
export default function InvestmentPortfolio() {
  const [asOf, setAsOf] = useState(today());
  const [data, setData] = useState<Portfolio | null>(null), [error, setError] = useState(""), [note, setNote] = useState(""), [busy, setBusy] = useState(false);
  const load = (date = asOf) => { setError(""); investments.portfolio(date).then(setData).catch(e => setError(errorMessage(e))); };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  async function accrue() {
    setBusy(true); setNote(""); setError("");
    try {
      const r = await investments.accrueAll(asOf);
      setNote(r.made.length ? `Income recognised in ${r.made.length} transaction${r.made.length === 1 ? "" : "s"}.` : "Nothing new to accrue.");
      if (r.failed.length) setError(r.failed.map(f => `${f.investment}: ${f.error}`).join(" · "));
      load();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const k = data?.kpis;
  return (
    <div className="panel">
      <div className="page-head">
        <div><h1>Investment Portfolio</h1><p className="muted">Money market, bonds, equities, funds and property in one view.{data ? ` ${data.currency_note}` : ""}</p></div>
        <div className="head-actions"><a className="rbtn" href="#/app/Investment/new">New investment</a><a className="rbtn" href="#/app/Investment%20Transaction/new">Record transaction</a></div>
      </div>
      <div className="brc-bar">
        <label>As at<input type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /></label>
        <button className="rbtn" onClick={() => load()}>Refresh</button>
        <button className="rbtn primary" disabled={busy} onClick={() => void accrue()}>{busy ? "Working…" : "Accrue income to this date"}</button>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {note && <div className="success" role="status">{note}</div>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && k && <>
        <div className="brc-kpis">
          <Kpi label="Carrying value" value={money(k.carrying)} />
          <Kpi label="Cost" value={money(k.cost)} />
          <Kpi label="Unrealised gain / loss" value={money(k.unrealised)} tone={k.unrealised < 0 ? "bad" : undefined} />
          <Kpi label="Income receivable" value={money(k.accrued_receivable)} />
          <Kpi label="Income this year" value={money(k.income_ytd)} />
          <Kpi label="Tax withheld this year" value={money(k.tax_withheld_ytd)} />
          <Kpi label="Average yield" value={pct(k.weighted_yield)} />
          <Kpi label="Holdings" value={k.holdings} />
        </div>
        {data.alerts.length > 0 && <Card title="Needs attention">
          <ul className="cx-alerts">{data.alerts.map((a, i) => <li key={i} className={`cx-alert cx-${a.severity}`}>{a.message}</li>)}</ul>
        </Card>}
        <div className="admin-grid">
          <Card title="By asset group" note={data.limits.asset_group_percent ? `Limit ${data.limits.asset_group_percent}% per group` : undefined}><Bars items={data.by_group.map(g => ({ label: g.label, value: g.amount, flag: g.over_limit, note: pct(g.percent) }))} mark="over limit" /></Card>
          <Card title="By investment type"><Bars items={data.by_class.map(g => ({ label: g.label, value: g.amount, note: pct(g.percent) }))} /></Card>
          <Card title="By counterparty" note={data.limits.counterparty_percent ? `Limit ${data.limits.counterparty_percent}% per counterparty` : undefined}><Bars items={data.by_counterparty.map(g => ({ label: g.label, value: g.amount, flag: g.over_limit, note: pct(g.percent) }))} mark="over limit" /></Card>
          <Card title="Maturity ladder" note="Fixed-income holdings by time to maturity."><Bars items={data.ladder.map(l => ({ label: l.label, value: l.amount, note: `${l.count}` }))} /></Card>
        </div>
        {data.upcoming.length > 0 && <Card title="Coming up (next 90 days)">
          <div className="table-wrap"><table><thead><tr><th>Date</th><th>Event</th><th>Investment</th><th className="num">Amount</th></tr></thead>
            <tbody>{data.upcoming.map((u, i) => <tr key={i}><td>{u.date}</td><td>{u.event}</td><td><a href={`#/app/Investment/${encodeURIComponent(u.investment)}`}>{u.name}</a></td><td className="num">{u.amount ? money(u.amount) : ""}</td></tr>)}</tbody></table></div>
        </Card>}
        <Card title="Holdings">
          {data.holdings.length === 0 ? <p className="muted">No active investments. Create one to get started.</p> :
            <div className="table-wrap"><table><thead><tr><th>Investment</th><th>Type</th><th>Counterparty</th><th className="num">Carrying value</th><th className="num">Yield</th><th>Matures</th><th className="num">Receivable</th></tr></thead>
              <tbody>{data.holdings.map(h => <tr key={h.name}>
                <td><a href={`#/app/Investment/${encodeURIComponent(h.name)}`}>{h.investment_name}</a></td><td>{h.investment_class}</td><td>{h.counterparty ?? ""}</td>
                <td className="num">{money(h.carrying_amount)}</td><td className="num">{pct(h.effective_yield)}</td>
                <td className={h.days_to_maturity != null && h.days_to_maturity < 0 ? "brc-bad" : ""}>{h.maturity_date ?? ""}{h.days_to_maturity != null && h.days_to_maturity >= 0 && h.days_to_maturity <= 30 ? <small> in {h.days_to_maturity}d</small> : null}</td>
                <td className="num">{money(h.accrued_receivable)}</td></tr>)}</tbody></table></div>}
        </Card>
      </>}
    </div>
  );
}
