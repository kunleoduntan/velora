import { useEffect, useState } from "react";
import { api, errorMessage, type PullCandidate } from "../api";

/** ERPNext's "Get Items From": tick one or several open documents of the same party and add what is still open on them to this draft. */
export default function PullItemsDialog({ target, source, party, onCancel, onPull }: {
  target: string; source: string; party: string; onCancel: () => void;
  onPull: (result: { header: Record<string, unknown>; lines: Record<string, unknown>[] }) => void;
}) {
  const [rows, setRows] = useState<PullCandidate[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [txt, setTxt] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      api.pullCandidates({ target_doctype: target, source_doctype: source, party: party || undefined, txt: txt || undefined })
        .then((r) => { if (live) { setRows(r); setError(""); } }).catch((e) => { if (live) setError(errorMessage(e)); });
    }, txt ? 250 : 0);
    return () => { live = false; clearTimeout(t); };
  }, [target, source, party, txt]);

  // the first tick fixes the party: documents of anyone else cannot be merged with it
  const chosenParty = picked.length ? rows?.find((r) => r.name === picked[0])?.party : party;
  const toggle = (name: string) => setPicked((cur) => cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name]);

  async function go() {
    setBusy(true); setError("");
    try { onPull(await api.pullLines({ target_doctype: target, source_doctype: source, names: picked, party: party || undefined })); }
    catch (e) { setError(errorMessage(e)); setBusy(false); }
  }

  return (
    <div className="overlay" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="dialog pull-dialog" role="dialog" aria-modal="true" aria-label={`Get items from ${source}`}>
        <header><h2>Get items from {source}</h2></header>
        <div className="dialog-body">
          <input type="search" aria-label="Search documents" placeholder={`Search ${source}…`} value={txt} onChange={(e) => setTxt(e.target.value)} />
          {error && <div className="error" role="alert">{error}</div>}
          {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? <p className="muted">No open {source} with items left to take{party ? ` for ${party}` : ""}.</p> : (
            <div className="grid-scroll"><table className="dgrid">
              <thead><tr><th /><th>{source}</th><th>{source.includes("Order") || source === "Delivery Note" ? (source.startsWith("Sales") || source === "Delivery Note" ? "Customer" : "Supplier") : "Supplier"}</th><th>Date</th><th>Open lines</th><th>Open qty</th></tr></thead>
              <tbody>{rows.map((r) => {
                const blocked = !!chosenParty && r.party !== chosenParty;
                return (
                  <tr key={r.name} className={picked.includes(r.name) ? "selected" : undefined}>
                    <td><input type="checkbox" aria-label={`Select ${r.name}`} disabled={blocked} checked={picked.includes(r.name)} onChange={() => toggle(r.name)} /></td>
                    <td><strong>{r.name}</strong></td><td>{r.party_name || r.party}</td><td>{r.date}</td><td>{r.open_lines}</td><td>{Number(r.open_quantity)}</td>
                  </tr>);
              })}</tbody></table></div>)}
        </div>
        <footer>
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn primary" disabled={!picked.length || busy} onClick={() => void go()}>{busy ? "Getting items…" : `Get items${picked.length ? ` (${picked.length})` : ""}`}</button>
        </footer>
      </div>
    </div>
  );
}
