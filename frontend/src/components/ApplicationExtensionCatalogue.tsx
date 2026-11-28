import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import type { AppExtensionManifest } from "../api";

export default function ApplicationExtensionCatalogue() {
  const [apps, setApps] = useState<AppExtensionManifest[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    api.appExtensions().then((rows) => { if (active) setApps(rows); })
      .catch((e) => { if (active) setError(errorMessage(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  return <section className="section"><div className="builder-body">
    <div className="object-studio-heading"><div><h3>UI Extension Catalogue</h3>
      <p className="muted">Inspects frontend assets and runtime hooks declared by applications installed on the active company. This catalogue does not execute or install third-party code.</p>
    </div><span className="studio-count">{apps.length} installed app(s)</span></div>
    {loading && <p className="muted">Loading extension manifests…</p>}
    {error && <div className="error" role="alert">{error}</div>}
    {!loading && !error && apps.length === 0 && <p className="muted">No installed application extensions are registered.</p>}
    {apps.map((app) => <article className="extension-card" key={app.name}>
      <div className="object-studio-heading"><div><h4>{app.name} <span className="muted">v{app.version}</span></h4>
        <p className="muted">{app.lifecycle_hooks.length} lifecycle hook(s) · {app.scheduler_events.length} scheduler group(s) · {app.doc_events ? "Document events enabled" : "No document events"}</p>
      </div><span className="status-pill">Installed</span></div>
      <h5>Frontend assets</h5>
      {app.frontend_assets.length ? <div className="table-wrap"><table className="dgrid"><thead><tr><th>Asset</th><th>Type</th><th>Size</th><th>SHA-256</th></tr></thead><tbody>
        {app.frontend_assets.map((asset) => <tr key={asset.path}><td>{asset.path}</td><td>{asset.type}</td><td>{asset.size_bytes ?? 0} bytes</td><td><code>{asset.sha256 ? asset.sha256.slice(0, 16) + "…" : "Not available"}</code></td></tr>)}
      </tbody></table></div> : <p className="muted">No frontend assets declared.</p>}
      <p className="muted">Lifecycle: {app.lifecycle_hooks.join(", ") || "None"} · Job handlers: {app.job_handlers.join(", ") || "None"}</p>
    </article>)}
  </div></section>;
}
