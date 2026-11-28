/** The form-layout model and every operation a designer can perform on it. Pure and immutable: nothing here touches the DOM or the network. */
import type { Cell, Field, GridLayout, GridSection, GridTab } from "./types";

export const MAX_SPAN = 12;
export const WIDE = ["Table", "Text", "JSON"];
export class LayoutError extends Error {}

export interface Drop {
  tab: number; section: number;
  /** an existing row to drop into (at `index`), or null to create a NEW row at `rowAt` */
  row: number | null; index?: number; rowAt?: number;
}
export interface Where { tab: number; section: number; row: number; index: number }

export const defaultSpan = (f?: Pick<Field, "fieldtype">) => (f && WIDE.includes(f.fieldtype) ? 12 : 6);
export const rowSum = (row: Cell[]) => row.reduce((n, c) => n + c.span, 0);
const clone = (l: GridLayout): GridLayout => JSON.parse(JSON.stringify(l));
const sec = (l: GridLayout, d: { tab: number; section: number }): GridSection => {
  const s = l.tabs[d.tab]?.sections[d.section];
  if (!s) throw new LayoutError("That section does not exist");
  return s;
};

export function find(layout: GridLayout, field: string): Where | null {
  for (let t = 0; t < layout.tabs.length; t++) for (let s = 0; s < layout.tabs[t].sections.length; s++)
    for (let r = 0; r < layout.tabs[t].sections[s].rows.length; r++) {
      const i = layout.tabs[t].sections[s].rows[r].findIndex((c) => c.field === field);
      if (i >= 0) return { tab: t, section: s, row: r, index: i };
    }
  return null;
}

export const placedFields = (layout: GridLayout): string[] => layout.tabs.flatMap((t) => t.sections.flatMap((s) => s.rows.flat().map((c) => c.field)));
export const unplaced = (layout: GridLayout, fields: Field[]): Field[] => { const p = new Set(placedFields(layout)); return fields.filter((f) => !p.has(f.fieldname)); };

function dropEmptyRows(l: GridLayout): GridLayout {
  for (const t of l.tabs) for (const s of t.sections) s.rows = s.rows.filter((r) => r.length > 0);
  return l;
}

function equalizeInPlace(row: Cell[]) {
  const base = Math.floor(MAX_SPAN / row.length), extra = MAX_SPAN % row.length;
  row.forEach((c, i) => { c.span = base + (i < extra ? 1 : 0); });
}

function removeCell(l: GridLayout, field: string): Cell | null {
  const w = find(l, field);
  if (!w) return null;
  return l.tabs[w.tab].sections[w.section].rows[w.row].splice(w.index, 1)[0];
}

/** Place a field (from the palette, or already on the form). Drops into an existing row, or makes a new row. */
export function placeField(layout: GridLayout, field: Field | string, to: Drop, span?: number): GridLayout {
  const name = typeof field === "string" ? field : field.fieldname;
  const l = clone(layout);
  const existing = removeCell(l, name);            // keeps the (possibly now empty) row until the end so the drop indices stay valid
  const want = Math.min(MAX_SPAN, Math.max(1, span ?? existing?.span ?? defaultSpan(typeof field === "string" ? undefined : field)));
  const s = sec(l, to);
  if (to.row === null) {
    s.rows.splice(Math.min(Math.max(to.rowAt ?? s.rows.length, 0), s.rows.length), 0, [{ field: name, span: want }]);
  } else {
    const row = s.rows[to.row];
    if (!row) throw new LayoutError("That row does not exist");
    const free = MAX_SPAN - rowSum(row);
    const at = Math.min(Math.max(to.index ?? row.length, 0), row.length);
    if (free >= 1) {
      row.splice(at, 0, { field: name, span: Math.min(want, free) });                // takes the free space (up to the width it wants)
    } else {
      if (row.length >= MAX_SPAN) throw new LayoutError("That row is full: drop on a new row instead");
      row.splice(at, 0, { field: name, span: 1 });
      equalizeInPlace(row);                                                          // a full row is shared out evenly: 6/6, 4/4/4 ...
    }
  }
  return dropEmptyRows(l);
}

/** Move a placed field; `to.index`/`to.rowAt` are interpreted against the layout as the user SEES it (before the move). */
export function moveField(layout: GridLayout, field: string, to: Drop): GridLayout {
  const from = find(layout, field);
  if (!from) throw new LayoutError(`${field} is not on the form`);
  const t = { ...to };
  // Rows are only removed at the very end of placeField, so row numbers stay valid. Within the SAME row, removing the cell shifts those after it left.
  if (to.row !== null && from.tab === to.tab && from.section === to.section && from.row === to.row && t.index !== undefined && from.index < t.index) t.index -= 1;
  return placeField(layout, field, t);
}

