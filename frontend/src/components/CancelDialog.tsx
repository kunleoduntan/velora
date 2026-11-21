import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

interface Props {
  doctype: string;
  name: string;
  /** Called after the document (and, with Cancel All, everything that depended on it) has been cancelled. */
  onDone: () => void;
  onClose: () => void;
}

type Dependent = { doctype: string; name: string; via?: string };

/**
 * Cancel a submitted document the ERPNext way: say why, see what else depends on it, then cancel it (or cancel it together with
 * the documents that depend on it). Cancelling removes the document's ledger postings; nothing is left to reverse.
 */
export default function CancelDialog({ doctype, name, onDone, onClose }: Props) {
  const [reason, setReason] = useState("");
  const [dependents, setDependents] = useState<Dependent[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api.linkedDocuments(doctype, name).then((r) => { if (live) setDependents(r.dependents); }, (e) => { if (live) { setDependents([]); setError(errorMessage(e)); } });
    return () => { live = false; };
  }, [doctype, name]);

  const blocked = (dependents?.length ?? 0) > 0;
  const go = async () => {
    if (!reason.trim()) { setError("A cancellation reason is required."); return; }
    setBusy(true); setError("");
    try {
      if (blocked) await api.cancelAll(doctype, name, reason.trim());
      else await api.action(doctype, name, "cancel", reason.trim());
      onDone();
    } catch (e) { setError(errorMessage(e)); setBusy(false); }
  };

  return (
    <div className="overlay" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={`Cancel ${doctype}`}>
        <header><h2>Cancel {doctype} {name}</h2></header>
        <div className="dialog-body">
          <p className="muted">Cancelling removes this document's postings from the ledgers and keeps the document as Cancelled. You can amend it afterwards to post a corrected version.</p>
          {dependents === null && <p className="muted">Checking what depends on this document…</p>}
          {blocked && (
            <div role="status">
              <p><strong>{dependents!.length} other submitted document{dependents!.length === 1 ? "" : "s"} depend on this one.</strong> They will be cancelled first:</p>
              <ul>{dependents!.map((d) => <li key={`${d.doctype}:${d.name}`}>{d.doctype} <a href={`#/app/${encodeURIComponent(d.doctype)}/${encodeURIComponent(d.name)}`} target="_blank" rel="noreferrer">{d.name}</a></li>)}</ul>
            </div>
          )}
          <label className="field"><span>Reason for cancelling</span>
            <textarea value={reason} rows={3} autoFocus onChange={(e) => setReason(e.target.value)} aria-label="Reason for cancelling" /></label>
          {error && <div className="error" role="alert">{error}</div>}
        </div>
        <footer>
          <button type="button" className="btn" disabled={busy} onClick={onClose}>Keep Document</button>
          <button type="button" className="btn danger" disabled={busy || dependents === null} onClick={go}>
            {blocked ? `Cancel All (${dependents!.length + 1} documents)` : "Cancel Document"}</button>
        </footer>
      </div>
    </div>
  );
}
