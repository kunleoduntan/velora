import { useEffect, useRef, useState } from "react";
import type { ReportResultData } from "../api";
import { formatReportValue } from "../format";

const NUMERIC = ["Currency", "Float", "Int", "Percent"];
const MIN_WIDTH = 92;
const MAX_WIDTH = 640;

/** Excel-style report grid with per-user, per-report resizable columns. */
export default function ReportSheet({ result, loading }: { result: ReportResultData; loading?: boolean }) {
  const cols = result.columns;
  const first = cols[0]?.fieldname;
  const storageKey = `velora.report.column-widths.${result.title || "report"}`;
  const [widths, setWidths] = useState<Record<string, number>>(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch { return {}; }
  });
  const [query, setQuery] = useState("");
  const drag = useRef<{ field: string; startX: number; startWidth: number } | null>(null);

  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify(widths)); } catch { /* storage may be disabled */ }
  }, [storageKey, widths]);

  useEffect(() => {
    try { setWidths(JSON.parse(localStorage.getItem(storageKey) || "{}")); }
    catch { setWidths({}); }
  }, [storageKey]);

  const q = query.trim().toLowerCase();
  const text = (r: ReportResultData["rows"][number]) => cols.map((c) => formatReportValue(r.values[c.fieldname], c.fieldtype)).join("\u0001").toLowerCase();
  const rows = q ? result.rows.filter((r) => r.type === "data" && text(r).includes(q)) : result.rows;
  /** Each column starts just wide enough for its longest value (in characters), unless the user has dragged it. */
  const autoWidth = (c: ReportResultData["columns"][number]) => {
    let n = c.label.length + 3;
    for (const r of result.rows) n = Math.max(n, formatReportValue(r.values[c.fieldname], c.fieldtype).length + (c.fieldname === first ? r.indent * 2 : 0) + 2);
    return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(n * 7.6 + 16)));
  };
  const widthOf = (c: ReportResultData["columns"][number]) => widths[c.fieldname] || autoWidth(c);

  function beginResize(event: React.PointerEvent<HTMLSpanElement>, field: string, label: string) {
    event.preventDefault();
    event.stopPropagation();
    const th = event.currentTarget.parentElement;
    const measured = th?.getBoundingClientRect().width || Math.max(120, label.length * 9 + 32);
    drag.current = { field, startX: event.clientX, startWidth: widths[field] || measured };
    const move = (e: PointerEvent) => {
      if (!drag.current) return;
      const next = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, drag.current.startWidth + e.clientX - drag.current.startX));
      setWidths((current) => ({ ...current, [drag.current!.field]: Math.round(next) }));
    };
    const end = () => {
      drag.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  }

  return (
    <div className="report-sheet" aria-busy={loading}>
      <div className="report-head">
        {result.company && <div className="rh-company">{result.company}</div>}
        <h2>{result.title}</h2>
        {result.subtitle && <div className="muted">{result.subtitle}{result.currency ? `  |  Amounts in ${result.currency}` : ""}</div>}
        {result.filters.length > 0 && <div className="muted"><em>Filters: {result.filters.map(([k, v]) => (v !== "" ? `${k} = ${v}` : k)).join("; ")}</em></div>}
      </div>
      {result.summary.length > 0 && (
        <div className="summary-cards">{result.summary.map((s) => (
          <div className="summary-card" key={s.label}><small>{s.label}</small><strong>{formatReportValue(s.value, s.fieldtype ?? "Data")}</strong></div>))}</div>
      )}
      {result.rows.length > 0 && (
        <div className="report-search"><input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search rows…" aria-label="Search report rows" />
          {q && <small className="muted">{rows.length} of {result.rows.filter((r) => r.type === "data").length} rows</small>}</div>)}
      {result.rows.length === 0 ? <p className="muted" data-testid="report-empty">No data for these filters.</p> : (
        <table className="report report-resizable">
          <colgroup>{cols.map((c) => <col key={c.fieldname} style={{ width: `${widthOf(c)}px` }} />)}</colgroup>
          <thead><tr>{cols.map((c) => (
            <th key={c.fieldname} className={NUMERIC.includes(c.fieldtype) ? "num" : ""}
              style={{ width: `${widthOf(c)}px`, minWidth: `${MIN_WIDTH}px` }}>
              <span className="report-heading-label">{c.label}</span>
              <span className="report-col-resize" role="separator" aria-orientation="vertical"
                aria-label={`Resize ${c.label} column`} title={`Drag to resize ${c.label}`}
                onPointerDown={(e) => beginResize(e, c.fieldname, c.label)} />
            </th>
          ))}</tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={`rp-${r.type}`} data-row-type={r.type}>
                {cols.map((c) => (
                  <td key={c.fieldname} className={NUMERIC.includes(c.fieldtype) ? "num" : ""}
                    style={c.fieldname === first ? { paddingLeft: 12 + r.indent * 18 } : undefined}>
                    {r.type === "header" && c.fieldname !== first ? "" : formatReportValue(r.values[c.fieldname], c.fieldtype)}</td>))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="report-note">Generated {result.generated_at}</p>
    </div>
  );
}
