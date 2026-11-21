import { useEffect, useState } from "react";
import type { Field, FieldAppearance, Meta } from "../types";
import Toggle from "../ui/Toggle";
import LinkField from "./LinkField";
import TableField from "./TableField";

export interface ControlProps {
  field: Field;
  value: unknown;
  onChange: (value: unknown) => void;
  readOnly?: boolean;
  compact?: boolean; // inside a child-table cell
  childMetas?: Record<string, Meta>;
  invalid?: boolean;
  required?: boolean;
  appearance?: FieldAppearance;
  onChildChange?: (row: Record<string, unknown>, rowIndex: number, fieldname: string) => void;
}

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));

function JsonControl({ value, onChange, readOnly }: { value: unknown; onChange: (v: unknown) => void; readOnly?: boolean }) {
  const [text, setText] = useState(value == null ? "" : JSON.stringify(value, null, 2));
  const [bad, setBad] = useState(false);
  useEffect(() => { setText(value == null ? "" : JSON.stringify(value, null, 2)); }, [value]);
  return (
    <textarea
      className={bad ? "invalid" : ""} rows={4} value={text} readOnly={readOnly}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (!text.trim()) { setBad(false); return onChange(null); }
        try { onChange(JSON.parse(text)); setBad(false); } catch { setBad(true); }
      }}
    />
  );
}

/** Renders the right input for a field's type. Layout types never reach here. */
export default function FieldControl(p: ControlProps) {
  const { field: f, value, onChange, readOnly, compact } = p;
  const appearance = p.appearance ?? {};
  const id = `f_${f.fieldname}`;
  const common = { id: compact ? undefined : id, readOnly, disabled: false, className: p.invalid ? "invalid" : "", placeholder: appearance.placeholder || undefined };

  let control: JSX.Element;
  switch (f.fieldtype) {
    case "Check":
      control = compact
        ? <input type="checkbox" checked={!!value && value !== "0"} disabled={readOnly} onChange={(e) => onChange(e.target.checked ? 1 : 0)} />
        : <Toggle id={common.id} checked={!!value && value !== "0"} disabled={readOnly} onChange={(v) => onChange(v ? 1 : 0)} />;
      break;
    case "Select":
      control = (
        <select id={common.id} className={common.className} value={str(value)} disabled={readOnly}
          onChange={(e) => onChange(e.target.value || null)}>
          <option value=""></option>
          {(Array.isArray(f.options) ? f.options : []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
      break;
    case "Text":
      control = <textarea {...common} rows={3} value={str(value)} onChange={(e) => onChange(e.target.value)} />;
      break;
    case "Int": case "Float": case "Currency":
      control = <input {...common} type="number" step={f.fieldtype === "Int" ? 1 : "any"} value={str(value)}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />;
      break;
    case "Date":
      control = <input {...common} type="date" value={str(value).slice(0, 10)} onChange={(e) => onChange(e.target.value || null)} />;
      break;
    case "Datetime":
      control = <input {...common} type="datetime-local" value={str(value).slice(0, 16)} onChange={(e) => onChange(e.target.value || null)} />;
      break;
    case "Link":
      control = <LinkField doctype={String(f.options)} value={str(value)} readOnly={readOnly} invalid={p.invalid} id={common.id}
        onChange={(v) => onChange(v || null)} filters={f.link_filters} />;
      break;
    case "JSON":
      control = <JsonControl value={value} onChange={onChange} readOnly={readOnly} />;
      break;
    case "Table":
      control = <TableField field={f} rows={(value as Record<string, unknown>[]) ?? []} onChange={onChange}
        onChildChange={p.onChildChange} readOnly={readOnly} childMeta={p.childMetas?.[String(f.options)]} childMetas={p.childMetas} />;
      break;
    default: // Data
      control = <input {...common} type="text" maxLength={f.length ?? 255} value={str(value)} onChange={(e) => onChange(e.target.value)} />;
  }

  if (compact) return control;
  const description = appearance.help_text || (appearance.show_description === false ? "" : f.description || "");
  const label = <label htmlFor={id}>{f.label}{(p.required ?? f.required) && <span className="req" title="required"> *</span>}</label>;
  return (
    <div className={`field field-${f.fieldtype.toLowerCase().replace(" ", "-")} field-size-${appearance.control_size ?? "medium"} field-style-${appearance.display_style ?? "standard"} label-${appearance.label_position ?? "top"}${readOnly && appearance.readonly_style ? " readonly-emphasis" : ""}${p.invalid ? " has-error" : ""}`} data-fieldname={f.fieldname}>
      {label}
      <div className="field-control-wrap">{control}</div>
      {description && <small>{description}</small>}
    </div>
  );
}
