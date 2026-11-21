import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

type Repo = { repository: string; status: string; path: string; packages: { name?: string; version?: string; file?: string; sha256?: string; status: string; error?: string }[] };

export default function ApplicationMarketplace() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    api.marketplace().then((rows) => { if (active) setRepos(rows); })
      .catch((e) => { if (active) setError(errorMessage(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  return <section className="section"><div className="builder-body">
    <div className="object-studio-heading"><div><h3>Application Marketplace</h3>
      <p className="muted">Browse validated packages from locally configured repositories. Packages are inspected without executing their code.</p>
    </div><span className="studio-count">{repos.reduce((n, r) => n + r.packages.length, 0)} package(s)</span></div>
    {loading && <p className="muted">Loading configured repositories…</p>}
    {error && <div className="error" role="alert">{error}</div>}
    {!loading && !error && repos.length === 0 && <p className="muted">No repositories configured. Add one with <code>velora marketplace add-source NAME /path/to/repository</code>.</p>}
    {repos.map((repo) => <article className="extension-card" key={repo.repository}>
      <div className="object-studio-heading"><div><h4>{repo.repository}</h4><p className="muted">{repo.path}</p></div><span className="status-pill">{repo.status}</span></div>
      {repo.packages.length ? <div className="table-wrap"><table className="dgrid"><thead><tr><th>Application</th><th>Version</th><th>Package</th><th>Validation</th><th>SHA-256</th></tr></thead><tbody>
        {repo.packages.map((pkg) => <tr key={pkg.file}><td>{pkg.name ?? "—"}</td><td>{pkg.version ?? "—"}</td><td>{pkg.file}</td><td>{pkg.status}{pkg.error ? `: ${pkg.error}` : ""}</td><td><code>{pkg.sha256?.slice(0, 16) ?? "—"}…</code></td></tr>)}
      </tbody></table></div> : <p className="muted">No ZIP packages found.</p>}
      <p className="muted">Import validated source with <code>velora marketplace import {repo.repository} PACKAGE.zip --sha256 DIGEST</code>. Then validate and install explicitly.</p>
    </article>)}
  </div></section>;
}
