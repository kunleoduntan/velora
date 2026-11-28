import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

/** Sample approval workflows offered by the installed apps. They install inactive: review one, then switch it on (Finance Settings > Approvals does both). */
export default function StarterWorkflows({ onInstalled }: { onInstalled: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const load = () => api.workflowTemplates().then(setItems).catch(e => setError(errorMessage(e)));
  useEffect(() => { load(); }, []);
  const missing = items.filter(i => !i.installed);
  if (!items.length) return null;
  async function install(names: string[]) {
    setBusy(true); setError(""); setMessage("");
    try {
      const done = await api.installWorkflowTemplates(names);
      setMessage(done.length ? `Installed ${done.length} sample workflow${done.length === 1 ? "" : "s"} (inactive). Open one below to change who approves it, then switch it on.` : "Nothing new to install.");
      setPicked([]); await load(); onInstalled();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <section className="admin-card wide" aria-labelledby="starter-wf">
    <h2 id="starter-wf">Sample approval workflows</h2>
    <p className="muted">
      {missing.length
        ? `${missing.length} document type${missing.length === 1 ? " has" : "s have"} no sample workflow yet. Samples install inactive, so nothing changes until you switch one on.`
        : "Every document type that can carry an approval has a workflow. Which documents need approval is set in Finance Settings > Approvals."}
    </p>
    {error && <div className="error" role="alert">{error}</div>}{message && <div className="success" role="status">{message}</div>}
    {missing.length > 0 && <div className="wf-starter-actions">
      <button className="rbtn primary" disabled={busy} onClick={() => install(missing.map(m => m.name))}>Install all {missing.length}</button>
      <button className="rbtn" disabled={busy || !picked.length} onClick={() => install(picked)}>Install selected ({picked.length})</button>
      <button className="rbtn" onClick={() => setOpen(o => !o)}>{open ? "Hide list" : "Choose which"}</button>
    </div>}
    {open && <div className="wf-starter-list">
      {items.map(i => <label key={i.name} className={i.installed ? "wf-starter done" : "wf-starter"}>
        <input type="checkbox" disabled={i.installed} checked={picked.includes(i.name)} onChange={e => setPicked(p => e.target.checked ? [...p, i.name] : p.filter(x => x !== i.name))} />
        <span><b>{i.doctype}</b><small>{i.installed ? "Installed" : `Approved by ${i.approvers.join(", ")}`}</small></span>
      </label>)}
    </div>}
  </section>;
}
