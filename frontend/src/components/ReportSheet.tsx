import type { ReportResultData } from "../api";
import { formatReportValue } from "../format";

const NUMERIC = ["Currency", "Float", "Int", "Percent"];

/** The report as it prints and exports: title block, headline numbers, hierarchy with subtotal/total rows. */
export default function ReportSheet({ result, loading }: { result: ReportResultData; loading?: boolean }) {
  const cols = result.columns;
  const first = cols[0]?.fieldname;
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
      {result.rows.length === 0 ? <p className="muted" data-testid="report-empty">No data for these filters.</p> : (
        <table className="report">
          <thead><tr>{cols.map((c) => <th key={c.fieldname} className={NUMERIC.includes(c.fieldtype) ? "num" : ""}>{c.label}</th>)}</tr></thead>
          <tbody>
            {result.rows.map((r, i) => (
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
