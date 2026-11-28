import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import MetadataExtensions from "./MetadataExtensions";
import VisualDocTypeBuilder from "./VisualDocTypeBuilder";
import ApplicationLifecycleManager from "./ApplicationLifecycleManager";
import ApplicationExtensionCatalogue from "./ApplicationExtensionCatalogue";
import ApplicationMarketplace from "./ApplicationMarketplace";
import DeploymentCentre from "./DeploymentCentre";

type Catalog = {
  apps: { name: string; doctype_count: number; doctypes: string[] }[];
  doc_events: { doctype: string; event: string; handlers: string[] }[];
  job_handlers: { name: string; handler: string }[];
  scheduler_events: Record<string, string[]>;
  database_objects: { app?: string; name?: string; type?: string }[];
  doctype_count: number;
};
type Inspection = { name: string; app: string; module: string; controller_module: string; is_submittable: boolean; is_child: boolean; fields: { fieldname: string; fieldtype: string; label: string }[]; api: Record<string, string> };

export default function DeveloperStudio() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [doctype, setDoctype] = useState("");
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [newApp, setNewApp] = useState("");
  const [newModule, setNewModule] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [createdApp, setCreatedApp] = useState("");
  useEffect(() => { api.devtoolsCatalog().then(setCatalog).catch((e) => setError(errorMessage(e))); }, []);
  async function inspect() {
    if (!doctype) return;
    setBusy(true); setError("");
    try { setInspection(await api.devtoolsInspect(doctype)); } catch (e) { setError(errorMessage(e)); setInspection(null); }
    finally { setBusy(false); }
  }
  if (!catalog) return <div className="panel">{error || "Loading Developer Studio…"}</div>;
  return <div className="creator">
    <header className="page-head"><div className="titles"><h1>Developer Studio</h1><span className="muted">Application catalogue, hook declarations and DocType API explorer</span></div></header>
    <section className="object-studio-launchpad" aria-label="Object Studio">
      <div className="object-studio-heading"><div><h2>Graphical Object Studio</h2><p className="muted">Open the visual managers for the framework objects currently available in this release.</p></div><span className="studio-count">{catalog.doctype_count} registered DocTypes</span></div>
      <div className="object-studio-grid">
        <a className="studio-card" href="#/settings/object-manager"><span className="studio-card-icon">▦</span><strong>Company DocTypes</strong><small>Browse, edit, create and archive company-owned DocTypes.</small><span className="studio-card-action">Open object manager →</span></a>
        <a className="studio-card" href="#/settings/doctype-creator"><span className="studio-card-icon">＋</span><strong>Visual DocType Builder</strong><small>Design application DocTypes, fields, conditions and permissions.</small><span className="studio-card-action">Create DocType →</span></a>
        <a className="studio-card" href="#/builder"><span className="studio-card-icon">▤</span><strong>Report Designer</strong><small>Create and manage reusable report definitions.</small><span className="studio-card-action">Open report designer →</span></a>
        <a className="studio-card" href="#/settings/workflows"><span className="studio-card-icon">⑂</span><strong>Workflow Designer</strong><small>Configure approval states, transitions and workflow rules.</small><span className="studio-card-action">Open workflows →</span></a>
        <a className="studio-card" href="#/settings/role-permissions"><span className="studio-card-icon">▤</span><strong>Role & Field Permissions</strong><small>Manage DocType actions, permission levels and field visibility.</small><span className="studio-card-action">Manage permissions →</span></a>
        <a className="studio-card" href="#/dashboards"><span className="studio-card-icon">▥</span><strong>Dashboards</strong><small>View and manage available dashboard experiences.</small><span className="studio-card-action">Open dashboards →</span></a>
        <a className="studio-card" href="#/settings/print-website"><span className="studio-card-icon">▧</span><strong>Print & Website</strong><small>Access print formats and website configuration tools.</small><span className="studio-card-action">Open print & website →</span></a>
      </div>
    </section>
    {error && <div className="error" role="alert">{error}</div>}
    <div className="section"><div className="builder-body"><h3>Application Builder</h3>
      <p className="muted">Generate a new, independent Velora application scaffold inside this workspace. Creation does not automatically install or execute the application.</p>
      <div className="creator-opts">
        <div className="field"><label htmlFor="studio-app-name">App name (lowercase, underscores)</label><input id="studio-app-name" value={newApp} placeholder="e.g. inventory_plus" onChange={(e) => setNewApp(e.target.value)} /></div>
        <div className="field"><label htmlFor="studio-app-module">Default module</label><input id="studio-app-module" value={newModule} placeholder="e.g. Inventory" onChange={(e) => setNewModule(e.target.value)} /></div>
        <div className="field"><label htmlFor="studio-app-title">Application title</label><input id="studio-app-title" value={newTitle} placeholder="e.g. Inventory Plus" onChange={(e) => setNewTitle(e.target.value)} /></div>
      </div>
      <button className="rbtn primary" disabled={busy || !/^[a-z][a-z0-9_]{0,40}$/.test(newApp)} onClick={async () => { setBusy(true); setError(""); setCreatedApp(""); try { const result = await api.createApplication({ name: newApp, module: newModule || undefined, title: newTitle || undefined }); setCreatedApp(`Created ${result.name} at ${result.path}. It has not been installed.`); setNewApp(""); setNewModule(""); setNewTitle(""); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }}>Create application scaffold</button>
      {createdApp && <p className="success" role="status">{createdApp}</p>}
    </div></div>
    <div className="creator-opts">
      <div className="section"><div className="builder-body"><h3>Installed applications</h3>
        <p className="muted">{catalog.apps.length} apps · {catalog.doctype_count} DocTypes</p>
        <table className="dgrid"><thead><tr><th>App</th><th>DocTypes</th><th>Count</th></tr></thead><tbody>
          {catalog.apps.map((a) => <tr key={a.name}><td>{a.name}</td><td>{a.doctypes.join(", ") || "—"}</td><td>{a.doctype_count}</td></tr>)}
        </tbody></table></div></div>
      <div className="section"><div className="builder-body"><h3>DocType API explorer</h3>
        <div className="field"><label htmlFor="studio-doctype">Select DocType</label><select id="studio-doctype" value={doctype} onChange={(e) => { setDoctype(e.target.value); setInspection(null); }}>
          <option value="">Choose a DocType</option>{catalog.apps.flatMap((a) => a.doctypes).sort().map((d) => <option key={d}>{d}</option>)}
        </select></div>
        <button className="rbtn primary" disabled={!doctype || busy} onClick={inspect}>Inspect DocType</button>
        {inspection && <><p><strong>{inspection.name}</strong> · {inspection.app} · {inspection.module}</p>
          <table className="dgrid"><thead><tr><th>Field</th><th>Type</th><th>Label</th></tr></thead><tbody>{inspection.fields.map((f) => <tr key={f.fieldname}><td>{f.fieldname}</td><td>{f.fieldtype}</td><td>{f.label}</td></tr>)}</tbody></table>
          <h4>REST API endpoints</h4><ul>{Object.entries(inspection.api).map(([k, v]) => <li key={k}><code>{v}</code></li>)}</ul>
        </>}
      </div></div>
    </div>
    <div className="section"><div className="builder-body"><h3>Application document hooks</h3>
      {catalog.doc_events.length ? <table className="dgrid"><thead><tr><th>DocType</th><th>Event</th><th>Handlers</th></tr></thead><tbody>{catalog.doc_events.map((h, i) => <tr key={`${h.doctype}-${h.event}-${i}`}><td>{h.doctype}</td><td>{h.event}</td><td>{h.handlers.join(", ")}</td></tr>)}</tbody></table> : <p className="muted">No document event hooks declared.</p>}
      <h3>Background job handlers</h3>{catalog.job_handlers.length ? <ul>{catalog.job_handlers.map((j) => <li key={j.name}><strong>{j.name}</strong> — <code>{j.handler}</code></li>)}</ul> : <p className="muted">No app job handlers declared.</p>}
      <h3>Scheduler events</h3><pre>{JSON.stringify(catalog.scheduler_events, null, 2)}</pre>
    </div></div>
    <ApplicationLifecycleManager />
    <ApplicationExtensionCatalogue />
    <ApplicationMarketplace />\n    <DeploymentCentre />
    <VisualDocTypeBuilder apps={catalog.apps.map((a) => a.name)} />
    <MetadataExtensions doctypes={catalog.apps.flatMap((a) => a.doctypes).sort()} />
    <div className="intro">Metadata extensions are stored in the active company database. App metadata remains version-controlled and is not rewritten by company customisations.</div>
  </div>;
}
