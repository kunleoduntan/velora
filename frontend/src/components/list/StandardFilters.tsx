import { type Filter } from "../../filters";
import type { Field, Meta } from "../../types";
import LinkField from "../LinkField";

const opFor = (f: Field) => (f.fieldtype === "Data" || f.fieldtype === "Text" ? "like" : "=");

/** Inline filter controls for fields flagged `in_standard_filter` in the DocType JSON. */
export default function StandardFilters({ meta, filters, onChange }: { meta: Meta; filters: Filter[]; onChange: (f: Filter[]) => void }) {
  const fields = meta.fields.filter((f) => f.in_standard_filter && !["Table", "JSON"].includes(f.fieldtype));
  if (!fields.length) return null;
  const current = (f: Field) => filters.find((x) => x.field === f.fieldname && x.op === opFor(f));
  const set = (f: Field, value: string) => {
    const rest = filters.filter((x) => !(x.field === f.fieldname && x.op === opFor(f)));
    onChange(value === "" ? rest : [...rest, { field: f.fieldname, op: opFor(f), value: opFor(f) === "like" ? value : value }]);
  };
  return (
    <div className="std-filters">
      {fields.map((f) => {
        const v = current(f)?.value;
        const val = v === undefined ? "" : String(v).replace(/^%|%$/g, "");
        if (f.fieldtype === "Select") {
          return <select key={f.fieldname} aria-label={f.label} className={val ? "active" : ""} value={val} onChange={(e) => set(f, e.target.value)}>
            <option value="">{f.label}</option>{(Array.isArray(f.options) ? f.options : []).map((o) => <option key={o} value={o}>{o}</option>)}</select>;
        }
        if (f.fieldtype === "Check") {
          return <select key={f.fieldname} aria-label={f.label} className={val ? "active" : ""} value={val} onChange={(e) => set(f, e.target.value)}>
            <option value="">{f.label}</option><option value="1">Yes</option><option value="0">No</option></select>;
        }
        if (f.fieldtype === "Link") {
          return <div key={f.fieldname} className={`std-link${val ? " active" : ""}`}><LinkField doctype={String(f.options)} value={val} onChange={(x) => set(f, x)} placeholder={f.label} ariaLabel={f.label} /></div>;
        }
        const type = f.fieldtype === "Date" ? "date" : ["Int", "Float", "Currency"].includes(f.fieldtype) ? "number" : "text";
        return <input key={f.fieldname} type={type} aria-label={f.label} placeholder={f.label} className={val ? "active" : ""} defaultValue={val}
          onBlur={(e) => e.target.value !== val && set(f, e.target.value)} onKeyDown={(e) => e.key === "Enter" && set(f, (e.target as HTMLInputElement).value)} />;
      })}
    </div>
  );
}
