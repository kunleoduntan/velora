import type { FieldType } from "./types";

export const isNumeric = (ft: FieldType | string) => ft === "Int" || ft === "Float" || ft === "Currency";

export function formatCell(value: unknown, ft: FieldType | string): string {
  if (value === null || value === undefined || value === "") return "";
  switch (ft) {
    case "Currency": return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    case "Float": return Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 });
    case "Int": return Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
    case "Date": return String(value).slice(0, 10);
    case "Datetime": return String(value).slice(0, 16).replace("T", " ");
    case "Check": return value && value !== "0" ? "Yes" : "No";
    case "JSON": return typeof value === "string" ? value : JSON.stringify(value);
    default: return String(value);
  }
}

/** Tab-separated text that pastes into Excel/Sheets as a grid (cells with tabs, quotes or newlines are quoted). */
export function toTsv(headers: string[], rows: string[][]): string {
  const cell = (v: string) => (/[\t\n\r"]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return [headers, ...rows].map((r) => r.map(cell).join("\t")).join("\n");
}

export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* fall through to the legacy path */ }
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  ta.remove();
  return ok;
}

/** Report cells: accounting style - negatives in (parentheses), zero as a dash, percentages from fractions. */
export function formatReportValue(value: unknown, ft: string): string {
  if (value === null || value === undefined || value === "") return "";
  if (ft === "Check") return value ? "Yes" : "No";
  if (["Currency", "Float", "Int", "Percent"].includes(ft)) {
    const n = Number(value);
    if (Number.isNaN(n)) return String(value);
    if (n === 0) return "-";
    const body = ft === "Percent" ? `${Math.abs(n * 100).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
      : Math.abs(n).toLocaleString(undefined, ft === "Int" ? { maximumFractionDigits: 0 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return n < 0 ? `(${body})` : body;
  }
  if (ft === "Date") return String(value).slice(0, 10);
  if (ft === "Datetime") return String(value).slice(0, 16).replace("T", " ");
  return String(value);
}
