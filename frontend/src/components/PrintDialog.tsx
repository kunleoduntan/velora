import { useEffect, useState } from "react";
import { api, errorMessage, getCompany } from "../api";

export function printUrl(formatId: string, doctype: string, names: string[], pdf = false): string {
  const co = getCompany();
  const base = names.length === 1
    ? `/api/print/${encodeURIComponent(formatId)}/${encodeURIComponent(doctype)}/${encodeURIComponent(names[0])}${pdf ? "/pdf" : ""}`
    : `/api/print-batch/${encodeURIComponent(formatId)}/${encodeURIComponent(doctype)}${pdf ? "/pdf" : ""}?names=${encodeURIComponent(names.join(","))}`;
  return co ? `${base}${base.includes("?") ? "&" : "?"}company=${encodeURIComponent(co)}` : base;
}

/** Print one document, or several from the list, using the print format designed for the DocType (the built-in Standard page when none is designed). */
export default function PrintDialog({ doctype, names, onClose }: { doctype: string; names: string[]; onClose: () => void }) {
  const [choices, setChoices] = useState<{ id: string; name: string; builtin?: boolean }[]>([]);
  const [picked, setPicked] = useState(""), [error, setError] = useState("");
  useEffect(() => { api.printChoices(doctype).then(c => { setChoices(c); setPicked(c[0]?.id ?? ""); }).catch(e => setError(errorMessage(e))); }, [doctype]);
  const go = (pdf: boolean) => { if (!picked) return; window.open(printUrl(picked, doctype, names, pdf), "_blank", "noopener"); onClose(); };
  const title = names.length === 1 ? `Print ${doctype} ${names[0]}` : `Print ${names.length} ${doctype} documents`;
  return (
    <div className="overlay" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        <header><h2>{title}</h2></header>
        <div className="dialog-body">
          {error && <div className="error" role="alert">{error}</div>}
          <fieldset className="print-choices"><legend>Print format</legend>
            {choices.map(c => <label key={c.id} className="field-inline"><input type="radio" name="print-format" checked={picked === c.id} onChange={() => setPicked(c.id)} /> {c.name}{c.builtin ? " (built-in)" : ""}</label>)}
          </fieldset>
          {names.length > 1 && <p className="muted">Each document starts on its own page. Documents you may not print are listed at the top and skipped.</p>}
        </div>
        <footer>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn" disabled={!picked} onClick={() => go(true)}>PDF</button>
          <button type="button" className="btn primary" disabled={!picked} onClick={() => go(false)}>Print</button>
        </footer>
      </div>
    </div>
  );
}
