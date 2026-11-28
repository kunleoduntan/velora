import { useEffect, useMemo, useState } from "react";
import { api, errorMessage, type DbDocResult, type DbGrid, type DbSqlResult, type DbStructure, type DbTable } from "../api";

const WRITES = /^\s*(--[^\n]*\n\s*)*(insert|update|delete|replace|create|alter|drop|truncate|reindex)\b/i;
const cell = (v: unknown) => (v === null ? "∅" : typeof v === "object" ? JSON.stringify(v) : String(v));

function Grid({ grid, selectable, selected, onSelect }: { grid: DbGrid; selectable?: boolean; selected?: Set<number>; onSelect?: (i: number) => void }) {
  return (
    <div className="db-grid" role="region" aria-label="Results" tabIndex={0}>
      <table>
        <thead><tr>{selectable && <th />}{grid.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {grid.rows.map((r, i) => (
            <tr key={i}>
              {selectable && <td><input type="checkbox" aria-label={`Select row ${i + 1}`} checked={!!selected?.has(i)} onChange={() => onSelect?.(i)} /></td>}
              {r.map((v, j) => <td key={j} title={cell(v)}>{cell(v)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {grid.rows.length === 0 && <p className="muted">No rows.</p>}
    </div>
  );
}

/** Browse tables, run SQL (changes are previewed first and need the unlock) and clear a stuck document. Every rule is enforced by the server. */
export default function DatabaseTools({ unlocked, needUnlock }: { unlocked: boolean; needUnlock: (then?: () => void) => boolean }) {
  const [companies, setCompanies] = useState<{ id: string; name: string; status: string }[]>([]);
  const [company, setCompany] = useState("");
  const [tables, setTables] = useState<DbTable[]>([]);
  const [filter, setFilter] = useState("");
  const [table, setTable] = useState("");
  const [structure, setStructure] = useState<DbStructure | null>(null);
  const [grid, setGrid] = useState<DbGrid | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [sql, setSql] = useState("");
  const [result, setResult] = useState<DbSqlResult | null>(null);
  const [previewed, setPreviewed] = useState<{ sql: string; plan: string } | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [doc, setDoc] = useState({ doctype: "", name: "", action: "cancel" });
  const [docPreview, setDocPreview] = useState<DbDocResult | null>(null);
  const [confirm, setConfirm] = useState("");

  useEffect(() => {
    api.platformCompanies().then(c => {
      const active = c.filter((x: any) => x.status === "active");
      setCompanies(active); if (active[0]) setCompany(active[0].id);
    }).catch(e => setError(errorMessage(e)));
  }, []);
  useEffect(() => {
    if (!company) return;
    setTable(""); setStructure(null); setGrid(null); setError("");
    api.consoleTables(company).then(setTables).catch(e => setError(errorMessage(e)));
  }, [company]);

  async function guarded<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true); setError(""); setMessage("");
    try { return await fn(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  async function openTable(name: string, off = 0) {
    const r = await guarded(() => api.consoleTable(company, name, { offset: off }));
    if (!r) return;
    setTable(name); setStructure(r.structure); setGrid(r.data); setOffset(off); setSelected(new Set());
  }

  const isWrite = WRITES.test(sql);
  const changedSincePreview = !previewed || previewed.sql !== sql.trim();

  async function run() {
    const r = await guarded(() => api.consoleSql(company, sql, "read"));
    if (r) { setResult(r); setPreviewed(null); }
  }
  function preview() {
    if (!needUnlock(() => void preview())) return;
    void (async () => {
      const r = await guarded(() => api.consoleSql(company, sql, "preview"));
      if (r?.plan) { setResult(r); setPreviewed({ sql: sql.trim(), plan: r.plan }); }
    })();
  }
  async function apply() {
    if (!previewed) return;
    const r = await guarded(() => api.consoleSql(company, sql, "apply", previewed.plan));
    if (r) {
      setResult(r); setPreviewed(null);
      setMessage(`Done. ${r.affected ?? "Some"} row(s) affected. A safety backup was made first.`);
      if (table) void openTable(table, offset);
    }
  }

  function deleteSelected() {
    if (!grid || !structure || structure.primary_key.length !== 1 || selected.size === 0) return;
    const pk = structure.primary_key[0], col = grid.columns.indexOf(pk);
    const ids = [...selected].map(i => `'${String(grid.rows[i][col]).replace(/'/g, "''")}'`).join(", ");
    setSql(`DELETE FROM "${table}" WHERE "${pk}" IN (${ids})`); setResult(null); setPreviewed(null);
  }

  async function docStep(mode: "preview" | "apply") {
    if (mode === "preview" && !needUnlock(() => void docStep("preview"))) return;
    const r = await guarded(() => api.consoleDocument(company, { ...doc, mode, plan: docPreview?.plan, confirm }));
    if (!r) return;
    if (mode === "preview") setDocPreview(r);
    else { setDocPreview(null); setConfirm(""); setMessage(`Done: ${r.action}. A safety backup was made first.`); }
  }

  const visible = useMemo(() => tables.filter(t => t.name.toLowerCase().includes(filter.toLowerCase())), [tables, filter]);
  const pages = grid?.total !== undefined ? Math.ceil(grid.total / 50) : 0;

  return (
    <div className="db-tools">
      {error && <div className="error" role="alert">{error}</div>}
      {message && <div className="success" role="status">{message}</div>}
      <label>Company
        <select value={company} onChange={e => setCompany(e.target.value)} aria-label="Company">
          {companies.map(c => <option key={c.id} value={c.id}>{c.name} ({c.id})</option>)}
        </select>
      </label>
      <div className="db-layout">
        <aside className="db-tables" aria-label="Tables">
          <input placeholder="Find a table" value={filter} onChange={e => setFilter(e.target.value)} aria-label="Find a table" />
          <ul>
            {visible.map(t => (
              <li key={t.name}><button className={`rbtn ${t.name === table ? "primary" : ""}`} onClick={() => void openTable(t.name)}>{t.name} <span className="muted">{t.rows ?? "?"}</span></button></li>
            ))}
          </ul>
        </aside>
        <div className="db-main">
          {structure && grid && (
            <section className="admin-card">
              <h2>{table}</h2>
              <p className="muted">{structure.columns.length} columns · {grid.total ?? 0} rows · key: {structure.primary_key.join(", ") || "none"}</p>
              <Grid grid={grid} selectable={structure.primary_key.length === 1} selected={selected} onSelect={i => setSelected(s => { const n = new Set(s); if (n.has(i)) n.delete(i); else n.add(i); return n; })} />
              <div className="fe-tools">
                <button className="rbtn" disabled={offset === 0 || busy} onClick={() => void openTable(table, Math.max(0, offset - 50))}>Previous</button>
                <span className="muted">Page {Math.floor(offset / 50) + 1} of {Math.max(pages, 1)}</span>
                <button className="rbtn" disabled={offset + 50 >= (grid.total ?? 0) || busy} onClick={() => void openTable(table, offset + 50)}>Next</button>
                <button className="rbtn danger" disabled={selected.size === 0} onClick={deleteSelected}>Prepare delete of {selected.size} selected row{selected.size === 1 ? "" : "s"}</button>
              </div>
            </section>
          )}
          <section className="admin-card">
            <h2>SQL</h2>
            <textarea rows={6} value={sql} onChange={e => setSql(e.target.value)} spellCheck={false} aria-label="SQL statement" placeholder="SELECT name, modified FROM tab_customer ORDER BY modified DESC" style={{ width: "100%", fontFamily: "monospace" }} />
            <div className="fe-tools">
              {!isWrite && <button className="rbtn primary" disabled={busy || !sql.trim()} onClick={() => void run()}>Run</button>}
              {isWrite && <button className="rbtn" disabled={busy || !sql.trim()} onClick={preview}>Preview changes</button>}
              {isWrite && <button className="rbtn danger" disabled={busy || changedSincePreview || !unlocked} onClick={() => void apply()}>Apply to the database</button>}
              <span className="muted">One statement at a time. Changes are previewed, then applied after a safety backup.</span>
            </div>
            {result?.kind === "preview" && <div className="warning" role="status">This would affect <strong>{result.would_affect ?? "an unknown number of"}</strong> row(s). {result.note} Nothing has changed yet.</div>}
            {result?.columns && <><Grid grid={{ columns: result.columns, rows: result.rows ?? [], truncated: !!result.truncated, seconds: result.seconds ?? 0 }} />{result.truncated && <p className="muted">Only the first 500 rows are shown.</p>}</>}
          </section>
          <section className="admin-card">
            <h2>Stuck document</h2>
            <p className="muted">Cancel, reopen or remove one document together with its table rows. Postings and links made from it are not undone.</p>
            <div className="fe-tools">
              <input placeholder="Document type, e.g. Sales Invoice" value={doc.doctype} onChange={e => { setDoc({ ...doc, doctype: e.target.value }); setDocPreview(null); }} aria-label="Document type" />
              <input placeholder="Name, e.g. SINV-0001" value={doc.name} onChange={e => { setDoc({ ...doc, name: e.target.value }); setDocPreview(null); }} aria-label="Document name" />
              <select value={doc.action} onChange={e => { setDoc({ ...doc, action: e.target.value }); setDocPreview(null); }} aria-label="Action">
                <option value="cancel">Mark as cancelled</option><option value="draft">Reopen as draft</option><option value="delete">Delete</option>
              </select>
              <button className="rbtn" disabled={busy || !doc.doctype || !doc.name} onClick={() => void docStep("preview")}>Preview</button>
            </div>
            {docPreview && (
              <div className="warning" role="status">
                <p>{docPreview.warning}</p>
                <p>Action: {docPreview.action}. Table rows involved: {Object.values(docPreview.child_rows ?? {}).reduce((a, b) => a + b, 0)}.</p>
                <label>Type <code>{doc.name}</code> to confirm<input value={confirm} onChange={e => setConfirm(e.target.value)} aria-label="Type the document name to confirm" /></label>
                <button className="rbtn danger" disabled={busy || confirm !== doc.name || !unlocked} onClick={() => void docStep("apply")}>Apply</button>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
