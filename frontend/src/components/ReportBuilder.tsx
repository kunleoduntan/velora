import { askConfirm, askPrompt, askAlert } from "../ui/ask";
import { useEffect, useMemo, useState } from "react";
import { api, downloadBlob, errorMessage, type AdhocMeasure, type AdhocSpec, type ReportResultData, type SavedReport } from "../api";
import { dataFields, describe, fieldInfo, fromApi, toApi, type Filter } from "../filters";
import { builderHash, goTo } from "../router";
import type { DocTypeInfo, Meta } from "../types";
import Icon from "../ui/Icon";
import Popover from "../ui/Popover";
import Toggle from "../ui/Toggle";
import FilterPopover from "./list/FilterPopover";
import ReportSheet from "./ReportSheet";
import SavedReportHistory from "./SavedReportHistory";

const GROUPABLE = ["Select", "Link", "Check", "Date", "Datetime", "Data", "Int"];
const NUMERIC = ["Int", "Float", "Currency"];
const FNS: [string, string][] = [["count", "Count"], ["sum", "Sum"], ["avg", "Average"], ["min", "Minimum"], ["max", "Maximum"]];
const BUCKETS: [string, string][] = [["day", "Day"], ["month", "Month"], ["quarter", "Quarter"], ["year", "Year"]];
const SYSTEM_GROUPABLE = ["owner", "creation", "modified", "docstatus"];

interface Measure { fn: string; field: string; label: string }
const emptyMeasure = (): Measure => ({ fn: "count", field: "", label: "" });

