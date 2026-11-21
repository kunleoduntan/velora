import { useEffect, useRef, useState } from "react";
import { api, downloadBlob, errorMessage, type ReportDefinition, type ReportFilterDef, type ReportResultData } from "../api";
import Icon from "../ui/Icon";
import LinkField from "./LinkField";
import ReportSheet from "./ReportSheet";

function FilterInput({ f, value, onChange }: { f: ReportFilterDef; value: unknown; onChange: (v: unknown) => void }) {
  const v = value === undefined || value === null ? "" : String(value);
  const id = `rf_${f.fieldname}`;
  let control;
  if (f.fieldtype === "Select") {
    control = <select id={id} value={v} onChange={(e) => onChange(e.target.value || null)}><option value="">All</option>
      {(Array.isArray(f.options) ? f.options : []).map((o) => <option key={o} value={o}>{o}</option>)}</select>;
  } else if (f.fieldtype === "Link") {
    control = <LinkField doctype={String(f.options)} value={v} onChange={(x) => onChange(x || null)} id={id} />;
  } else if (f.fieldtype === "Check") {
    // a Check that has a default sends an explicit false, otherwise "off" would fall back to the default on the server
    control = <label className="rf-check"><input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked ? true : f.default === undefined || f.default === null ? null : false)} /> <span>{value ? "Yes" : "No"}</span></label>;
  } else {
    const type = f.fieldtype === "Date" ? "date" : ["Int", "Float", "Currency"].includes(f.fieldtype) ? "number" : "text";
    control = <input id={id} type={type} value={v} onChange={(e) => onChange(e.target.value || null)} />;
  }
  return (
    <div className="field"><label htmlFor={id}>{f.label}{f.required && <span className="req"> *</span>}</label>{control}
      {f.fieldtype === "Date" && typeof f.default === "string" && <small>Default: {f.default}</small>}</div>
  );
}

/** What each filter shows when the report opens: its default (dates keep their relative default, which the server resolves). */
function startingFilters(defs: ReportFilterDef[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of defs) {
    if (f.default === undefined || f.default === null || f.default === "" || f.fieldtype === "Date") continue;
    out[f.fieldname] = f.fieldtype === "Check" ? !!Number(f.default === true ? 1 : f.default) : f.default;
  }
  return out;
}

/** Runs any registered or ad-hoc report and shows it the way the Excel export lays it out. */
export default function ReportView({ name }: { name: string }) {
  const [def, setDef] = useState<ReportDefinition | null>(null);
  const [filters, setFilters] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<ReportResultData | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const seq = useRef(0);

  const clean = (f: Record<string, unknown>) => Object.fromEntries(Object.entries(f).filter(([, v]) => v !== null && v !== undefined && v !== ""));

  async function run(f: Record<string, unknown>) {
    const mine = ++seq.current;
    setLoading(true); setError("");
    try { const r = await api.runReport(name, clean(f)); if (mine === seq.current) setResult(r); }
    catch (e) { if (mine === seq.current) { setError(errorMessage(e)); setResult(null); } }
    finally { if (mine === seq.current) setLoading(false); }
  }

  useEffect(() => {
    setDef(null); setResult(null); setFilters({}); setError("");
    api.reportDef(name).then((d) => { setDef(d); const start = startingFilters(d.filters ?? []); setFilters(start); void run(start); }).catch((e) => setError(errorMessage(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  async function exportXlsx() {
    setExporting(true); setError("");
    try { const { blob, filename } = await api.exportReport(name, clean(filters)); downloadBlob(blob, filename); }
    catch (e) { setError(errorMessage(e)); }
    finally { setExporting(false); }
  }

  if (!def) return <div className="panel">{error ? <div className="error" role="alert">{error}</div> : "Loading…"}</div>;
  return (
    <div className="report-page">
      <header className="page-head"><div className="titles"><h1>{def.name}</h1>{def.description && <span className="muted">{def.description}</span>}</div></header>
      <div className="ribbon" role="toolbar" aria-label="Report actions">
        <button type="button" className="rbtn primary" disabled={loading} onClick={() => run(filters)}><Icon name="refresh" /><span>{loading ? "Running…" : "Run report"}</span></button>
        {def.can_export && <button type="button" className="rbtn" disabled={exporting || !result} onClick={exportXlsx}><Icon name="sheet" /><span>{exporting ? "Exporting…" : "Export to Excel"}</span></button>}
        <button type="button" className="rbtn" disabled={!result} onClick={() => window.print()}><Icon name="download" /><span>Print</span></button>
      </div>
      {def.filters.length > 0 && (
        <form className="report-filters report-filter-grid" onSubmit={(e) => { e.preventDefault(); void run(filters); }}>
          {def.filters.map((f) => <FilterInput key={f.fieldname} f={f} value={filters[f.fieldname]} onChange={(v) => setFilters((cur) => ({ ...cur, [f.fieldname]: v }))} />)}
        </form>
      )}
      {error && <div className="error" role="alert">{error}</div>}
      {result && <ReportSheet result={result} loading={loading} />}
    </div>
  );
}
