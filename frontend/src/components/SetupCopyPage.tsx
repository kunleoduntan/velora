import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

/** Copy setup (chart of accounts, masters, workflows, permissions) between companies through a file, with a preview before anything is written. */
export default function SetupCopyPage() {
  const [sections, setSections] = useState<any[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [bundle, setBundle] = useState<any>(null);
  const [fileName, setFileName] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { api.setupCopySections().then(setSections).catch(e => setError(errorMessage(e))); }, []);
  const toggle = (id: string) => { setPicked(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id]); setPreview(null); };
  async function run(fn: () => Promise<void>) { setBusy(true); setError(""); setMessage(""); try { await fn(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  const exportFile = () => run(async () => {
    const data = await api.setupCopyExport(picked);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = `velora-setup-${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(url);
    setMessage("Setup file downloaded. Open Setup Copy in the other company and choose it under 'Copy into this company'.");
  });
  const readFile = async (f: File | undefined) => {
    setPreview(null); setBundle(null); setFileName(""); if (!f) return;
    try { const parsed = JSON.parse(await f.text()); setBundle(parsed); setFileName(f.name); setPicked(Object.keys(parsed.sections || {}).filter(id => sections.some(s => s.id === id))); }
    catch { setError("That file could not be read. Choose a setup file exported from Velora."); }
  };
  const doPreview = () => run(async () => setPreview(await api.setupCopyPreview(bundle, picked)));
  const doApply = () => run(async () => {
    const r = await api.setupCopyApply(bundle, picked);
    const updated = (r.copied || []).reduce((n: number, d: any) => n + (d.updated || 0), 0);
    setMessage(r.created || updated
      ? [r.created ? `Copied ${r.created} record${r.created === 1 ? "" : "s"} into this company.` : "", updated ? `Updated ${updated} setting${updated === 1 ? "" : "s"}.` : ""].filter(Boolean).join(" ")
      : "Everything in the file is already here, so nothing was added.");
    setPreview(null);
  });
  const inFile = (id: string) => !bundle || !!bundle.sections?.[id];
  return <div className="panel setup-copy">
    <div className="page-head"><div className="titles"><h1>Setup Copy</h1><span className="muted">Reuse one company's chart of accounts, masters, approval workflows and permissions in another</span></div></div>
    {error && <div className="error" role="alert">{error}</div>}{message && <div className="success" role="status">{message}</div>}
    <div className="admin-grid">
      <section className="admin-card wide">
        <h2>1. Choose what to copy</h2>
        <p className="muted">Only setup is copied. Posted or approved documents never are, and anything that already exists here is left exactly as it is, except that Finance policy updates this company's Finance Settings.</p>
        <div className="sc-sections">
          {sections.map(s => <label key={s.id} className={"sc-section" + (inFile(s.id) ? "" : " off")}>
            <input type="checkbox" checked={picked.includes(s.id)} disabled={!inFile(s.id)} onChange={() => toggle(s.id)} />
            <span><b>{s.label}</b><small>{s.description}</small>
              {s.doctypes?.length > 0 && <small className="muted">{s.doctypes.join(" · ")}</small>}
              {s.skipped?.length > 0 && <small className="muted">Not copied: {s.skipped.map((x: any) => `${x.doctype} (${x.reason})`).join(", ")}</small>}
            </span>
          </label>)}
        </div>
      </section>
      <section className="admin-card">
        <h2>2a. Copy out of this company</h2>
        <p className="muted">Downloads the chosen sections as one file.</p>
        <button className="rbtn primary" disabled={busy || !picked.length || !!bundle} onClick={exportFile}>Download setup file</button>
      </section>
      <section className="admin-card">
        <h2>2b. Copy into this company</h2>
        <p className="muted">Choose a file from another company, check what would change, then copy. It is all or nothing.</p>
        <input type="file" accept="application/json,.json" aria-label="Setup file" onChange={e => readFile(e.target.files?.[0])} />
        {fileName && <p className="muted">File: {fileName}</p>}
        <div className="wf-starter-actions">
          <button className="rbtn" disabled={busy || !bundle || !picked.length} onClick={doPreview}>Check what would change</button>
          <button className="rbtn primary" disabled={busy || !preview || !!preview.blocked?.length || !preview.new} onClick={doApply}>Copy {preview?.new ? `${preview.new} record${preview.new === 1 ? "" : "s"}` : ""}</button>
        </div>
        {preview && <table className="grid-table sc-plan"><thead><tr><th>Item</th><th>New</th><th>Already here</th></tr></thead>
          <tbody>{preview.plan.map((p: any, i: number) => <tr key={i}><td>{p.item}{p.blocked && <small className="error"> {p.blocked}</small>}{!p.blocked && p.note && <small className="muted"> {p.note}</small>}</td><td>{p.kind === "settings" ? "–" : p.new}</td><td>{p.kind === "settings" ? `${p.updates} to update` : p.existing}</td></tr>)}</tbody></table>}
      </section>
    </div>
  </div>;
}
