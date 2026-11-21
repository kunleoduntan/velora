import type { Field, Meta } from "./types";

/** UI-level filter. Operators "is set"/"is not set" and the %-wrapping of like are translated by toApi(). */
export interface Filter { field: string; op: string; value: unknown }
export type ApiFilter = [string, string, unknown];

const LABELS: Record<string, string> = {
  "=": "equals", "!=": "not equals", like: "contains", "not like": "does not contain", in: "is one of", "not in": "is none of",
  ">": "greater than", "<": "less than", ">=": "at least", "<=": "at most", between: "between", "is set": "is set", "is not set": "is not set",
};
export const opLabel = (op: string) => LABELS[op] ?? op;
export const needsValue = (op: string) => !op.startsWith("is ");

export const SYSTEM_FIELDS: Record<string, { label: string; fieldtype: Field["fieldtype"] }> = {
  name: { label: "ID", fieldtype: "Data" },
  owner: { label: "Created By", fieldtype: "Data" },
  creation: { label: "Created On", fieldtype: "Datetime" },
  modified: { label: "Last Modified", fieldtype: "Datetime" },
  modified_by: { label: "Last Modified By", fieldtype: "Data" },
  docstatus: { label: "Status", fieldtype: "Int" },
};

const LAYOUT = ["Section Break", "Column Break", "Tab Break", "Table"];

export function fieldInfo(meta: Meta, fieldname: string): { label: string; fieldtype: Field["fieldtype"]; field?: Field } {
  const f = meta.fields.find((x) => x.fieldname === fieldname);
  if (f) return { label: f.label, fieldtype: f.fieldtype, field: f };
  const s = SYSTEM_FIELDS[fieldname];
  return s ?? { label: fieldname, fieldtype: "Data" };
}

/** Everything a user may filter, sort, show or group by. */
export function dataFields(meta: Meta): { fieldname: string; label: string; fieldtype: Field["fieldtype"] }[] {
  const own = meta.fields.filter((f) => !LAYOUT.includes(f.fieldtype)).map((f) => ({ fieldname: f.fieldname, label: f.label, fieldtype: f.fieldtype }));
  const sys = Object.entries(SYSTEM_FIELDS)
    .filter(([k]) => k !== "docstatus" || meta.is_submittable)
    .map(([fieldname, v]) => ({ fieldname, ...v }));
  return [sys[0], ...own, ...sys.slice(1)];
}

export function opsFor(ft: Field["fieldtype"], fieldname = ""): string[] {
  if (fieldname === "docstatus") return ["=", "!="];
  switch (ft) {
    case "Data": case "Text": return ["like", "not like", "=", "!=", "in", "not in", "is set", "is not set"];
    case "Select": case "Link": return ["=", "!=", "in", "not in", "is set", "is not set"];
    case "Int": case "Float": case "Currency": return ["=", "!=", ">", "<", ">=", "<=", "between", "is set", "is not set"];
    case "Date": return ["=", ">", "<", ">=", "<=", "between", "is set", "is not set"];
    case "Datetime": return [">", "<", ">=", "<=", "between", "is set", "is not set"];  // a day = between d and d
    case "Check": return ["="];
    default: return ["=", "!=", "is set", "is not set"];
  }
}

export function isComplete(f: Filter): boolean {
  if (!needsValue(f.op)) return true;
  if (f.op === "between") return Array.isArray(f.value) && f.value.length === 2 && f.value.every((v) => v !== "" && v != null);
  if (Array.isArray(f.value)) return f.value.length > 0;
  return f.value !== "" && f.value !== null && f.value !== undefined;
}

export function toApi(filters: Filter[]): ApiFilter[] {
  return filters.filter(isComplete).map((f): ApiFilter => {
    if (f.op === "is set" || f.op === "is not set") return [f.field, "is", f.op.slice(3)];
    if (f.op === "like" || f.op === "not like") { const v = String(f.value); return [f.field, f.op, v.includes("%") ? v : `%${v}%`]; }
    if (f.op === "in" || f.op === "not in") {
      const arr = Array.isArray(f.value) ? f.value : String(f.value).split(",").map((x) => x.trim()).filter(Boolean);
      return [f.field, f.op, arr];
    }
    return [f.field, f.op, f.value];
  });
}

/** Inverse of toApi(): turn a stored API filter back into what the filter editor shows. */
export function fromApi(f: ApiFilter): Filter {
  const [field, op, value] = f;
  if (op === "is") return { field, op: `is ${value}`, value: "" };
  if ((op === "like" || op === "not like") && typeof value === "string") return { field, op, value: value.replace(/^%|%$/g, "") };
  return { field, op, value };
}

const STATUS = ["Draft", "Submitted", "Cancelled"];
export function describe(f: Filter, meta: Meta): string {
  const { label } = fieldInfo(meta, f.field);
  if (!needsValue(f.op)) return `${label} ${f.op}`;
  const v = Array.isArray(f.value) ? f.value.join(f.op === "between" ? " and " : ", ") : f.field === "docstatus" ? STATUS[Number(f.value)] : String(f.value);
  return `${label} ${opLabel(f.op)} ${v}`;
}
