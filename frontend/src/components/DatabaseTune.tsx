import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

const mb = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`;

/** One-click database tuning. It only changes how the database finds data (indexes, statistics, free space); no record is touched. */
export default function DatabaseTune() {
  const [plan, setPlan] = useState<{ database: string; size_bytes: number; indexes_to_create: string[] } | null>(null);
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.databaseTune>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const look = () => api.databaseTunePreview().then(setPlan).catch((e) => setError(errorMessage(e)));
  useEffect(() => { void look(); }, []);

  async function run() {
    setBusy(true); setError(""); setResult(null);
    try { setResult(await api.databaseTune()); await look(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <section className="admin-card" aria-label="Database tuning">
      <h2>Database speed</h2>
      <p className="muted">Tuning adds the indexes your lists and searches need, refreshes the database's statistics and gives back unused space. Your data is not changed. It is safe to run at any time; a quiet moment is best because it can take a minute on a large database.</p>
      {plan && <p>{plan.database === "postgresql" ? "PostgreSQL" : plan.database === "sqlite" ? "SQLite" : plan.database} database, {mb(plan.size_bytes)}. {plan.indexes_to_create.length ? `${plan.indexes_to_create.length} index${plan.indexes_to_create.length === 1 ? "" : "es"} can be added.` : "Every index is already in place."}</p>}
      <button type="button" className="rbtn primary" disabled={busy} onClick={() => void run()}>{busy ? "Tuning… please wait" : "Tune the database now"}</button>
      {error && <div className="error" role="alert">{error}</div>}
      {result && (
        <div className="success" role="status">
          Done in {result.seconds} seconds. {result.indexes_created.length} index{result.indexes_created.length === 1 ? "" : "es"} added; size {mb(result.size_before)} → {mb(result.size_after)}.
          {result.notes.map((n) => <div key={n} className="muted">{n}</div>)}
        </div>)}
    </section>
  );
}
