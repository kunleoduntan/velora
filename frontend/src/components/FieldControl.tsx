import { useEffect, useState } from "react";
import { api } from "../api";
import type { Doc, Field, FieldAppearance, Meta } from "../types";
import Toggle from "../ui/Toggle";
import LinkField from "./LinkField";
import NumberInput from "./NumberInput";
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
  /** Inside a child table: the row being edited and the document that owns it (a Batch picker needs the row's item and warehouse). */
  row?: Record<string, unknown>;
  parentDoc?: Doc | null;
  /** Table only: header values every NEW row starts with (the header warehouse). */
  rowDefaults?: Record<string, unknown>;
}

/** What a batch offers the user: stock on hand, expiry, and which one the first-expiry-first-out rule puts first. */
export function batchTitle(b: { quantity: number; expiry_date?: string | null; expired: boolean; suggested: boolean; days_left?: number | null }, showStock: boolean): string {
  const parts: string[] = [];
  if (showStock) parts.push(`${b.quantity} in stock`);
  if (b.expiry_date) parts.push(b.expired ? `EXPIRED ${b.expiry_date}` : `exp ${b.expiry_date}`);
  if (b.suggested) parts.push("use first");
  return parts.join(" · ");
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
      control = <NumberInput kind={f.fieldtype as "Int" | "Float" | "Currency"} id={common.id} className={common.className} readOnly={readOnly}
        placeholder={common.placeholder} value={value} onChange={onChange} />;
      break;
    case "Date":
      control = <input {...common} type="date" value={str(value).slice(0, 10)} onChange={(e) => onChange(e.target.value || null)} />;
      break;
    case "Datetime":
      control = <input {...common} type="datetime-local" value={str(value).slice(0, 16)} onChange={(e) => onChange(e.target.value || null)} />;
      break;
    case "Link":
    {
      const item = String(p.row?.item_code ?? ""), wh = String(p.row?.warehouse ?? p.parentDoc?.warehouse ?? ""), dt = String(p.parentDoc?.doctype ?? "");
      const batchRow = f.options === "Batch" && !!p.row && !!p.parentDoc;
      control = <LinkField doctype={String(f.options)} value={str(value)} readOnly={readOnly} invalid={p.invalid} id={common.id}
        onChange={(v) => onChange(v || null)} filters={f.link_filters}
        scope={batchRow ? `${item}|${wh}|${dt}` : undefined}
        fetcher={batchRow ? async (txt, signal) => item
          ? (await api.batchesFor(item, wh, txt, dt, signal)).map((b) => ({ name: b.name, title: batchTitle(b, true) }))
          : [] : undefined} />;
    }
      break;
    case "JSON":
      control = <JsonControl value={value} onChange={onChange} readOnly={readOnly} />;
      break;
    case "Table":
      control = <TableField field={f} rows={(value as Record<string, unknown>[]) ?? []} onChange={onChange}
        onChildChange={p.onChildChange} readOnly={readOnly} childMeta={p.childMetas?.[String(f.options)]} childMetas={p.childMetas}
        parentDoc={p.parentDoc} rowDefaults={p.rowDefaults} />;
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
