import type { Field, GridColumn, Meta } from "./types";

export const MAX_WIDTH = 100; // per-column width only; there is no aggregate width or column-count ceiling
export interface Col { field: Field; width: number }
const LAYOUT = ["Section Break", "Column Break", "Tab Break"];

/** Every field a grid could show: real, visible, non-table fields (a child row may have any number of them). */
export const gridFields = (m: Meta): Field[] => m.fields.filter((f) => !LAYOUT.includes(f.fieldtype) && f.fieldtype !== "Table" && !f.hidden);

const IMPORTANT_NAMES = /^(item|item_code|item_name|account|account_head|expense_account|income_account|warehouse|qty|quantity|uom|rate|price|amount|base_amount|debit|credit|party|customer|supplier|employee|project|cost_center|description|posting_date|transaction_date|due_date|schedule_date|reference|reference_name|status)$/i;
const SMALL_TYPES = new Set(["Date", "Datetime", "Time", "Int", "Check", "Float", "Percent", "Currency"]);
const WIDE_TYPES = new Set(["Text", "Small Text", "Long Text", "Code", "JSON"]);

/** Type-aware default width in 70px grid units; independent of the total table width. */
export function defaultColumnWidth(f: Field): number {
  // Widths are whole 70px units. Persisted grid settings are validated by the server as integers.
  if (SMALL_TYPES.has(f.fieldtype)) return 2;
  if (f.fieldtype === "Link" || f.fieldtype === "Dynamic Link") return 4;
  if (WIDE_TYPES.has(f.fieldtype) || /description|remarks|narration|address|comment|notes/i.test(f.fieldname)) return 6;
  if (/name|party|account|employee|customer|supplier|warehouse|project/i.test(f.fieldname)) return 4;
  return 3;
}

/** A new grid starts small: at most this many columns. Everything else is one click away in the Columns dialog or the row editor. */
export const DEFAULT_GRID_COLUMNS = 6;
const PRIORITY = ["item_code", "item", "account", "item_name", "qty", "quantity", "rate", "price", "amount", "uom", "debit", "credit", "warehouse", "description", "party", "employee", "customer", "supplier"];

/** The few columns a person needs first (item code, name, quantity, rate, amount ...), in the form's own order. Explicit list-view flags win. */
const TECHNICAL = /^(source_line|source_doctype|source_document|purchase_receipt_line|matched_quantity)$/;
export function defaultGridFields(m: Meta): Field[] {
  const all = gridFields(m).filter((f) => f.fieldname !== "idx");
  const lean = all.filter((f) => !TECHNICAL.test(f.fieldname) || f.in_list_view);   // bookkeeping links stay selectable in Columns, never lead
  const fields = lean.length ? lean : all;
  if (fields.length <= DEFAULT_GRID_COLUMNS) return fields;                // a small table simply shows what it has
  const rank = (f: Field, i: number) => {
    if (f.in_list_view) return -1000 + i;                                  // a field the designer flagged for the list always comes first
    const p = PRIORITY.indexOf(f.fieldname);
    return p >= 0 ? p : (f.required ? 100 : IMPORTANT_NAMES.test(f.fieldname) ? 150 : 200);
  };
  const picked = fields.map((f, i) => ({ f, i, r: rank(f, i) })).sort((a, b) => a.r - b.r || a.i - b.i).slice(0, DEFAULT_GRID_COLUMNS).map((x) => x.f);
  return fields.filter((f) => picked.includes(f));                       // back into the form's own order
}

const key = (child: string) => `velora.grid.${child}`;
export function loadPersonal(child: string): GridColumn[] | null {
  try { const v = JSON.parse(localStorage.getItem(key(child)) ?? "null"); return Array.isArray(v) ? v : null; } catch { return null; }
}
export function savePersonal(child: string, cols: GridColumn[] | null) {
  try { if (cols) localStorage.setItem(key(child), JSON.stringify(cols)); else localStorage.removeItem(key(child)); } catch { /* private mode: the setting just won't persist */ }
}

/** Which columns the grid shows, in what order and how wide:  your own setting > the company/app setting > a sensible default. */
export function resolveColumns(m: Meta, personal?: GridColumn[] | null, shared?: GridColumn[] | null): Col[] {
  const fields = Object.fromEntries(gridFields(m).map((f) => [f.fieldname, f]));
  for (const source of [personal, shared, m.grid_columns]) {
    const cols = (source ?? []).filter((c) => fields[c.field]).map((c) => {
      const raw = Number(c.width);
      const width = Number.isFinite(raw) ? Math.round(raw) : 2;
      return { field: fields[c.field], width: Math.min(MAX_WIDTH, Math.max(1, width)) };
    });
    if (cols.length) return cols;
  }
  // All other fields remain available in the Columns dialog, but are not exposed on first use.
  return defaultGridFields(m).map((field) => ({ field, width: defaultColumnWidth(field) }));
}

export const total = (cols: { width: number }[]) => cols.reduce((n, c) => n + c.width, 0);
export const toColumns = (cols: Col[]): GridColumn[] => cols.map((c) => ({ field: c.field.fieldname, width: c.width }));

export function reorder<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
  const next = [...list];
  next.splice(to, 0, next.splice(from, 1)[0]);
  return next;
}

/** Freeze panes, as in a spreadsheet: the first FREEZE_COLUMNS columns stay in view while the rest scroll sideways. */
export const FREEZE_COLUMNS = 5;
const freezeKey = (child: string) => `velora.freeze.${child}`;
export function loadFreeze(child: string): number {
  try { const v = JSON.parse(localStorage.getItem(freezeKey(child)) ?? "null"); return Number.isInteger(v) && v >= 0 && v <= 12 ? v : FREEZE_COLUMNS; } catch { return FREEZE_COLUMNS; }
}
export function saveFreeze(child: string, n: number | null) {
  try { if (n === null || n === FREEZE_COLUMNS) localStorage.removeItem(freezeKey(child)); else localStorage.setItem(freezeKey(child), JSON.stringify(n)); } catch { /* the setting just won't persist */ }
}
/** How many of the wanted columns can be frozen and still leave at least 40% of the width to scroll (never fewer than one). */
export function frozenFits(widths: number[], wanted: number, available: number): number {
  if (wanted <= 0 || !widths.length) return 0;
  let used = 0, n = 0;
  for (const w of widths.slice(0, wanted)) { if (n >= 1 && available > 0 && used + w > available * 0.6) break; used += w; n++; }
  return n;
}
