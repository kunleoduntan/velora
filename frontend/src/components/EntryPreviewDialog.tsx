import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import Dialog from "../ui/Dialog";

interface Row { account: string; account_label: string; debit: string; credit: string; base_debit?: string; base_credit?: string; party?: string | null; description?: string | null; cost_centre?: string | null; event?: string }
interface Preview { status: "Posted" | "Preview" | "Unavailable" | "None"; note: string; currency: string; base_currency: string; rows: Row[]; total_debit: string; total_credit: string; total_base_debit: string; total_base_credit: string; balanced: boolean; posting_date?: string; exchange_rate?: string }

const money = (v: string | undefined) => { const n = Number(v ?? 0); return n === 0 ? "" : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };

/** The accounting entries of a document in one clean table: the posted entries once submitted, the entries it will post while it is a draft. */
export default function EntryPreviewDialog({ doctype, name, onClose }: { doctype: string; name: string; onClose: () => void }) {
  const [data, setData] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.entryPreview(doctype, name).then((d) => setData(d as Preview)).catch((e) => setError(errorMessage(e))); }, [doctype, name]);
  const foreign = !!data && data.currency !== data.base_currency;
  return (
    <Dialog title={`Accounting entries — ${doctype} ${name}`} onClose={onClose} wide footer={<button type="button" className="btn primary" onClick={onClose}>Close</button>}>
      {error && <div className="error" role="alert">{error}</div>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && (
        <div className="entry-preview">
          <p className={data.status === "Preview" ? "entry-note preview" : "entry-note"}><strong>{data.status === "Posted" ? "Posted" : data.status === "Preview" ? "Preview — not posted yet" : ""}</strong>{data.status === "Posted" || data.status === "Preview" ? " · " : ""}{data.note}</p>
          {data.rows.length > 0 && (
            <div className="grid-scroll">
              <table className="dgrid">
                <thead><tr><th>Account</th><th>Party</th><th>Details</th><th className="num">Debit ({data.currency})</th><th className="num">Credit ({data.currency})</th>{foreign && <><th className="num">Debit ({data.base_currency})</th><th className="num">Credit ({data.base_currency})</th></>}</tr></thead>
                <tbody>
                  {data.rows.map((r, i) => (
                    <tr key={i}><td>{r.account_label}</td><td>{r.party ?? ""}</td><td>{r.description ?? ""}</td>
                      <td className="num">{money(r.debit)}</td><td className="num">{money(r.credit)}</td>
                      {foreign && <><td className="num">{money(r.base_debit)}</td><td className="num">{money(r.base_credit)}</td></>}</tr>
                  ))}
                </tbody>
                <tfoot><tr><th colSpan={3}>Total</th><th className="num">{money(data.total_debit)}</th><th className="num">{money(data.total_credit)}</th>{foreign && <><th className="num">{money(data.total_base_debit)}</th><th className="num">{money(data.total_base_credit)}</th></>}</tr></tfoot>
              </table>
            </div>
          )}
          {data.rows.length > 0 && <p className={data.balanced ? "muted" : "error"} role={data.balanced ? undefined : "alert"}>{data.balanced ? "Debits equal credits." : "Debits and credits do not agree — do not submit until this is resolved."}</p>}
        </div>
      )}
    </Dialog>
  );
}
