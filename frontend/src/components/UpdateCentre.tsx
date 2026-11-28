import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage, updateCentre } from "../api";
import type { UpdateJob, UpdateState } from "../api";
import DatabaseTune from "./DatabaseTune";

const icon = (s: string) => ({ done: "✔", running: "⏳", failed: "✖", skipped: "–", pending: "·" } as Record<string, string>)[s] ?? "·";

/** Drop wheels in one folder, see what is newer, and install everything with one button. The work runs in the background and survives a restart. */
export default function UpdateCentre() {
  const [st, setSt] = useState<UpdateState | null>(null);
  const [job, setJob] = useState<UpdateJob | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [restart, setRestart] = useState("");
  const [confirming, setConfirming] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try { const s = await updateCentre.state(); setSt(s); setRestart(r => r || s.restart_command); setJob(s.running ?? s.last ?? null); setError(""); }
    catch (e) { setError(`${errorMessage(e)} (if an update is restarting the service, this clears by itself)`); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {                                                   // follow a running job; keep trying through a restart
    if (job?.state !== "running") return;
    const t = setInterval(() => { void load(); }, 3000);
    return () => clearInterval(t);
  }, [job?.state, load]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true); setError(""); setNote("");
    try { for (const f of Array.from(files)) await updateCentre.upload(f); setNote(`${files.length} file${files.length === 1 ? "" : "s"} added to the updates folder.`); await load(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function run() {
    setBusy(true); setError(""); setNote(""); setConfirming(false);
    try { await updateCentre.run(); setNote("Update started. It keeps running even if the service restarts."); await load(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  if (!st) return <div className="panel"><h1>Update Centre</h1>{error ? <div className="error" role="alert">{error}</div> : <p className="muted">Loading…</p>}</div>;
  const running = st.running?.state === "running";
  return (
    <div className="panel publish-panel">
      <div className="page-head"><div className="titles"><h1>Update Centre</h1><span className="muted">Put new wheels in the updates folder, then press Install updates. Backups are taken automatically.</span></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      {note && <div className="success" role="status">{note}</div>}
      {st.update_available && !running && <div className="banner amended" role="status"><b>A new update is ready to install.</b></div>}

      <section className="admin-card">
        <h2>Installed now</h2>
        <p>Velora <strong>{st.current.velora}</strong>{Object.entries(st.current.apps).map(([a, v]) => <span key={a}> · {a} <strong>{v}</strong></span>)}</p>
      </section>

      <section className="admin-card">
        <h2>Updates folder</h2>
        <p className="muted">Copy files into <code>{st.drop_folder}</code> (File Explorer, scp, or the button below). Only the newest file of each package is used.</p>
        <input ref={input} type="file" accept=".whl" multiple hidden aria-label="Choose wheel files" onChange={e => { void upload(e.target.files); e.target.value = ""; }} />
        <div className="fe-tools"><button className="rbtn" disabled={busy || running} onClick={() => input.current?.click()}>Upload wheel files</button><button className="rbtn" onClick={() => void load()}>Refresh</button></div>
        {st.files.length === 0 && <p className="muted">The folder is empty.</p>}
        {st.files.map(f => (
          <article className="recruitment-row" key={f.file}>
            <div><strong>{f.file}</strong><p className="muted">{f.note || `${f.package}: installed ${f.installed ?? "none"} → file ${f.version}`}</p></div>
            <span>{f.newer ? "Newer — will install" : "Already installed"}</span>
            <button className="rbtn" disabled={running} onClick={async () => { try { await updateCentre.remove(f.file); await load(); } catch (e) { setError(errorMessage(e)); } }}>Remove</button>
          </article>))}
      </section>

      <section className="admin-card">
        <h2>Install</h2>
        <label htmlFor="uc-restart">Command that restarts Velora afterwards (optional)</label>
        <div className="fe-tools"><input id="uc-restart" value={restart} onChange={e => setRestart(e.target.value)} placeholder="sudo systemctl restart velora" style={{ flex: 1, minWidth: 240 }} />
          <button className="rbtn" onClick={async () => { try { await updateCentre.saveSettings(restart); setNote("Restart command saved."); } catch (e) { setError(errorMessage(e)); } }}>Save</button></div>
        {!confirming
          ? <button className="rbtn primary" disabled={busy || running || !st.update_available} onClick={() => setConfirming(true)}>{running ? "Update running…" : "Install updates"}</button>
          : <div className="admin-card" role="dialog" aria-label="Confirm update">
              <p>The system goes into maintenance mode, every database is backed up and upgraded, then the service restarts. Continue?</p>
              <div className="fe-tools"><button className="rbtn primary" disabled={busy} onClick={run}>Yes, install now</button><button className="rbtn" onClick={() => setConfirming(false)}>Cancel</button></div>
            </div>}
        {!st.update_available && !running && <p className="muted">Nothing newer than what is installed.</p>}
      </section>

      {job && (
        <section className="admin-card" aria-label="Update progress">
          <h2>{job.state === "running" ? "Update in progress" : job.state === "done" ? "Last update finished" : "Last update failed"}</h2>
          {job.plan?.map(p => <p key={p} className="muted">{p}</p>)}
          <ol className="uc-steps">{job.steps.map(s => <li key={s.name}><span aria-hidden="true">{icon(s.state)}</span> {s.name}{s.detail ? <small className="muted"> — {s.detail}</small> : null}</li>)}</ol>
          {job.error && <div className="error" role="alert">{job.error}</div>}
          <details open={job.state !== "done"}><summary>Log</summary><pre style={{ maxHeight: 280, overflow: "auto" }}>{job.log.join("\n")}</pre></details>
        </section>)}
      <DatabaseTune />
    </div>
  );
}