/** Self-service reporting: choose what to group by and what to total, preview it, export it as the formatted Excel report, save it. */
export default function ReportBuilder({ id }: { id?: string }) {
  const [types, setTypes] = useState<DocTypeInfo[]>([]);
  const [doctype, setDoctype] = useState("");
  const [meta, setMeta] = useState<Meta | null>(null);
  const [groupBy, setGroupBy] = useState<string[]>([""]);
  const [bucket, setBucket] = useState("month");
  const [measures, setMeasures] = useState<Measure[]>([{ fn: "count", field: "", label: "" }]);
  const [filters, setFilters] = useState<Filter[]>([]);
  const [title, setTitle] = useState("");
  const [result, setResult] = useState<ReportResultData | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [saved, setSaved] = useState<SavedReport | null>(null);
  const [saveName, setSaveName] = useState("");
  const [shared, setShared] = useState(false);

  useEffect(() => { api.doctypes().then(setTypes).catch((e) => setError(errorMessage(e))); }, []);

  // ---- derived options ---------------------------------------------------------------------------
  const groupOptions = useMemo(() => (meta ? dataFields(meta).filter((f) => f.fieldname !== "name" && (SYSTEM_GROUPABLE.includes(f.fieldname) || GROUPABLE.includes(f.fieldtype)) && !(f.fieldname === "docstatus" && !meta.is_submittable)) : []), [meta]);
  const measureFields = useMemo(() => (meta ? meta.fields.filter((f) => NUMERIC.includes(f.fieldtype)) : []), [meta]);
  const chosen = groupBy.filter(Boolean);
  const dateField = meta ? chosen.find((g) => ["Date", "Datetime"].includes(fieldInfo(meta, g).fieldtype)) : undefined;

  const problems: string[] = [];
  if (!doctype) problems.push("Choose what to report on");
  else if (chosen.length === 0) problems.push("Choose at least one field to group by");
  if (measures.some((m) => m.fn !== "count" && !m.field)) problems.push("Pick a field for each total");

  const spec = (): AdhocSpec => ({
    doctype, group_by: chosen, date_field: dateField ?? null, date_bucket: dateField ? bucket : null,
    measures: measures.map((m): AdhocMeasure => ({ fn: m.fn, ...(m.fn === "count" ? {} : { field: m.field }), ...(m.label.trim() ? { label: m.label.trim() } : {}) })),
    filters: toApi(filters), ...(title.trim() ? { title: title.trim() } : {}),
  });

  // ---- load a doctype's meta; load a saved report -------------------------------------------------
  useEffect(() => {
    if (!doctype) { setMeta(null); return; }
    let cancelled = false;
    api.meta(doctype).then((m) => { if (!cancelled) setMeta(m); }).catch((e) => { if (!cancelled) setError(errorMessage(e)); });
    return () => { cancelled = true; };
  }, [doctype]);

  useEffect(() => {
    if (!id) return;
    api.savedReport(id).then(async (r) => {
      const s = r.spec;
      setSaved(r); setSaveName(r.name); setShared(r.shared); setTitle(s.title ?? "");
      setDoctype(s.doctype); setGroupBy(s.group_by.length ? s.group_by : [""]); setBucket(s.date_bucket ?? "month");
      setMeasures(s.measures.map((m) => ({ fn: m.fn, field: m.field ?? "", label: m.label ?? "" })));
      setFilters(s.filters.map(fromApi));
      await run(s);
    }).catch((e) => setError(errorMessage(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const changeDoctype = (d: string) => { setDoctype(d); setGroupBy([""]); setMeasures([emptyMeasure()]); setFilters([]); setResult(null); setError(""); setNote(""); };

  async function run(s: AdhocSpec = spec()) {
    setLoading(true); setError(""); setNote("");
    try { setResult(await api.runAdhoc(s)); }
    catch (e) { setError(errorMessage(e)); setResult(null); }
    finally { setLoading(false); }
  }

  async function exportXlsx() {
    setExporting(true); setError("");
    try { const { blob, filename } = await api.exportAdhoc(spec()); downloadBlob(blob, filename); }
    catch (e) { setError(errorMessage(e)); }
    finally { setExporting(false); }
  }

  const changed = () => window.dispatchEvent(new Event("velora:saved-reports-changed"));
  async function save(asNew: boolean, close: () => void) {
    const name = saveName.trim() || title.trim();
    setError("");
    try {
      if (saved && !asNew) {
        const r = await api.updateSavedReport(saved.id, { name, spec: spec(), shared });
        setSaved(r); setNote(`Saved changes to "${r.name}".`);
      } else {
        const r = await api.createSavedReport({ name, spec: spec(), shared });
        setSaved(r); setNote(`Saved as "${r.name}".`); goTo(builderHash(r.id));
      }
      changed(); close();
    } catch (e) { setError(errorMessage(e)); }
  }
  async function remove() {
    if (!saved || !await askConfirm(`Delete the saved report "${saved.name}"?`)) return;
    try { await api.deleteSavedReport(saved.id); changed(); goTo(builderHash()); }
    catch (e) { setError(errorMessage(e)); }
  }

  const canExport = !!meta?.permissions.export;
  return (
    <div className="report-page builder">
      <header className="page-head"><div className="titles"><h1>{saved ? saved.name : "Report builder"}</h1>
        <span className="muted">Group, total and filter any DocType, then export it to Excel</span></div></header>
      <div className="ribbon" role="toolbar" aria-label="Builder actions">
        <button type="button" className="rbtn primary" disabled={loading || problems.length > 0} onClick={() => run()}><Icon name="refresh" /><span>{loading ? "Running…" : "Run report"}</span></button>
        {canExport && <button type="button" className="rbtn" disabled={exporting || problems.length > 0} onClick={exportXlsx}><Icon name="sheet" /><span>{exporting ? "Exporting…" : "Export to Excel"}</span></button>}
        <Popover trigger={(p) => <button type="button" className="rbtn" disabled={problems.length > 0} {...p}><Icon name="save" /><span>Save report</span></button>}>
          {(close) => (
            <div className="save-pop">
              <label htmlFor="sr-name">Report name</label>
              <input id="sr-name" type="text" maxLength={100} value={saveName} placeholder={title || "e.g. Sales by group"} onChange={(e) => setSaveName(e.target.value)} />
              <div className="field"><label htmlFor="sr-share">Share with everyone in this company</label><Toggle id="sr-share" checked={shared} onChange={setShared} />
                <small>Only a System Manager can share. People who run a shared report only see data they are allowed to see.</small></div>
              <div className="popover-actions">
                {saved?.can_edit && <button type="button" className="rbtn primary" onClick={() => save(false, close)}>Update “{saved.name}”</button>}
                <button type="button" className={`rbtn${saved?.can_edit ? "" : " primary"}`} onClick={() => save(true, close)}>{saved ? "Save as new" : "Save"}</button>
              </div>
            </div>
          )}
        </Popover>
        {saved?.can_edit && <button type="button" className="rbtn danger" onClick={remove}><Icon name="trash" /><span>Delete</span></button>}
        <span className="rsep" />
        <button type="button" className="rbtn" onClick={() => goTo(builderHash())}><Icon name="plus" /><span>New report</span></button>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {note && <div className="success" role="status">{note}</div>}

      <div className="builder-grid">
        <section className="section builder-def" aria-label="Report definition">
          <div className="section-head static"><span>Definition</span></div>
          <div className="builder-body">
            <div className="field"><label htmlFor="b-doctype">Report on</label>
              <select id="b-doctype" value={doctype} onChange={(e) => changeDoctype(e.target.value)}>
                <option value="">Choose a DocType…</option>{types.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}</select></div>

            <h4>Group by</h4>
            {[0, 1].map((i) => (i === 0 || groupBy[0]) && (
              <div className="field" key={i}><label htmlFor={`b-group-${i}`}>{i === 0 ? "Group by" : "Then by (optional)"}</label>
                <select id={`b-group-${i}`} value={groupBy[i] ?? ""} disabled={!meta} onChange={(e) => setGroupBy((cur) => { const n = [cur[0] ?? "", cur[1] ?? ""]; n[i] = e.target.value; return !n[0] ? [""] : n[1] ? [n[0], n[1]] : [n[0]]; })}>
                  <option value="">{i === 0 ? "Choose a field…" : "None"}</option>
                  {groupOptions.filter((f) => f.fieldname !== groupBy[1 - i]).map((f) => <option key={f.fieldname} value={f.fieldname}>{f.label}</option>)}</select></div>
            ))}
            {dateField && (
              <div className="field"><label htmlFor="b-bucket">Group dates by</label>
                <select id="b-bucket" value={bucket} onChange={(e) => setBucket(e.target.value)}>{BUCKETS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
            )}

            <h4>Totals</h4>
            {measures.map((m, i) => (
              <div className="measure-row" key={i}>
                <select aria-label={`Total ${i + 1} function`} value={m.fn} onChange={(e) => setMeasures((cur) => cur.map((x, j) => (j === i ? { ...x, fn: e.target.value, field: e.target.value === "count" ? "" : x.field } : x)))}>
                  {FNS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                {m.fn !== "count" && (
                  <select aria-label={`Total ${i + 1} field`} value={m.field} onChange={(e) => setMeasures((cur) => cur.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)))}>
                    <option value="">Field…</option>{measureFields.map((f) => <option key={f.fieldname} value={f.fieldname}>{f.label}</option>)}</select>
                )}
                <input type="text" aria-label={`Total ${i + 1} label`} placeholder="Column title (optional)" value={m.label} onChange={(e) => setMeasures((cur) => cur.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
                <button type="button" className="icon-btn" aria-label={`Remove total ${i + 1}`} disabled={measures.length === 1} onClick={() => setMeasures((cur) => cur.filter((_, j) => j !== i))}><Icon name="x" size={14} /></button>
              </div>
            ))}
            <button type="button" className="rbtn" disabled={!meta || measures.length >= 6} onClick={() => setMeasures((cur) => [...cur, emptyMeasure()])}><Icon name="plus" /><span>Add a total</span></button>

            <h4>Filters</h4>
            {meta && <FilterPopover meta={meta} filters={filters} onChange={setFilters} />}
            {meta && filters.length > 0 && <div className="chips">{filters.map((f, i) => (
              <span className="chip" key={i}>{describe(f, meta)}
                <button type="button" aria-label={`Remove filter ${describe(f, meta)}`} onClick={() => setFilters((cur) => cur.filter((_, j) => j !== i))}><Icon name="x" size={12} /></button></span>))}</div>}

            <div className="field"><label htmlFor="b-title">Report title</label>
              <input id="b-title" type="text" maxLength={100} value={title} placeholder="Shown at the top of the report and the Excel file" onChange={(e) => setTitle(e.target.value)} /></div>
            {problems.length > 0 && <p className="muted" data-testid="builder-hint">{problems[0]}.</p>}
          </div>
        </section>
        <section className="builder-preview" aria-label="Preview">
          {result ? <ReportSheet result={result} loading={loading} /> : <div className="panel muted">{loading ? "Running…" : "Choose what to report on, then run the report."}</div>}
        </section>
      </div>
      {saved && <SavedReportHistory id={saved.id} canEdit={saved.can_edit} onRestored={async () => {
        const r = await api.savedReport(saved.id);
        setSaved(r); setSaveName(r.name); setShared(r.shared); setTitle(r.spec.title ?? "");
        setDoctype(r.spec.doctype); setGroupBy(r.spec.group_by.length ? r.spec.group_by : [""]);
        setBucket(r.spec.date_bucket ?? "month");
        setMeasures(r.spec.measures.map((m) => ({ fn: m.fn, field: m.field ?? "", label: m.label ?? "" })));
        setFilters(r.spec.filters.map(fromApi)); await run(r.spec);
      }} />}
    </div>
  );
}