/** Set a cell's width. If the row is full, the neighbours to the right give up space first (then those to the left); never below 1 column each. */
export function resizeField(layout: GridLayout, field: string, span: number): GridLayout {
  const l = clone(layout);
  const w = find(l, field);
  if (!w) throw new LayoutError(`${field} is not on the form`);
  const row = l.tabs[w.tab].sections[w.section].rows[w.row];
  const cell = row[w.index];
  const others = rowSum(row) - cell.span;
  let target = Math.min(MAX_SPAN - (row.length - 1), Math.max(1, Math.round(span)));        // every other cell keeps at least one column
  let over = others + target - MAX_SPAN;
  for (const i of [...row.keys()].filter((k) => k > w.index).concat([...row.keys()].filter((k) => k < w.index).reverse())) {
    if (over <= 0) break;
    const give = Math.min(over, row[i].span - 1);
    row[i].span -= give;
    over -= give;
  }
  if (over > 0) target -= over;
  cell.span = Math.max(1, target);
  return l;
}

export function equalizeRow(layout: GridLayout, at: { tab: number; section: number; row: number }): GridLayout {
  const l = clone(layout);
  const row = sec(l, at).rows[at.row];
  if (!row) throw new LayoutError("That row does not exist");
  equalizeInPlace(row);
  return l;
}

export function unplaceField(layout: GridLayout, field: string): GridLayout {
  const l = clone(layout);
  removeCell(l, field);
  return dropEmptyRows(l);
}

export function moveRow(layout: GridLayout, at: { tab: number; section: number; row: number }, dir: -1 | 1): GridLayout {
  const l = clone(layout);
  const rows = sec(l, at).rows;
  const j = at.row + dir;
  if (j < 0 || j >= rows.length) return l;
  [rows[at.row], rows[j]] = [rows[j], rows[at.row]];
  return l;
}

// ---- sections and tabs ----------------------------------------------------------------------------------------------
export function addSection(layout: GridLayout, tab: number, label = "New section", at?: number): GridLayout {
  const l = clone(layout);
  if (!l.tabs[tab]) throw new LayoutError("That tab does not exist");
  l.tabs[tab].sections.splice(at ?? l.tabs[tab].sections.length, 0, { label, collapsible: false, rows: [] });
  return l;
}
export function updateSection(layout: GridLayout, at: { tab: number; section: number }, patch: Partial<Pick<GridSection, "label" | "collapsible">>): GridLayout {
  const l = clone(layout);
  Object.assign(sec(l, at), patch);
  return l;
}
export function removeSection(layout: GridLayout, at: { tab: number; section: number }): GridLayout {
  const l = clone(layout);
  sec(l, at);
  l.tabs[at.tab].sections.splice(at.section, 1);                                  // its fields simply become unplaced: nothing is deleted
  return l;
}
export function moveSection(layout: GridLayout, at: { tab: number; section: number }, dir: -1 | 1): GridLayout {
  const l = clone(layout);
  const list = l.tabs[at.tab]?.sections;
  const j = at.section + dir;
  if (!list || !list[at.section] || j < 0 || j >= list.length) return l;
  [list[at.section], list[j]] = [list[j], list[at.section]];
  return l;
}
export function addTab(layout: GridLayout, label = "New tab"): GridLayout {
  const l = clone(layout);
  l.tabs.push({ label, sections: [{ label: "", collapsible: false, rows: [] }] });
  return l;
}
export function renameTab(layout: GridLayout, tab: number, label: string): GridLayout {
  const l = clone(layout);
  if (!l.tabs[tab]) throw new LayoutError("That tab does not exist");
  l.tabs[tab].label = label;
  return l;
}
export function removeTab(layout: GridLayout, tab: number): GridLayout {
  if (layout.tabs.length <= 1) throw new LayoutError("A form needs at least one tab");
  const l = clone(layout);
  l.tabs.splice(tab, 1);
  return l;
}
export function moveTab(layout: GridLayout, tab: number, dir: -1 | 1): GridLayout {
  const l = clone(layout);
  const j = tab + dir;
  if (!l.tabs[tab] || j < 0 || j >= l.tabs.length) return l;
  [l.tabs[tab], l.tabs[j]] = [l.tabs[j], l.tabs[tab]];
  return l;
}

/** Same rules as the server: the designer refuses to save what the server would refuse. */
export function validate(layout: GridLayout): string[] {
  const errs: string[] = [], seen = new Set<string>();
  if (!layout.tabs.length) return ["The form needs at least one tab"];
  layout.tabs.forEach((t: GridTab, ti) => t.sections.forEach((s, si) => s.rows.forEach((row, ri) => {
    const where = `${t.label || `Tab ${ti + 1}`} / ${s.label || `section ${si + 1}`} / row ${ri + 1}`;
    if (rowSum(row) > MAX_SPAN) errs.push(`${where}: widths add up to ${rowSum(row)} (at most ${MAX_SPAN})`);
    for (const c of row) {
      if (seen.has(c.field)) errs.push(`${where}: ${c.field} is placed twice`);
      seen.add(c.field);
      if (!Number.isInteger(c.span) || c.span < 1 || c.span > MAX_SPAN) errs.push(`${where}: ${c.field} has an invalid width`);
    }
  })));
  return errs;
}
