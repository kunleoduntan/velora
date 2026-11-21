import { useState } from "react";
import { api, downloadBlob, errorMessage, type ExportBody } from "../../api";
import type { ApiFilter } from "../../filters";
import Dialog from "../../ui/Dialog";
import Icon from "../../ui/Icon";

export interface ExportProps {
  doctype: string;
  columns: string[];          // visible columns, in order (excluding the fixed ID column)
  apiFilters: ApiFilter[];
  orderBy?: string;
  selected: string[];
  pageNames: string[];
  total: number;
  initialRows?: "selected" | "all" | "page";
  onClose: () => void;
}

/** Excel export. "Current view" = the visible columns; "All fields" = every field plus child tables on their own sheets. */
export default function ExportDialog(p: ExportProps) {
  const [cols, setCols] = useState<"view" | "all">("view");
  const [rows, setRows] = useState<"selected" | "all" | "page">(p.initialRows ?? (p.selected.length ? "selected" : "all"));
  const [header, setHeader] = useState<"label" | "fieldname">("label");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  async function go() {
    setBusy(true); setError(""); setDone("");
    const body: ExportBody = { header, order_by: p.orderBy };
    if (cols === "all") body.all_fields = true; else body.columns = ["name", ...p.columns];
    if (rows === "selected") body.names = p.selected;
    else if (rows === "page") body.names = p.pageNames;
    else body.filters = p.apiFilters;
    try {
      const { blob, filename, rows: n } = await api.exportXlsx(p.doctype, body);
      downloadBlob(blob, filename);
      setDone(`Exported ${n.toLocaleString()} row${n === 1 ? "" : "s"} to ${filename}`);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  const radio = <T extends string>(name: string, value: T, cur: T, set: (v: T) => void, label: string, hint?: string, disabled?: boolean) => (
    <label className={`radio${disabled ? " disabled" : ""}`}>
      <input type="radio" name={name} value={value} checked={cur === value} disabled={disabled} onChange={() => set(value)} />
      <span><strong>{label}</strong>{hint && <small>{hint}</small>}</span>
    </label>
  );

  return (
    <Dialog title={`Export ${p.doctype} to Excel`} onClose={p.onClose} footer={<>
      <button type="button" className="rbtn" onClick={p.onClose}>Close</button>
      <button type="button" className="rbtn primary" disabled={busy} onClick={go}><Icon name="sheet" /><span>{busy ? "Exporting…" : "Export"}</span></button>
    </>}>
      <fieldset>
        <legend>Columns</legend>
        {radio("cols", "view", cols, setCols, "Current view", `The ${p.columns.length + 1} columns you see, in this order`)}
        {radio("cols", "all", cols, setCols, "All fields", "Every field plus system fields; each child table on its own sheet")}
      </fieldset>
      <fieldset>
        <legend>Rows</legend>
        {radio("rows", "selected", rows, setRows, `Selected rows (${p.selected.length})`, undefined, p.selected.length === 0)}
        {radio("rows", "all", rows, setRows, `All rows matching the current filters (${p.total.toLocaleString()})`, "Up to 50,000 rows")}
        {radio("rows", "page", rows, setRows, `This page only (${p.pageNames.length})`)}
      </fieldset>
      <fieldset>
        <legend>Column headers</legend>
        {radio("hdr", "label", header, setHeader, "Labels", "Friendly names, e.g. Customer Name")}
        {radio("hdr", "fieldname", header, setHeader, "Field names", "Technical names, e.g. customer_name (best for re-import)")}
      </fieldset>
      {error && <div className="error" role="alert">{error}</div>}
      {done && <div className="success" role="status">{done}</div>}
    </Dialog>
  );
}
