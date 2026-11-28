import { askConfirm, askPrompt, askAlert } from "../ui/ask";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, bankRec, errorMessage } from "../api";
import type { BankCompute, BankGroup, BankLine, BankRecord, BankWorkbench } from "../api";

const num = (v: unknown) => Number(v ?? 0);
const money = (v: unknown, cur = "") => `${cur} ${num(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
const signedLine = (l: BankLine) => (l.direction === "Receipt" ? 1 : -1) * num(l.amount);
type Tab = "review" | "unmatched" | "matched" | "statement";

export default function BankReconciliationCentre() {
  const [accounts, setAccounts] = useState<string[]>([]);
  const [account, setAccount] = useState("");
  const [wb, setWb] = useState<BankWorkbench | null>(null);
  const [tab, setTab] = useState<Tab>("review");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selLines, setSelLines] = useState<string[]>([]);
  const [selRecs, setSelRecs] = useState<string[]>([]);
  const [toDate, setToDate] = useState(new Date().toISOString().slice(0, 10));
  const [closing, setClosing] = useState("");
  const [opening, setOpening] = useState("");
  const [stmt, setStmt] = useState<BankCompute | null>(null);

  useEffect(() => {
    api.list("Bank Account", { fields: ["name"], limit: 200 }).then(r => { const names = r.map(x => String(x.name)); setAccounts(names); if (names.length === 1) setAccount(names[0]); }).catch(e => setError(errorMessage(e)));
  }, []);

  const load = useCallback(async () => {
    if (!account) { setWb(null); return; }
    setBusy(true); setError("");
    try { setWb(await bankRec.workbench(account, toDate)); setSelLines([]); setSelRecs([]); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }, [account, toDate]);
  useEffect(() => { load(); }, [load]);

  async function act(fn: () => Promise<unknown>, done?: string) {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); if (done) setNotice(done); await load(); } catch (e) { setError(errorMessage(e)); setBusy(false); }
  }

  async function upload(file: File) {
    const buf = new Uint8Array(await file.arrayBuffer());
    let bin = ""; buf.forEach(b => { bin += String.fromCharCode(b); });
    await act(async () => {
      const r = await bankRec.importStatement({ bank_account: account, filename: file.name, content_base64: btoa(bin) });
      const m = r.matching || {};
      setNotice(`${r.created} lines imported (${r.duplicates_skipped || 0} already present). Matched ${m.confirmed || 0} automatically, ${m.suggested || 0} to review, ${m.coded || 0} coded for posting.`);
      if (r.closing_balance != null) setClosing(String(r.closing_balance));
      if (r.opening_balance != null) setOpening(String(r.opening_balance));
    });
  }

  const cur = wb?.currency || "";
  const lineSum = useMemo(() => (wb?.unmatched_lines || []).filter(l => selLines.includes(l.id)).reduce((a, l) => a + signedLine(l), 0), [wb, selLines]);
  const recSum = useMemo(() => (wb?.unmatched_records || []).filter(r => selRecs.includes(r.id)).reduce((a, r) => a + num(r.signed), 0), [wb, selRecs]);
  const diff = Math.round((lineSum - recSum) * 100) / 100;
  const canMatch = (selLines.length > 0 || selRecs.length > 0) && diff === 0 && selLines.length + selRecs.length > 1;
  const toggle = (list: string[], set: (v: string[]) => void, id: string) => set(list.includes(id) ? list.filter(x => x !== id) : [...list, id]);
  const coded = (wb?.unmatched_lines || []).filter(l => l.proposed_account && !l.posting_batch);

  async function computeStatement() {
    setBusy(true); setError("");
    try { setStmt(await bankRec.compute(account, toDate, closing || "0", opening || undefined)); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  const lineRow = (l: BankLine) => (
    <label className="brc-row" key={l.id}>
      <input type="checkbox" checked={selLines.includes(l.id)} onChange={() => toggle(selLines, setSelLines, l.id)} />
      <span>{l.date}</span>
      <span>{l.description || l.reference || l.id}<small>{l.reference}{l.proposed_account ? ` · coded → ${l.proposed_account}` : ""}{l.posting_batch ? ` · posted via ${l.posting_batch}` : ""}</small></span>
      <span className={`brc-amt ${l.direction === "Receipt" ? "brc-ok" : "brc-bad"}`}>{l.direction === "Receipt" ? "" : "−"}{money(l.amount)}</span>
    </label>
  );
  const recRow = (r: BankRecord) => (
    <label className="brc-row" key={r.id}>
      <input type="checkbox" checked={selRecs.includes(r.id)} onChange={() => toggle(selRecs, setSelRecs, r.id)} />
      <span>{r.date}</span>
      <span>{r.description || r.party || r.id}<small>{r.reference} {r.source}</small></span>
      <span className={`brc-amt ${num(r.signed) >= 0 ? "brc-ok" : "brc-bad"}`}>{money(r.signed)}</span>
    </label>
  );
  const groupCard = (g: BankGroup, actions: React.ReactNode) => (
    <article className="brc-group" key={g.group}>
      <header><strong>{g.method}</strong><span className="brc-pill">{Math.round(g.confidence)}% confidence</span></header>
      {g.reason && <p className="muted">{g.reason}</p>}
      <div className="brc-two"><div>{g.lines.map(l => <div className="brc-row" key={l.id}><span /><span>{l.date}</span><span>{l.description || l.reference}</span><span className="brc-amt">{l.direction === "Receipt" ? "" : "−"}{money(l.amount)}</span></div>)}{!g.lines.length && <p className="muted">No statement line (ledger-only pair)</p>}</div>
        <div>{g.records.map(r => <div className="brc-row" key={r.id}><span /><span>{r.date}</span><span>{r.description || r.party || r.id}<small>{r.source}</small></span><span className="brc-amt">{money(r.signed)}</span></div>)}</div></div>
      <div className="brc-bar">{actions}</div>
    </article>
  );

  return (
    <main className="panel">
      <header className="page-head"><div><h1>Bank Reconciliation</h1><p className="muted">Import the statement, let Velora match it, review only the exceptions, then finalise.</p></div>
        <button className="rbtn" onClick={load} disabled={busy || !account}>{busy ? "Working…" : "Refresh"}</button></header>
      {error && <div className="error" role="alert">{error}</div>}
      {notice && <div className="notice" role="status">{notice}</div>}
      <div className="brc-bar">
        <label>Bank account<select value={account} onChange={e => setAccount(e.target.value)}><option value="">Select…</option>{accounts.map(a => <option key={a}>{a}</option>)}</select></label>
        <label>Reconcile up to<input type="date" value={toDate} onChange={e => setToDate(e.target.value)} /></label>
        <label>Statement file (CSV, Excel, OFX, MT940)<input type="file" accept=".csv,.xlsx,.xlsm,.ofx,.qfx,.sta,.mt940,.txt" disabled={!account || busy} onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} /></label>
        <button className="rbtn primary" disabled={!account || busy} onClick={() => act(() => bankRec.auto(account), "Matching run complete.")}>Run auto-match</button>
        <button className="rbtn" disabled={!account || busy || !coded.length} onClick={() => act(async () => { const r = await bankRec.post(account); setNotice(r.batch ? `${r.lines} lines posted through ${r.batch} — awaiting approval if your authority rules require it.` : "Nothing to post."); })}>Post {coded.length} coded line{coded.length === 1 ? "" : "s"}</button>
      </div>
      {wb && <>
        <section className="brc-kpis">
          <div className="brc-kpi"><span>Ledger balance</span><strong>{money(wb.ledger_balance, cur)}</strong></div>
          <div className="brc-kpi"><span>To review</span><strong>{wb.suggestions.length}</strong></div>
          <div className="brc-kpi"><span>Unmatched statement lines</span><strong>{wb.unmatched_lines.length}</strong></div>
          <div className="brc-kpi"><span>Unmatched ledger entries</span><strong>{wb.unmatched_records.length}</strong></div>
          <div className="brc-kpi"><span>Matched groups</span><strong>{wb.matched_total}</strong></div>
        </section>
        <div className="brc-tabs" role="tablist">{(["review", "unmatched", "matched", "statement"] as Tab[]).map(t => <button key={t} className="rbtn" aria-pressed={tab === t} onClick={() => setTab(t)}>{{ review: `Review (${wb.suggestions.length})`, unmatched: "Unmatched", matched: "Matched", statement: "Reconciliation statement" }[t]}</button>)}</div>

        {tab === "review" && <section>
          {wb.suggestions.length > 1 && <button className="rbtn" onClick={() => act(() => bankRec.confirm(wb.suggestions.map(g => g.group)), "All suggestions accepted.")}>Accept all {wb.suggestions.length}</button>}
          {wb.suggestions.map(g => groupCard(g, <><button className="rbtn primary" onClick={() => act(() => bankRec.confirm([g.group]))}>Accept</button><button className="rbtn" onClick={() => act(() => bankRec.reject([g.group]))}>Not a match</button></>))}
          {!wb.suggestions.length && <p className="muted">Nothing waiting for review.</p>}
        </section>}

        {tab === "unmatched" && <section>
          <div className="brc-diff" aria-live="polite">Selected: statement {money(lineSum)} · ledger {money(recSum)} · difference <strong className={diff === 0 ? "brc-ok" : "brc-bad"}>{money(diff)}</strong>
            <span className="brc-bar" style={{ display: "inline-flex", marginLeft: 12 }}>
              <button className="rbtn primary" disabled={!canMatch || busy} onClick={() => act(() => bankRec.match(account, selLines, selRecs), "Matched.")}>Match selected</button>
              <button className="rbtn" disabled={!selLines.length || busy} onClick={async () => { const reason = await askPrompt("Why are these statement lines ignored?"); if (reason) act(() => bankRec.ignore(selLines, reason), "Ignored."); }}>Ignore lines…</button></span></div>
          <div className="brc-two">
            <div><h2>Bank statement</h2><div className="brc-list">{wb.unmatched_lines.map(lineRow)}{!wb.unmatched_lines.length && <p className="muted" style={{ padding: 10 }}>All statement lines are matched.</p>}</div></div>
            <div><h2>Ledger ({wb.gl_account})</h2><div className="brc-list">{wb.unmatched_records.map(recRow)}{!wb.unmatched_records.length && <p className="muted" style={{ padding: 10 }}>All ledger entries are matched.</p>}</div></div>
          </div>
          {wb.ignored_lines.length > 0 && <details><summary>{wb.ignored_lines.length} ignored lines</summary>{wb.ignored_lines.map(l => <div className="brc-row" key={l.id}><span /><span>{l.date}</span><span>{l.description}<small>{l.ignore_reason}</small></span><button className="rbtn" onClick={() => act(() => bankRec.restore([l.id]))}>Restore</button></div>)}</details>}
        </section>}

        {tab === "matched" && <section>
          {wb.matched.map(g => groupCard(g, g.locked ? <span className="muted">Locked by a submitted reconciliation</span> : <button className="rbtn" onClick={() => act(() => bankRec.unmatch([g.group]))}>Unmatch</button>))}
          {!wb.matched.length && <p className="muted">Nothing matched yet.</p>}
        </section>}

        {tab === "statement" && <section>
          <div className="brc-bar">
            <label>Statement opening balance<input value={opening} onChange={e => setOpening(e.target.value)} inputMode="decimal" /></label>
            <label>Statement closing balance<input value={closing} onChange={e => setClosing(e.target.value)} inputMode="decimal" /></label>
            <button className="rbtn primary" onClick={computeStatement} disabled={busy}>Calculate</button>
            <a className="rbtn" href="#/app/Bank Reconciliation">Open Bank Reconciliation records</a>
          </div>
          {stmt && <>
            <div className="brc-kpis">
              <div className="brc-kpi"><span>Statement closing</span><strong>{money(closing, cur)}</strong></div>
              <div className="brc-kpi"><span>+ Deposits in transit</span><strong>{money(stmt.deposits_in_transit)}</strong></div>
              <div className="brc-kpi"><span>− Outstanding payments</span><strong>{money(stmt.outstanding_payments)}</strong></div>
              <div className="brc-kpi"><span>Adjusted bank</span><strong>{money(stmt.adjusted_bank_balance)}</strong></div>
              <div className="brc-kpi"><span>Ledger balance</span><strong>{money(stmt.ledger_balance)}</strong></div>
              <div className="brc-kpi"><span>Adjusted book</span><strong>{money(stmt.adjusted_book_balance)}</strong></div>
              <div className="brc-kpi"><span>Variance</span><strong className={num(stmt.variance) === 0 ? "brc-ok" : "brc-bad"}>{money(stmt.variance)}</strong></div>
              <div className="brc-kpi"><span>Match rate</span><strong>{stmt.match_rate}%</strong></div>
            </div>
            {num(stmt.statement_check) !== 0 && <div className="error">The statement lines do not roll opening to closing: difference {money(stmt.statement_check)}. A line is missing or duplicated.</div>}
            <p className={num(stmt.variance) === 0 ? "brc-ok" : "brc-bad"}>{num(stmt.variance) === 0 ? "Reconciled. Create the Bank Reconciliation record to lock these matches." : "Not yet reconciled: resolve the unmatched items or check the closing balance."}</p>
            <div className="brc-list">{stmt.items.map((i, n) => <div className="brc-row" key={n}><span /><span>{i.item_date}</span><span>{i.category}<small>{i.description} {i.reference}</small></span><span className="brc-amt">{money(i.amount)}</span></div>)}</div>
          </>}
        </section>}
      </>}
      {!account && <p className="muted">Choose a bank account to begin.</p>}
    </main>
  );
}
