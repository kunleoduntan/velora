import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api";

type AppRow = { name: string; version: string; installed: boolean; required_apps: string[]; required_velora: string; path: string };

export default function ApplicationLifecycleManager() {
  const [site, setSite] = useState("");
  const [apps, setApps] = useState<AppRow[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [validation, setValidation] = useState<Record<string, any>>({});
  const refresh = useCallback(async () => {
    try { const result = await api.lifecycleCatalog(); setSite(result.site); setApps(result.apps); setError(""); }
    catch (e) { setError(errorMessage(e)); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  async function validate(app: AppRow) {
    setBusy(app.name); setError(""); setNotice("");
    try { const report = await api.validateApplication(app.name); setValidation(v => ({...v,[app.name]:report})); setNotice(`${app.name}: ${report.valid ? "validation passed" : "validation found errors"}.`); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(""); }
  }
  async function change(app: AppRow, action: "install" | "uninstall") {
    const prompt = action === "install"
      ? `Install ${app.name} on ${site}? Installation validates dependencies and applies the app schema.`
      : `Uninstall ${app.name} from ${site}? Its tables and records will be retained.`;
    if (!window.confirm(prompt)) return;
    setBusy(app.name); setError(""); setNotice("");
    try {
      const result = action === "install" ? await api.lifecycleInstall(app.name) : await api.lifecycleUninstall(app.name);
      setNotice(action === "install" ? `${app.name} installed on ${site}. ${Array.isArray(result.migration_plan) ? `${result.migration_plan.length} schema operation(s) applied.` : ""}` : `${app.name} uninstalled. Application data was retained.`);
      await refresh();
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(""); }
  }
  return <section className="section"><div className="builder-body">
    <div className="object-studio-heading"><div><h3>Application Lifecycle Manager</h3><p className="muted">Manage installation, package health, declared dependencies and version compatibility for the active site. Validate an application before installing it.</p></div><button className="rbtn" onClick={() => void refresh()} disabled={!!busy}>Refresh</button></div>
    {site && <p className="muted">Active site: <strong>{site}</strong></p>}
    {error && <div className="error" role="alert">{error}</div>}{notice && <div className="success" role="status">{notice}</div>}
    <div className="table-wrap"><table className="dgrid"><thead><tr><th>Application</th><th>Version</th><th>Dependencies</th><th>Status</th><th>Package health</th><th>Actions</th></tr></thead><tbody>
      {apps.map((a) => <tr key={a.name}><td><strong>{a.name}</strong><div className="muted">{a.path}</div></td><td>{a.version}</td><td>{a.required_apps.join(", ") || "None"}{a.required_velora && <div className="muted">Velora {a.required_velora}</div>}</td><td>{a.installed ? <span className="status-pill">Installed</span> : "Available"}</td><td>{validation[a.name] ? <span className={validation[a.name].valid ? "status-pill" : "error"}>{validation[a.name].valid ? "Valid" : "Issues"} · {validation[a.name].file_count ?? 0} files</span> : <span className="muted">Not checked</span>}{validation[a.name]?.errors?.length ? <details><summary>Errors ({validation[a.name].errors.length})</summary><ul>{validation[a.name].errors.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></details> : null}{validation[a.name]?.warnings?.length ? <details><summary>Warnings ({validation[a.name].warnings.length})</summary><ul>{validation[a.name].warnings.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></details> : null}</td><td><button className="rbtn" disabled={!!busy} onClick={() => void validate(a)}>{busy === a.name ? "Checking…" : "Validate"}</button> {a.installed ? <button className="rbtn danger" disabled={!!busy} onClick={() => void change(a, "uninstall")}>{busy === a.name ? "Working…" : "Uninstall"}</button> : <button className="rbtn primary" disabled={!!busy} onClick={() => void change(a, "install")}>{busy === a.name ? "Working…" : "Install"}</button>}</td></tr>)}
      {!apps.length && <tr><td colSpan={6} className="muted">No application packages are registered in this workspace.</td></tr>}
    </tbody></table></div>
    <p className="muted">Safety: uninstall removes the app from the site's installed-app registry only. Database tables and records are deliberately retained. Package validation is static inspection; it does not execute app code. Source upgrades remain controlled by the reviewed deployment workflow.</p>
  </div></section>;
}
