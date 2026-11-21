import type { Filter } from "./filters";

export interface Sort { field: string; order: "asc" | "desc" }
export interface SavedView { name: string; filters: Filter[]; columns: string[] | null; sort: Sort | null }
export interface ListSettings {
  columns: string[] | null;   // null = the DocType's in_list_view columns
  sort: Sort | null;          // null = the DocType's default sort
  pageSize: number;
  filters: Filter[];
  views: SavedView[];
  widths: Record<string, number>;   // column widths in px (user-resized)
  pinned: string[];                 // sticky columns (the ID column is always pinned)
  totals: boolean;                  // show the total row
  freeze?: number;                  // 0 = no automatic freeze; unset = the ID column and the first four columns stay in view while scrolling sideways
}

export const PAGE_SIZES = [20, 50, 100, 500];
export const DEFAULTS: ListSettings = { columns: null, sort: null, pageSize: 20, filters: [], views: [], widths: {}, pinned: [], totals: false };

const key = (user: string, doctype: string) => `velora.list.${user}.${doctype}`;

/** Per-user, per-DocType list preferences (stored in this browser). */
export function loadSettings(user: string, doctype: string): ListSettings {
  try {
    const raw = JSON.parse(localStorage.getItem(key(user, doctype)) || "null");
    return raw ? { ...DEFAULTS, ...raw } : { ...DEFAULTS };
  } catch { return { ...DEFAULTS }; }
}

export function saveSettings(user: string, doctype: string, s: ListSettings) {
  try { localStorage.setItem(key(user, doctype), JSON.stringify(s)); } catch { /* storage full/blocked: preferences just won't persist */ }
}

const LIST_LAYOUT = ["Section Break", "Column Break", "Tab Break", "Table", "Text", "Small Text", "Long Text", "Code", "JSON", "Attach", "Attach Image"];
const LIST_IMPORTANT = /(^|_)(status|date|posting_date|due_date|party|customer|supplier|employee|employee_name|item|item_code|amount|total|grand_total|net_pay|balance|department|branch|type|stage)$/;
export const PRESET_LIST_COLUMNS = 7;
export const MIN_LIST_COLUMNS = 3;       // a DocType that declares fewer list columns than this is topped up

/** The columns a list shows before anyone customises it: the DocType's own list-view fields, topped up to a useful
 *  preset with required / filterable / well-known fields so a list is never nearly empty. Users can still add any number. */
export function defaultListColumns(fields: { fieldname: string; fieldtype: string; in_list_view?: boolean; required?: boolean; in_standard_filter?: boolean; hidden?: boolean }[]): string[] {
  const usable = fields.filter((f) => !LIST_LAYOUT.includes(f.fieldtype) && !f.hidden && f.fieldname !== "name");
  const chosen = usable.filter((f) => f.in_list_view).map((f) => f.fieldname);
  if (chosen.length >= MIN_LIST_COLUMNS) return chosen;      // curated by the DocType author: respected as is
  const rest = usable.filter((f) => !chosen.includes(f.fieldname)).map((f, i) => ({ f, i, score: (f.required ? 30 : 0) + (f.in_standard_filter ? 20 : 0) + (LIST_IMPORTANT.test(f.fieldname) ? 25 : 0) }))
    .filter((x) => x.score > 0).sort((a, b) => b.score - a.score || a.i - b.i);
  return [...chosen, ...rest.slice(0, PRESET_LIST_COLUMNS - chosen.length).map((x) => x.f.fieldname)];
}
