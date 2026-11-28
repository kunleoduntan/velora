import { useEffect, useState } from "react";
import { api, errorMessage, type CreatorBody, type CreatorReport, type CreatorResult } from "../api";

/** Paste DocType JSON (Velora's own, or a Frappe DocType export), preview what would be created, then create real, version-controlled DocType files. */
export default function DocTypeCreator() {
  const [status, setStatus] = useState<{ available: boolean; apps: string[] } | null>(null);
  const [text, setText] = useState("");
  const [app, setApp] = useState("");
  const [module, setModule] = useState("");
  const [name, setName] = useState("");
  const [child, setChild] = useState(false);
  const [submittable, setSubmittable] = useState(false);
  const [track, setTrack] = useState(false);
  const [autoField, setAutoField] = useState("");
  const [conflict, setConflict] = useState<"error" | "skip">("error");
  const [report, setReport] = useState<CreatorReport | null>(null);
  const [result, setResult] = useState<CreatorResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.devtoolsStatus().then((s) => { setStatus(s); if (s.apps.length) setApp(s.apps[0]); }).catch((e) => setError(errorMessage(e))); }, []);
  const invalidate = () => { setReport(null); setResult(null); };

  const body = (): CreatorBody => ({
    json: text, app, module: module || undefined, name: name || undefined, on_conflict: conflict,
    ...(child ? { is_child: true } : {}), ...(submittable ? { is_submittable: true } : {}), ...(track ? { track_changes: true } : {}),
    ...(autoField ? { is_autoname: true, autoname_field_name: autoField } : {}),
  });
  function syntaxOk(): boolean {
    try { JSON.parse(text); return true; } catch (e) { setError(`That is not valid JSON: ${(e as Error).message}`); return false; }
  }
  async function preview() {
    setError(""); setResult(null);
    if (!syntaxOk()) return setReport(null);
    setBusy(true);
    try { setReport(await api.creatorPreview(body())); } catch (e) { setError(errorMessage(e)); setReport(null); } finally { setBusy(false); }
  }
  async function create() {
    setError("");
    setBusy(true);
    try { setResult(await api.creatorCreate(body())); setReport(null); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  function format() {
    if (!syntaxOk()) return;
    setText(JSON.stringify(JSON.parse(text), null, 2));
  }

  if (!status) return <div className="panel">{error ? <div className="error" role="alert">{error}</div> : "Loading…"}</div>;
  if (!status.available) return <div className="panel"><h1>DocType Creator</h1><p>The DocType Creator writes files into an app, so it needs <strong>developer mode</strong> and a System Manager. A platform administrator can switch developer mode on under <a href="#/platform">Company Administration</a>.</p></div>;

  return (
    <div className="creator">
      <header className="page-head"><div className="titles"><h1>DocType Creator</h1><span className="muted">Create DocTypes from JSON: Velora's format or a Frappe DocType export</span></div></header>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="section"><div className="builder-body">
        <div className="field"><label htmlFor="dc-json">DocType JSON</label>
          <textarea id="dc-json" rows={14} spellCheck={false} value={text} placeholder='{"doctypes": [{"name": "Invoice Line", "module": "Sales", "istable": 1, "fields": [...]}, ...]}' onChange={(e) => { setText(e.target.value); invalidate(); }} /></div>
        <div className="creator-opts">
          <div className="field"><label htmlFor="dc-app">Create in app</label>
            <select id="dc-app" value={app} onChange={(e) => { setApp(e.target.value); invalidate(); }}>{status.apps.map((a) => <option key={a} value={a}>{a}</option>)}</select></div>
          <div className="field"><label htmlFor="dc-module">Module (if the JSON has none)</label><input id="dc-module" value={module} onChange={(e) => { setModule(e.target.value); invalidate(); }} /></div>
          <div className="field"><label htmlFor="dc-name">DocType name (for a bare list of fields)</label><input id="dc-name" value={name} onChange={(e) => { setName(e.target.value); invalidate(); }} /></div>
          <div className="field"><label htmlFor="dc-auto">Name documents after field</label><input id="dc-auto" value={autoField} placeholder="e.g. title" onChange={(e) => { setAutoField(e.target.value); invalidate(); }} /></div>
          <div className="field"><label htmlFor="dc-conflict">If a DocType already exists</label>
            <select id="dc-conflict" value={conflict} onChange={(e) => { setConflict(e.target.value as "error" | "skip"); invalidate(); }}><option value="error">Stop, and create nothing</option><option value="skip">Skip it, create the rest</option></select></div>
        </div>
        <div className="creator-flags">
          <label><input type="checkbox" checked={child} onChange={(e) => { setChild(e.target.checked); invalidate(); }} /> Child table</label>
          <label><input type="checkbox" checked={submittable} onChange={(e) => { setSubmittable(e.target.checked); invalidate(); }} /> Submittable</label>
          <label><input type="checkbox" checked={track} onChange={(e) => { setTrack(e.target.checked); invalidate(); }} /> Track changes</label>
        </div>
        <div className="ribbon">
          <button type="button" className="rbtn primary" disabled={busy || !text.trim() || !app} onClick={preview}><span>Preview</span></button>
          <button type="button" className="rbtn" disabled={busy || !report?.ok} onClick={create}><span>Create DocTypes</span></button>
          <button type="button" className="rbtn" disabled={!text.trim()} onClick={format}><span>Format JSON</span></button>
        </div>
      </div></div>

      {report && (
        <div className="section" data-testid="creator-report"><div className="builder-body">
          <h3>{report.ok ? `Ready: ${report.doctypes.length} DocType(s)` : "Not ready"} <span className="muted">({report.structure})</span></h3>
          {report.errors.length > 0 && <div className="error" role="alert"><strong>Fix these first (nothing will be created until they are fixed):</strong><ul>{report.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></div>}
          {report.warnings.length > 0 && <div className="intro"><strong>Worth knowing:</strong><ul>{report.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div>}
          {report.skipped.length > 0 && <p className="muted">Skipped (already exist): {report.skipped.join(", ")}</p>}
          {report.doctypes.length > 0 && (
            <table className="dgrid"><thead><tr><th>DocType</th><th>Module</th><th>Fields</th><th>Kind</th><th>Links to</th></tr></thead>
              <tbody>{report.doctypes.map((d) => <tr key={d.name}><td>{d.name}</td><td>{d.module}</td><td>{d.fields}</td><td>{d.child ? "Child table" : d.submittable ? "Submittable" : "DocType"}</td><td>{d.links.join(", ") || "–"}</td></tr>)}</tbody></table>
          )}
          {report.order.length > 1 && <p className="muted">Created in this order: {report.order.join(" → ")} (child tables first)</p>}
        </div></div>
      )}

      {result && (
        <div className="section" data-testid="creator-result"><div className="builder-body">
          <div className="success" role="status">Created {result.created.length} DocType(s){result.skipped.length ? `, skipped ${result.skipped.length}` : ""}.</div>
          <ul>{result.created.map((n) => <li key={n}>{n}: <a href={`#/app/${encodeURIComponent(n)}`}>open list</a> · <a href={`#/settings/layout/${encodeURIComponent(n)}`}>design form</a></li>)}</ul>
          {(result.folders?.length ?? 0) > 0 && <p>Edit the controller (<code>.py</code>) and the client scripts (<code>.js</code>, <code>_list.js</code>): {result.folders!.map((f) => <a key={f} href={`#/files?path=${encodeURIComponent(f)}`}>{f.split("/").pop()}</a>).reduce<React.ReactNode[]>((a, x, i) => (i ? [...a, " · ", x] : [x]), [])} in the File Explorer.</p>}
          {result.migration.length > 0 && <details><summary>Database changes ({result.migration.length})</summary><pre>{result.migration.join("\n")}</pre></details>}
          <p className="muted">{result.note}</p>
        </div></div>
      )}
    </div>
  );
}
