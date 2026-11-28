import { useEffect, useMemo, useRef, useState } from "react";
import { api, downloadBlob, errorMessage, type ImportOptions, type ImportReport } from "../api";
import type { Meta } from "../types";
import Icon from "../ui/Icon";

const MODES: { value: ImportOptions["mode"]; label: string; help: string }[] = [
  { value: "insert", label: "Create new records", help: "Every line becomes a new document." },
  { value: "update", label: "Update existing records", help: "Lines must carry the ID (or a unique value to match). Empty cells never erase anything." },
  { value: "upsert", label: "Create or update", help: "Update the ones that exist, create the ones that do not." },
];
const DATES: { value: ImportOptions["date_format"]; label: string }[] = [
  { value: "DMY", label: "Day first: 31/12/2026" }, { value: "MDY", label: "Month first: 12/31/2026" }, { value: "YMD", label: "Year first: 2026-12-31" },
];
const SHOWN = 100;

/** Data Import for any DocType: get the template, choose how, CHECK the file (the real validation, nothing saved), then import. Failed rows come back as a file to fix and re-upload. */
export default function DataImportPage({ doctype }: { doctype: string }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [opts, setOpts] = useState<ImportOptions>({ mode: "insert", submit: false, atomic: false, keep_names: false, date_format: "DMY", match: "" });
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState<"" | "check" | "import" | "template" | "errors">("");
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { api.meta(doctype).then(setMeta).catch((e) => setError(errorMessage(e))); }, [doctype]);
  const uniqueFields = useMemo(() => (meta?.fields ?? []).filter((f) => f.unique && f.fieldtype !== "Table"), [meta]);

  if (!meta) return <div className="panel">{error ? <div className="error" role="alert">{error}</div> : "Loading…"}</div>;
  const canSubmit = meta.is_submittable && meta.permissions.submit;
  const set = (patch: Partial<ImportOptions>) => { setOpts((o) => ({ ...o, ...patch })); setReport(null); };

  async function download() {
    setBusy("template"); setError("");
    try { const f = await api.importTemplate(doctype); downloadBlob(f.blob, f.filename); } catch (e) { setError(errorMessage(e)); } finally { setBusy(""); }
  }
  async function exportAll() {
    setBusy("template"); setError("");
    try { const f = await api.exportData(doctype); downloadBlob(f.blob, f.filename); } catch (e) { setError(errorMessage(e)); } finally { setBusy(""); }
  }
  async function go(dry: boolean) {
    if (!file) return;
    setBusy(dry ? "check" : "import"); setError(""); setReport(null);
    try { setReport(await api.importFile(doctype, file, file.name, opts, dry)); } catch (e) { setError(errorMessage(e)); } finally { setBusy(""); }
  }
  async function failedFile() {
    if (!report) return;
    setBusy("errors");
    try { const f = await api.importErrorsXlsx(report.failed_rows); downloadBlob(f.blob, f.filename); } catch (e) { setError(errorMessage(e)); } finally { setBusy(""); }
  }

  const real = report && !report.dry_run;
  return (
    <div className="panel import-page">
      <header className="page-head">
        <div className="titles"><h1>Import {doctype}</h1><a className="muted" href={`#/app/${encodeURIComponent(doctype)}`}>Back to the list</a></div>
      </header>

      <section className="import-step">
        <h2>1. Get the file ready</h2>
        <p>Download a template with the right headings, fill it in (one document per line), or bring your own Excel file: the columns are matched by name, in any order. A document with several rows (like invoice lines) has its extra rows on the lines <b>under</b> it, with the document's own cells left blank.</p>
        <div className="ribbon">
          <button type="button" className="rbtn" disabled={busy !== ""} onClick={() => download()}><Icon name="sheet" /><span>Excel template</span></button>
          {meta.permissions.export && <>
            <span className="rsep" />
            <button type="button" className="rbtn" disabled={busy !== ""} onClick={() => exportAll()}><span>Export all to Excel</span></button>
          </>}
        </div>
        {meta.permissions.export && <p className="muted">Exports use the same layout this page reads, so data can be moved between companies or servers.</p>}
      </section>

      <section className="import-step">
        <h2>2. Choose how to import</h2>
        <fieldset className="import-modes">
          <legend className="sr-only">What to do with each line</legend>
          {MODES.filter((m) => m.value === "insert" || meta.permissions.write).map((m) => (
            <label key={m.value} className="radio"><input type="radio" name="mode" checked={opts.mode === m.value} onChange={() => set({ mode: m.value })} /> <b>{m.label}</b> <span className="muted">{m.help}</span></label>
          ))}
        </fieldset>
        {opts.mode !== "insert" && uniqueFields.length > 0 && (
          <div className="field"><label htmlFor="imp_match">Find existing records by</label>
            <select id="imp_match" value={opts.match} onChange={(e) => set({ match: e.target.value })}>
              <option value="">The ID column</option>
              {uniqueFields.map((f) => <option key={f.fieldname} value={f.fieldname}>{f.label || f.fieldname}</option>)}
            </select></div>
        )}
        <div className="field"><label htmlFor="imp_date">Dates in the file are written</label>
          <select id="imp_date" value={opts.date_format} onChange={(e) => set({ date_format: e.target.value as ImportOptions["date_format"] })}>
            {DATES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}</select></div>
        {canSubmit && <label className="check"><input type="checkbox" checked={opts.submit} onChange={(e) => set({ submit: e.target.checked })} /> Submit the documents after creating them</label>}
        <label className="check"><input type="checkbox" checked={opts.atomic} onChange={(e) => set({ atomic: e.target.checked })} /> All or nothing: if any document fails, import none of them</label>
        {opts.mode !== "update" && <label className="check"><input type="checkbox" checked={opts.keep_names} onChange={(e) => set({ keep_names: e.target.checked })} /> Keep the IDs in the file (for moving data from another system; System Managers only)</label>}
      </section>

      <section className="import-step">
        <h2>3. Choose the file and check it</h2>
        <input ref={input} type="file" aria-label="File to import" accept=".xlsx,.xlsm" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setReport(null); setError(""); }} />
        {file && <span className="muted"> {file.name} ({Math.max(1, Math.round(file.size / 1024))} KB)</span>}
        <div className="ribbon">
          <button type="button" className="rbtn" disabled={!file || busy !== ""} onClick={() => go(true)}><Icon name="check" /><span>{busy === "check" ? "Checking…" : "Check file"}</span></button>
          <button type="button" className="rbtn primary" disabled={!file || busy !== ""} onClick={() => go(false)}><Icon name="submit" /><span>{busy === "import" ? "Importing…" : "Import"}</span></button>
        </div>
        <p className="muted">Check file runs the real validation and saves nothing. It is the safe way to find every problem first.</p>
      </section>

      {error && <div className="error" role="alert">{error}</div>}

      {report && (
        <section className="import-result" aria-live="polite" data-testid="import-result">
          <div className={`banner ${report.failed ? "cancelled" : "copied"}`} role="status">
            {report.dry_run ? <b>Check finished: nothing was saved.</b> : report.rolled_back ? <b>Nothing was imported (all or nothing).</b> : <b>Import finished.</b>}{" "}
            {report.failed === 0 ? (report.dry_run ? "No problems found: you can import this file." : "Every document was imported.") : `${report.failed} document${report.failed === 1 ? "" : "s"} could not be imported.`}
          </div>
          <div className="import-tiles">
            <div><b>{report.total}</b><span>in the file</span></div>
            <div><b>{report.created}</b><span>{report.dry_run ? "would be created" : "created"}</span></div>
            <div><b>{report.updated}</b><span>{report.dry_run ? "would be updated" : "updated"}</span></div>
            <div className={report.failed ? "bad" : ""}><b>{report.failed}</b><span>failed</span></div>
          </div>
          {report.unknown_columns.length > 0 && <p className="muted">Ignored columns (they match no importable field; calculated fields are never imported): {report.unknown_columns.join(", ")}</p>}
          {report.errors.length > 0 && (
            <>
              <table className="import-errors"><thead><tr><th>Line</th><th>Column</th><th>Problem</th></tr></thead>
                <tbody>{report.errors.slice(0, SHOWN).map((e, i) => <tr key={i}><td>{e.row}</td><td>{e.field}</td><td>{e.message}</td></tr>)}</tbody></table>
              {report.errors.length > SHOWN && <p className="muted">Showing the first {SHOWN} of {report.errors.length} problems; the file below has them all.</p>}
              {report.failed_rows.length > 0 && <button type="button" className="rbtn" disabled={busy !== ""} onClick={failedFile}><Icon name="sheet" /><span>Download the failed rows</span></button>}
              <p className="muted">The file has your original columns plus an Error column. Correct the rows, then import it again.</p>
            </>
          )}
          {real && report.created + report.updated > 0 && <p><a href={`#/app/${encodeURIComponent(doctype)}`}>Open the {doctype} list</a></p>}
        </section>
      )}
    </div>
  );
}
