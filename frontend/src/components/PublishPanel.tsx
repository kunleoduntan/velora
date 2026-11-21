import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, type PublishCatalog, type PublishProfile } from "../api";

const blank = { id: "", label: "", source: "upload" as "app" | "upload", app: "", company_id: "", repo_url: "https://github.com/kunleoduntan/velora", branch: "main", token: "" };

/** Publish an app, or the whole Velora project, to GitHub with one click. Each profile is tied to the company it belongs to. */
export default function PublishPanel() {
  const [cat, setCat] = useState<PublishCatalog | null>(null);
  const [sel, setSel] = useState<string>("");
  const [form, setForm] = useState({ ...blank });
  const [creating, setCreating] = useState(false);
  const [msg, setMsg] = useState("Update");
  const [status, setStatus] = useState<{ changes: string[]; last_commit: string | null; ready: boolean } | null>(null);
  const [cmds, setCmds] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [newToken, setNewToken] = useState("");
  const file = useRef<HTMLInputElement>(null);

  const load = useCallback(async (keep?: string) => {
    try { const c = await api.publishCatalog(); setCat(c); const id = keep ?? sel; if (id && c.profiles.some(p => p.id === id)) setSel(id); else setSel(c.profiles[0]?.id ?? ""); }
    catch (e) { setError(errorMessage(e)); }
  }, [sel]);
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const profile: PublishProfile | undefined = cat?.profiles.find(p => p.id === sel);
  useEffect(() => { setStatus(null); setCmds(""); setConfirming(false); setNewToken(""); if (sel) api.publishStatus(sel).then(setStatus).catch(() => undefined); }, [sel]);

  async function run(fn: () => Promise<string | void>) {
    setBusy(true); setError(""); setOk("");
    try { const m = await fn(); if (m) setOk(m); if (sel) api.publishStatus(sel).then(setStatus).catch(() => undefined); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); setConfirming(false); }
  }

  if (!cat) return <div className="panel"><h1>Publish to GitHub</h1>{error ? <div className="error" role="alert">{error}</div> : <p className="muted">Loading…</p>}</div>;
  const active = cat.companies.filter(c => c.status === "active");

  return (
    <div className="panel publish-panel">
      <div className="page-head"><div className="titles"><h1>Publish to GitHub</h1><span className="muted">Push an app, or the Velora project, to its repository. Every profile names the company it belongs to.</span></div></div>
      {!cat.git && <div className="error" role="alert">git is not installed on this server. Run <code>sudo apt install git</code> once, then reload this page.</div>}
      {error && <div className="error" role="alert">{error}</div>}
      {ok && <div className="success" role="status">{ok}</div>}

      <section className="admin-card">
        <h2>Profiles</h2>
        {cat.profiles.length === 0 && <p className="muted">No profile yet. Create one below: it remembers the project, company, repository and token, so publishing is one click.</p>}
        <div className="fe-tools">
          {cat.profiles.map(p => <button key={p.id} className={`rbtn${p.id === sel && !creating ? " primary" : ""}`} onClick={() => { setSel(p.id); setCreating(false); }}>{p.label || p.id}</button>)}
          <button className="rbtn" onClick={() => { setCreating(true); setForm({ ...blank, company_id: active[0]?.id ?? "" }); }}>New profile</button>
        </div>
      </section>

      {creating && (
        <section className="admin-card" aria-label="New publish profile">
          <h2>New profile</h2>
          <label htmlFor="pp-id">Profile name</label>
          <input id="pp-id" value={form.id} onChange={e => setForm({ ...form, id: e.target.value.toLowerCase() })} placeholder="velora-core (lower-case, digits, dashes)" />
          <label htmlFor="pp-company">Company this belongs to</label>
          <select id="pp-company" value={form.company_id} onChange={e => setForm({ ...form, company_id: e.target.value })}>
            <option value="">Choose a company</option>{active.map(c => <option key={c.id} value={c.id}>{c.name} ({c.id})</option>)}
          </select>
          <label htmlFor="pp-source">What are you publishing?</label>
          <select id="pp-source" value={form.source} onChange={e => setForm({ ...form, source: e.target.value as "app" | "upload" })}>
            <option value="upload">A project folder from my computer (upload as zip)</option>
            <option value="app" disabled={cat.apps.length === 0}>An app that is already on this server</option>
          </select>
          {form.source === "app" && <>
            <label htmlFor="pp-app">App</label>
            <select id="pp-app" value={form.app} onChange={e => setForm({ ...form, app: e.target.value })}><option value="">Choose an app</option>{cat.apps.map(a => <option key={a}>{a}</option>)}</select></>}
          <label htmlFor="pp-repo">Repository address</label>
          <input id="pp-repo" value={form.repo_url} onChange={e => setForm({ ...form, repo_url: e.target.value })} />
          <label htmlFor="pp-branch">Branch</label>
          <input id="pp-branch" value={form.branch} onChange={e => setForm({ ...form, branch: e.target.value })} />
          <label htmlFor="pp-token">GitHub access token</label>
          <input id="pp-token" type="password" autoComplete="off" value={form.token} onChange={e => setForm({ ...form, token: e.target.value })} placeholder="Stored encrypted; never shown again" />
          <p className="muted">Create a token at GitHub → Settings → Developer settings → Personal access tokens. Allow it to write to this repository only.</p>
          <div className="fe-tools">
            <button className="rbtn primary" disabled={busy || !form.id || !form.company_id || !form.repo_url || (form.source === "app" && !form.app)}
              onClick={() => run(async () => { const p = await api.publishSave({ ...form, label: form.id }); setCreating(false); await load(p.id); return "Profile saved."; })}>Save profile</button>
            <button className="rbtn" onClick={() => setCreating(false)}>Cancel</button>
          </div>
        </section>
      )}

      {profile && !creating && (
        <section className="admin-card" aria-label={`Publish ${profile.id}`}>
          <h2>{profile.label || profile.id}</h2>
          <dl className="pub-facts">
            <dt>Company</dt><dd><strong>{profile.company_name}</strong> <small>{profile.company_id}</small></dd>
            <dt>Project</dt><dd>{profile.source === "app" ? `App “${profile.app}” on this server` : "Uploaded project folder"}</dd>
            <dt>Repository</dt><dd>{profile.repo_url} <small>branch {profile.branch}</small></dd>
            <dt>Token</dt><dd>{profile.has_token ? "saved (hidden)" : "not set"}</dd>
            <dt>Last push</dt><dd>{profile.last_push ? `${profile.last_push.at.replace("T", " ").replace("+00:00", " UTC")} by ${profile.last_push.by} (${profile.last_push.commit})` : "never"}</dd>
          </dl>

          {profile.source === "upload" && <div className="fe-tools">
            <input ref={file} type="file" accept=".zip,application/zip" hidden aria-label="Choose project zip" onChange={e => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void run(async () => { const r = await api.publishUpload(profile.id, f); return `Uploaded ${r.files} files${r.skipped_count ? ` (${r.skipped_count} left out: caches, node_modules, secrets)` : ""}.`; }); }} />
            <button className="rbtn" disabled={busy} onClick={() => file.current?.click()}>Upload project zip</button>
            <span className="muted">Zip the project folder on your computer (right-click → Compress). A top-level folder is removed automatically.</span>
          </div>}

          {status && <p className="muted">{status.ready ? (status.changes.length ? `${status.changes.length} change${status.changes.length === 1 ? "" : "s"} waiting to be published.` : "No changes since the last commit.") : "Nothing uploaded yet."}{status.last_commit ? ` Last commit: ${status.last_commit}` : ""}</p>}

          <label htmlFor="pp-token2">{profile.has_token ? "Replace the GitHub access token" : "GitHub access token (required before you can push)"}</label>
          <div className="fe-tools">
            <input id="pp-token2" type="password" autoComplete="off" value={newToken} onChange={e => setNewToken(e.target.value)} placeholder="Paste a personal access token" style={{ flex: 1, minWidth: 220 }} />
            <button className="rbtn" disabled={busy || newToken.trim().length < 8}
              onClick={() => run(async () => { await api.publishSave({ id: profile.id, label: profile.label, source: profile.source, app: profile.app || "", company_id: profile.company_id, repo_url: profile.repo_url, branch: profile.branch, token: newToken.trim() }); setNewToken(""); await load(profile.id); return "Token saved. You can now test the connection and push."; })}>Save token</button>
          </div>
          {(!cat.git || !profile.has_token || (profile.source === "upload" && status && !status.ready)) && (
            <p className="error" role="status">Push is unavailable because: {[
              !cat.git ? "git cannot be found by the Velora service (install git, then restart the service)" : "",
              !profile.has_token ? "no access token is saved for this profile (add it above)" : "",
              profile.source === "upload" && status && !status.ready ? "no project zip has been uploaded yet" : "",
            ].filter(Boolean).join("; ")}.</p>)}
          <label htmlFor="pp-msg">Commit message</label>
          <input id="pp-msg" value={msg} onChange={e => setMsg(e.target.value)} />
          {!confirming
            ? <div className="fe-tools">
                <button className="rbtn primary" disabled={busy || !cat.git || !profile.has_token} onClick={() => setConfirming(true)}>Push to GitHub</button>
                <button className="rbtn" disabled={busy || !profile.has_token} onClick={() => run(async () => { const r = await api.publishTest(profile.id); return `Connection works. Branches: ${r.branches.join(", ") || "(empty repository)"}`; })}>Test connection</button>
                <button className="rbtn" onClick={() => api.publishCommands(profile.id).then(r => setCmds(r.commands)).catch(e => setError(errorMessage(e)))}>Show commands</button>
                <button className="rbtn danger" disabled={busy} onClick={() => { if (window.confirm(`Delete profile ${profile.id}? Your repository is not touched.`)) void run(async () => { await api.publishDelete(profile.id); await load(""); return "Profile deleted."; }); }}>Delete profile</button>
              </div>
            : <div className="admin-card" role="dialog" aria-label="Confirm push">
                <p>Push <strong>{profile.source === "app" ? profile.app : "the uploaded project"}</strong> for <strong>{profile.company_name}</strong> to <strong>{profile.repo_url}</strong> (branch <strong>{profile.branch}</strong>)?</p>
                <div className="fe-tools">
                  <button className="rbtn primary" disabled={busy} onClick={() => run(async () => { const r = await api.publishPush(profile.id, msg); await load(profile.id); return r.new_commit ? `Pushed commit ${r.commit} to ${r.to}.` : `Already up to date (${r.commit}). Nothing new to push.`; })}>Yes, push now</button>
                  <button className="rbtn" onClick={() => setConfirming(false)}>Cancel</button>
                </div>
              </div>}
          {cmds && <><label htmlFor="pp-cmds">Run these on your own computer inside the project folder instead</label>
            <textarea id="pp-cmds" readOnly rows={8} value={cmds} style={{ width: "100%", fontFamily: "monospace" }} onFocus={e => e.currentTarget.select()} /></>}
          {status && status.changes.length > 0 && <details><summary>Files that will be included ({status.changes.length})</summary><pre>{status.changes.join("\n")}</pre></details>}
        </section>
      )}
    </div>
  );
}
