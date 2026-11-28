import { useEffect, useMemo, useRef, useState } from "react";
import { api, clearCaches, downloadBlob, errorMessage } from "../api";
import { frozenFits, gridFields, loadFreeze, loadPersonal, MAX_WIDTH, reorder, resolveColumns, saveFreeze, savePersonal, toColumns } from "../gridConfig";
import type { Doc, Field, GridColumn, Meta } from "../types";
import Icon from "../ui/Icon";
import { fetchedValues } from "../fetchFrom";
import FieldControl from "./FieldControl";
import GridColumnsDialog from "./GridColumnsDialog";
import RowEditDialog from "./RowEditDialog";

interface Props {
  field: Field;
  rows: Record<string, unknown>[];
  onChange: (rows: Record<string, unknown>[]) => void;
  readOnly?: boolean;
  childMeta?: Meta;
  childMetas?: Record<string, Meta>;
  onChildChange?: (row: Record<string, unknown>, rowIndex: number, fieldname: string) => void;
  parentDoc?: Doc | null;
  rowDefaults?: Record<string, unknown>;
}

function defaultFor(f: Field): unknown {
  if (f.fieldtype === "Check") return 0;
  if (f.default === "Today") return new Date().toISOString().slice(0, 10);
  return f.default ?? null;
}

const key = (row: Record<string, unknown>, i: number) => String(row.name ?? `new-${i}`);
/** Excel-style cell tints: links pink, money light blue, free text light yellow. */
const cellKind = (t: string) => (t === "Link" || t === "Dynamic Link" ? "link" : t === "Currency" ? "currency" : ["Data", "Small Text", "Text", "Long Text"].includes(t) ? "data" : "plain");
const NUM = ["Int", "Float", "Currency"];

