import { useState } from "react";
import { dataFields, fieldInfo, isComplete, needsValue, opLabel, opsFor, type Filter } from "../../filters";
import type { Meta } from "../../types";
import Icon from "../../ui/Icon";
import Popover from "../../ui/Popover";
import LinkField from "../LinkField";

const STATUS = ["Draft", "Submitted", "Cancelled"];

function ValueInput({ meta, filter, onChange }: { meta: Meta; filter: Filter; onChange: (v: unknown) => void }) {
  const { fieldtype, field } = fieldInfo(meta, filter.field);
  const { op } = filter;
  if (!needsValue(op)) return null;
  const single = op !== "in" && op !== "not in" && op !== "between";
  const type = fieldtype === "Date" || fieldtype === "Datetime" ? "date" : ["Int", "Float", "Currency"].includes(fieldtype) && filter.field !== "docstatus" ? "number" : "text";

  if (op === "between") {
    const [a, b] = Array.isArray(filter.value) ? (filter.value as string[]) : ["", ""];
    return (
      <span className="between">
        <input type={type} aria-label="From" value={a ?? ""} onChange={(e) => onChange([e.target.value, b ?? ""])} />
        <span>and</span>
        <input type={type} aria-label="To" value={b ?? ""} onChange={(e) => onChange([a ?? "", e.target.value])} />
      </span>
    );
  }
  if (filter.field === "docstatus") {
    return <select aria-label="Value" value={String(filter.value ?? "")} onChange={(e) => onChange(e.target.value)}>
      <option value="" />{STATUS.map((s, i) => <option key={s} value={i}>{s}</option>)}</select>;
  }
  if (fieldtype === "Check") {
    return <select aria-label="Value" value={String(filter.value ?? "")} onChange={(e) => onChange(e.target.value)}>
      <option value="" /><option value="1">Yes</option><option value="0">No</option></select>;
  }
  if (fieldtype === "Select" && single) {
    return <select aria-label="Value" value={String(filter.value ?? "")} onChange={(e) => onChange(e.target.value)}>
      <option value="" />{(Array.isArray(field?.options) ? field!.options : []).map((o) => <option key={o} value={o}>{o}</option>)}</select>;
  }
  if (fieldtype === "Link" && single) {
    return <LinkField doctype={String(field?.options)} value={String(filter.value ?? "")} onChange={onChange} />;
  }
  return <input type={type} aria-label="Value" placeholder={op === "in" || op === "not in" ? "comma, separated" : ""}
    value={Array.isArray(filter.value) ? filter.value.join(", ") : String(filter.value ?? "")} onChange={(e) => onChange(e.target.value)} />;
}

function Editor({ meta, initial, onApply, close }: { meta: Meta; initial: Filter[]; onApply: (f: Filter[]) => void; close: () => void }) {
  const fields = dataFields(meta);
  const [rows, setRows] = useState<Filter[]>(initial.length ? initial : []);
  const set = (i: number, patch: Partial<Filter>) => setRows((r) => r.map((x, idx) => (idx === i ? { ...x, ...patch } : x)));
  const add = () => {
    const f = fields.find((x) => x.fieldname !== "name") ?? fields[0];
    setRows((r) => [...r, { field: f.fieldname, op: opsFor(f.fieldtype, f.fieldname)[0], value: "" }]);
  };
  return (
    <div className="filter-editor">
      {rows.length === 0 && <p className="muted">No filters applied.</p>}
      {rows.map((r, i) => {
        const info = fieldInfo(meta, r.field);
        return (
          <div className="filter-row" key={i}>
            <select aria-label="Field" value={r.field} onChange={(e) => {
              const fi = fieldInfo(meta, e.target.value);
              set(i, { field: e.target.value, op: opsFor(fi.fieldtype, e.target.value)[0], value: "" });
            }}>
              {fields.map((f) => <option key={f.fieldname} value={f.fieldname}>{f.label}</option>)}
            </select>
            <select aria-label="Condition" value={r.op} onChange={(e) => set(i, { op: e.target.value, value: e.target.value === "between" ? ["", ""] : "" })}>
              {opsFor(info.fieldtype, r.field).map((o) => <option key={o} value={o}>{opLabel(o)}</option>)}
            </select>
            <ValueInput meta={meta} filter={r} onChange={(v) => set(i, { value: v })} />
            <button type="button" className="icon-btn" aria-label="Remove filter" onClick={() => setRows((x) => x.filter((_, idx) => idx !== i))}><Icon name="x" /></button>
          </div>
        );
      })}
      <div className="popover-actions">
        <button type="button" className="rbtn" onClick={add}><Icon name="plus" /><span>Add a filter</span></button>
        <span className="grow" />
        <button type="button" className="rbtn" onClick={() => { onApply([]); close(); }}>Clear filters</button>
        <button type="button" className="rbtn primary" onClick={() => { onApply(rows.filter(isComplete)); close(); }}>Apply filters</button>
      </div>
    </div>
  );
}

export default function FilterPopover({ meta, filters, onChange }: { meta: Meta; filters: Filter[]; onChange: (f: Filter[]) => void }) {
  return (
    <Popover className="wide-pop" trigger={(p) => (
      <button type="button" className="rbtn" {...p}>
        <Icon name="filter" /><span>Filter</span>{filters.length > 0 && <span className="badge">{filters.length}</span>}
      </button>
    )}>
      {(close) => <Editor meta={meta} initial={filters} onApply={onChange} close={close} />}
    </Popover>
  );
}
