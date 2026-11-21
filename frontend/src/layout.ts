import type { Field } from "./types";

export interface Column { label?: string; fields: Field[] }
export interface Section { label: string; columns: Column[] }
export interface Tab { label: string; sections: Section[] }

const isLayout = (f: Field) => f.fieldtype === "Tab Break" || f.fieldtype === "Section Break" || f.fieldtype === "Column Break";

/** Turn the flat field list into Tab > Section > Column > Field (Frappe's break semantics). */
export function buildLayout(fields: Field[]): Tab[] {
  const tabs: Tab[] = [];
  const tab = () => tabs[tabs.length - 1];
  const ensureTab = () => { if (!tabs.length) tabs.push({ label: "Details", sections: [] }); };
  const ensureSection = () => { ensureTab(); if (!tab().sections.length) tab().sections.push({ label: "", columns: [] }); };
  const section = () => tab().sections[tab().sections.length - 1];
  const ensureColumn = () => { ensureSection(); if (!section().columns.length) section().columns.push({ fields: [] }); };

  for (const f of fields) {
    if (f.fieldtype === "Tab Break") {
      tabs.push({ label: f.label || "Details", sections: [] });
    } else if (f.fieldtype === "Section Break") {
      ensureTab();
      tab().sections.push({ label: f.label || "", columns: [] });
    } else if (f.fieldtype === "Column Break") {
      ensureSection();
      section().columns.push({ label: f.label || undefined, fields: [] });
    } else if (!isLayout(f)) {
      ensureColumn();
      const cols = section().columns;
      cols[cols.length - 1].fields.push(f);
    }
  }
  // drop empty columns/sections/tabs left by consecutive breaks
  return tabs
    .map((t) => ({
      ...t,
      sections: t.sections
        .map((s) => ({ ...s, columns: s.columns.filter((c) => c.fields.length) }))
        .filter((s) => s.columns.length),
    }))
    .filter((t) => t.sections.length);
}