/** Editable grid: choose your columns (any number of fields per row), resize them, reorder rows, edit a whole row in a dialog. */
export default function TableField({ field, rows, onChange, onChildChange, readOnly, childMeta, childMetas, parentDoc, rowDefaults }: Props) {
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [personal, setPersonal] = useState<GridColumn[] | null>(() => (childMeta ? loadPersonal(childMeta.name) : null));
  const [shared, setShared] = useState<GridColumn[] | null>(null);
  const [dialog, setDialog] = useState<"cols" | number | null>(null);
  const [error, setError] = useState("");
  const dragFrom = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [freezeWanted, setFreezeWanted] = useState<number>(() => (childMeta ? loadFreeze(childMeta.name) : 5));
  const [boxWidth, setBoxWidth] = useState(0);
  useEffect(() => {                                    // the frozen block must never take the whole width: measure the box it lives in
    const el = scrollRef.current;
    if (!el) return;
    setBoxWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setBoxWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, [childMeta]);
  const cols = useMemo(() => (childMeta ? resolveColumns(childMeta, personal, shared) : []), [childMeta, personal, shared]);
  if (!childMeta) return <div className="muted">Loading {String(field.options)}…</div>;
  const child = childMeta.name;
  // freeze panes: the select and drag columns plus the first columns of the row stay in view while the rest scrolls sideways
  const colPx = cols.map((c) => Math.max(76, c.width * 70));
  const lead = 30 + (readOnly ? 0 : 22);
  const frozen = frozenFits(colPx, freezeWanted, boxWidth ? boxWidth - lead : 0);
  const leftOf: number[] = []; { let acc = lead; colPx.forEach((w, i) => { leftOf[i] = acc; acc += w; }); }
  const stick = (i: number) => (i < frozen ? { className: `sticky-col${i === frozen - 1 ? " freeze-edge" : ""}`, style: { left: leftOf[i] } } : {});

  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const setCell = (i: number, fieldname: string, value: unknown) => {
    const updated = { ...rows[i], [fieldname]: value };
    onChange(rows.map((r, idx) => (idx === i ? updated : r)));
    onChildChange?.(updated, i, fieldname);
    // ERPNext-style fetch: picking an Item fills its name, UOM, account ... in the same row.
    void fetchedValues(childMeta, fieldname, value).then((extra) => {
      const keys = Object.keys(extra);
      if (!keys.length) return;
      const current = rowsRef.current;
      if (!current[i] || current[i][fieldname] !== value) return;          // the row moved on or the link changed again
      const merged = { ...current[i], ...extra };
      onChange(current.map((r, idx) => (idx === i ? merged : r)));
      keys.forEach((k) => onChildChange?.(merged, i, k));
    });
  };
  const blank = () => Object.fromEntries(gridFields(childMeta)
    .filter((c) => c.default !== undefined || c.fieldtype === "Check")
    .map((c) => [c.fieldname, defaultFor(c)])); // include configured defaults only; leave other fields unset
  /** A new row starts with the header values (e.g. the warehouse chosen at the top of the form) that this row type has a field for. */
  const newRow = () => {
    const fromHeader = Object.fromEntries(Object.entries(rowDefaults ?? {}).filter(([k, v]) => v !== null && v !== undefined && v !== "" && childMeta.fields.some((f) => f.fieldname === k)));
    return { ...blank(), ...fromHeader };
  };
  const selected = rows.map((r, i) => i).filter((i) => sel.has(key(rows[i], i)));
  const removeSelected = () => { onChange(rows.filter((r, i) => !sel.has(key(r, i)))); setSel(new Set()); };
  const duplicate = () => { onChange([...rows, ...selected.map((i) => { const { name: _n, ...rest } = rows[i]; void _n; return { ...rest }; })]); setSel(new Set()); };
  const move = (dir: -1 | 1) => {
    const i = selected[0], moved = rows[i];
    onChange(reorder(rows, i, i + dir));
    setSel(new Set([moved.name !== undefined && moved.name !== null ? String(moved.name) : `new-${i + dir}`]));      // the MOVED row stays selected (an unsaved row's key is its position)
  };
  const toggle = (k: string) => setSel((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const allOn = rows.length > 0 && rows.every((r, i) => sel.has(key(r, i)));

  async function saveColumns(next: GridColumn[], scope: "me" | "everyone") {
    setError("");
    if (scope === "me") { savePersonal(child, next); setPersonal(next); setDialog(null); return; }
    try { await api.gridSave(child, next); clearCaches(); savePersonal(child, null); setPersonal(null); setShared(next); setDialog(null); } catch (e) { setError(errorMessage(e)); }
  }
  const fileInput = useRef<HTMLInputElement>(null);
  async function exportExcel() {
    setError("");
    try { const f = await api.gridExcelExport(child, rows); downloadBlob(f.blob, f.filename); } catch (e) { setError(errorMessage(e)); }
  }
  async function importExcel(file: File | undefined) {
    if (!file) return;
    setError("");
    try {
      const res = await api.gridExcelRead(child, file, file.name);
      if (res.errors.length) {
        const first = res.errors.slice(0, 5).map((x) => `row ${x.row}, ${x.column}: ${x.error}`).join("; ");
        setError(`${res.errors.length} cell${res.errors.length === 1 ? "" : "s"} could not be read, so nothing was added. ${first}${res.errors.length > 5 ? "…" : ""}`);
      } else if (!res.rows.length) setError("The file has no rows to add.");
      else onChange([...rows, ...res.rows.map((r) => ({ ...newRow(), ...r }))]);
      if (!res.errors.length && res.unknown.length) setError(`Added ${res.rows.length} rows. These headings were not recognised and were skipped: ${res.unknown.join(", ")}`);
    } catch (e) { setError(errorMessage(e)); }
    finally { if (fileInput.current) fileInput.current.value = ""; }
  }
  function changeFreeze(n: number) { setFreezeWanted(n); saveFreeze(child, n); }
  function resetColumns() { saveFreeze(child, null); setFreezeWanted(5); savePersonal(child, null); setPersonal(null); setShared(null); setDialog(null); }
  function nudge(name: string, d: number) {                                     // keyboard-accessible column resize (the handle is a separator)
    const next = toColumns(cols).map((c) => (c.field === name ? { ...c, width: c.width + d } : c));
    if (next.some((c) => c.width < 1 || c.width > MAX_WIDTH)) return;
    savePersonal(child, next); setPersonal(next);
  }

  return (
    <div className="table-field" data-testid={`table-${field.fieldname}`}>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="grid-scroll" ref={scrollRef}>
        <table className="dgrid fixed unbounded-grid">
          <colgroup>
            <col style={{ width: 30 }} />{!readOnly && <col style={{ width: 22 }} />}
            {cols.map((c) => <col key={c.field.fieldname} style={{ width: `${Math.max(76, c.width * 70)}px` }} />)}
            <col style={{ width: 34 }} />
          </colgroup>
          <thead>
            <tr>
              <th className={frozen > 0 ? "chk sticky-col" : "chk"} style={frozen > 0 ? { left: 0 } : undefined}>{!readOnly && <input type="checkbox" aria-label="Select all rows" checked={allOn} onChange={() => setSel(allOn ? new Set() : new Set(rows.map(key)))} />}</th>
              {!readOnly && <th className={frozen > 0 ? "sticky-col" : ""} style={frozen > 0 ? { left: 30 } : undefined} />}
              {cols.map((c, ci) => (
                <th key={c.field.fieldname} className={`${NUM.includes(c.field.fieldtype) ? "num" : ""} ${stick(ci).className ?? ""}`.trim()} style={{ position: ci < frozen ? "sticky" : "relative", ...(stick(ci).style ?? {}) }}>
                  {c.field.label}{c.field.required && <span className="req"> *</span>}
                  <div role="separator" aria-orientation="vertical" tabIndex={0} className="col-resize" aria-label={`Resize column ${c.field.label}`} aria-valuenow={c.width}
                    onKeyDown={(e) => { if (e.key === "ArrowRight") { e.preventDefault(); nudge(c.field.fieldname, 1); } if (e.key === "ArrowLeft") { e.preventDefault(); nudge(c.field.fieldname, -1); } }} />
                </th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={cols.length + 3} className="empty-row">No rows</td></tr>}
            {rows.map((row, i) => {
              const k = key(row, i);
              return (
                <tr key={k} className={sel.has(k) ? "selected" : ""} onDragOver={(e) => { if (dragFrom.current !== null) e.preventDefault(); }}
                  onDrop={(e) => { e.preventDefault(); if (dragFrom.current !== null) onChange(reorder(rows, dragFrom.current, i)); dragFrom.current = null; }}>
                  <td className={frozen > 0 ? "chk sticky-col" : "chk"} style={frozen > 0 ? { left: 0 } : undefined}>{!readOnly ? <input type="checkbox" aria-label={`Select row ${i + 1}`} checked={sel.has(k)} onChange={() => toggle(k)} /> : <span className="muted">{i + 1}</span>}</td>
                  {!readOnly && <td className={frozen > 0 ? "grip sticky-col" : "grip"} style={frozen > 0 ? { left: 30 } : undefined} draggable aria-label={`Drag row ${i + 1}`} onDragStart={(e) => { dragFrom.current = i; try { e.dataTransfer.setData("text/plain", String(i)); } catch { /* tests */ } }} onDragEnd={() => { dragFrom.current = null; }}><Icon name="grip" size={14} /></td>}
                  {cols.map((c, ci) => (
                    <td key={c.field.fieldname} className={`${NUM.includes(c.field.fieldtype) ? "num" : ""} cell-${cellKind(c.field.fieldtype)} ${stick(ci).className ?? ""}`.trim()} style={stick(ci).style}>
                      <FieldControl compact field={c.field} value={row[c.field.fieldname]} readOnly={readOnly || c.field.read_only} onChange={(v) => setCell(i, c.field.fieldname, v)} childMetas={childMetas} row={row} parentDoc={parentDoc} />
                    </td>
                  ))}
                  <td><button type="button" className="icon-btn" aria-label={`${readOnly ? "View" : "Edit"} row ${i + 1}`} onClick={() => setDialog(i)}><Icon name="edit" size={14} /></button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="grid-toolbar grid-toolbar-bottom">
        {!readOnly && <>
          <button type="button" className="rbtn" aria-label="Add row" onClick={() => onChange([...rows, newRow()])}><Icon name="plus" /><span>New</span></button>
          <button type="button" className="rbtn" aria-label="Delete selected rows" disabled={sel.size === 0} onClick={removeSelected}><Icon name="trash" /><span>Delete</span></button>
          <button type="button" className="rbtn" aria-label="Duplicate selected rows" disabled={sel.size === 0} onClick={duplicate}><Icon name="copy" /><span>Duplicate</span></button>
          <button type="button" className="rbtn" aria-label="Move row up" disabled={selected.length !== 1 || selected[0] === 0} onClick={() => move(-1)}><Icon name="up" /></button>
          <button type="button" className="rbtn" aria-label="Move row down" disabled={selected.length !== 1 || selected[0] === rows.length - 1} onClick={() => move(1)}><Icon name="down" /></button>
        </>}
        <span className="rsep" />
        {!readOnly && <>
          <button type="button" className="rbtn" aria-label="Import rows from Excel" onClick={() => fileInput.current?.click()}><Icon name="sheet" /><span>Import Excel</span></button>
          <input ref={fileInput} type="file" hidden accept=".xlsx,.xlsm" aria-label="Excel file with rows" onChange={(e) => void importExcel(e.target.files?.[0])} />
        </>}
        <button type="button" className="rbtn" aria-label="Export rows to Excel" onClick={() => void exportExcel()}><Icon name="sheet" /><span>{rows.length ? "Export Excel" : "Excel template"}</span></button>
        <button type="button" className="rbtn" aria-label="Configure columns" onClick={() => setDialog("cols")}><Icon name="cog" /><span>Columns</span></button>
      </div>
      {dialog === "cols" && <GridColumnsDialog meta={childMeta} columns={toColumns(cols)} freeze={freezeWanted} onFreeze={changeFreeze} canCustomize={!!childMeta.can_customize} onSave={saveColumns} onReset={resetColumns} onClose={() => setDialog(null)} />}
      {typeof dialog === "number" && rows[dialog] && (
        <RowEditDialog meta={childMeta} childMetas={childMetas} parentDoc={parentDoc} row={rows[dialog]} index={dialog} readOnly={readOnly}
          onSave={(r) => {
            onChange(rows.map((x, idx) => (idx === dialog ? r : x)));
            Object.keys(r).forEach((fieldname) => { if (r[fieldname] !== rows[dialog][fieldname]) onChildChange?.(r, dialog, fieldname); });
            setDialog(null);
          }} onClose={() => setDialog(null)} />
      )}
    </div>
  );
}
