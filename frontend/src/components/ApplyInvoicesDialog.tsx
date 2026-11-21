import { useState } from "react";
import { api, type OutstandingInvoice } from "../api";

interface Props {
  kind: "Receipt" | "Payment";
  partyType: "Customer" | "Supplier";
  initialParty?: string;
  initialAmount?: number;
  currency?: string;
  reference?: string;
  onCancel: () => void;
  onApply: (lines: Record<string, unknown>[], amount: number) => void;
}

const n = (v: unknown) => Number(v ?? 0);
const money = (v: number) => v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Apply to Invoices: fetch a party's open invoices, allocate an amount across them (by hand or by a chosen rule), and write the lines. */
export default function ApplyInvoicesDialog({ kind, partyType, initialParty = "", initialAmount = 0, currency, reference, onCancel, onApply }: Props) {
  const [party, setParty] = useState(initialParty);
  const [amount, setAmount] = useState(String(initialAmount || ""));
  const [methods, setMethods] = useState<string[]>(["FIFO"]);
  const [method, setMethod] = useState("FIFO");
  const [rows, setRows] = useState<OutstandingInvoice[]>([]);
  const [alloc, setAlloc] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const allocated = rows.reduce((t, r) => t + n(alloc[r.invoice]), 0);
  const total = n(amount);
  const unapplied = total - allocated;

  async function fetchOutstanding() {
    if (!party.trim()) return setError(`Enter the ${partyType} code.`);
    setBusy(true); setError(""); setNote("");
    try {
      const res = await api.settlementOutstanding({ party_type: partyType, party: party.trim(), currency });
      setRows(res.invoices); setMethods(res.methods); setAlloc({});
      if (!res.invoices.length) setNote("No outstanding invoices for this party.");
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }

  async function autoAllocate() {
    if (!(total > 0)) return setError("Enter the amount to allocate first.");
    setBusy(true); setError("");
    try {
      const res = await api.settlementAllocate({ party_type: partyType, party: party.trim(), amount: total, method, currency, reference_text: reference });
      const next: Record<string, string> = {};
      for (const a of res.allocations) next[a.invoice] = String(a.allocate);
      setAlloc(next); setNote(res.explanation);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }

  function edit(invoice: string, value: string, outstanding: number) {
    const v = Math.min(Math.max(n(value), 0), outstanding);
    setAlloc((cur) => ({ ...cur, [invoice]: value === "" ? "" : String(v) }));
  }

  async function apply() {
    if (!(allocated > 0)) return setError("Allocate an amount to at least one invoice.");
    if (allocated - total > 0.005) return setError("The allocated amount exceeds the amount entered.");
    setBusy(true); setError("");
    try {
      const chosen = rows.filter((r) => n(alloc[r.invoice]) > 0).map((r) => ({ invoice: r.invoice, allocate: n(alloc[r.invoice]) }));
      const res = await api.settlementAllocate({ party_type: partyType, party: party.trim(), amount: total, allocations: chosen, currency });
      const lines = res.lines;
      onApply(lines, total);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="overlay" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="dialog wide" role="dialog" aria-modal="true" aria-label="Apply to Invoices">
        <header><h2>Apply {kind} to Invoices</h2></header>
        <div className="dialog-body">
          <div className="grid-3">
            <label className="field"><span>{partyType}</span><input value={party} onChange={(e) => setParty(e.target.value)} aria-label={partyType} /></label>
            <label className="field"><span>Amount</span><input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} aria-label="Amount to allocate" /></label>
            <label className="field"><span>Auto-allocation rule</span>
              <select value={method} onChange={(e) => setMethod(e.target.value)} aria-label="Auto-allocation rule">{methods.map((m) => <option key={m}>{m}</option>)}</select></label>
          </div>
          <div className="popover-actions">
            <button type="button" className="btn" disabled={busy} onClick={fetchOutstanding}>Get Outstanding Invoices</button>
            <button type="button" className="btn primary" disabled={busy || !rows.length} onClick={autoAllocate}>Auto Allocate</button>
            {note && <span className="muted">{note}</span>}
          </div>
          {rows.length > 0 && (
            <div className="table-scroll"><table className="grid-table" aria-label="Outstanding invoices">
              <thead><tr><th>Invoice</th><th>Due</th><th>Status</th><th className="num">Total</th><th className="num">Outstanding</th><th className="num">Allocate</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.invoice}><td>{r.invoice}</td><td>{r.due_date ?? ""}</td><td>{r.payment_status}</td>
                  <td className="num">{money(n(r.invoice_total))}</td><td className="num">{money(n(r.outstanding))}</td>
                  <td className="num"><input type="number" min="0" step="0.01" value={alloc[r.invoice] ?? ""} aria-label={`Allocate to ${r.invoice}`} onChange={(e) => edit(r.invoice, e.target.value, n(r.outstanding))} /></td></tr>))}</tbody>
              <tfoot><tr><td colSpan={5}>Allocated {money(allocated)} of {money(total)}</td><td className="num">{unapplied > 0.005 ? `Unapplied ${money(unapplied)}` : "Fully applied"}</td></tr></tfoot>
            </table></div>
          )}
          {error && <p className="form-error" role="alert">{error}</p>}
        </div>
        <footer>
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn primary" disabled={busy || !(allocated > 0)} onClick={apply}>Apply to Invoices</button>
        </footer>
      </div>
    </div>
  );
}
