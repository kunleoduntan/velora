import type { FieldType } from "./types";

export const isNumeric = (ft: FieldType | string) => ft === "Int" || ft === "Float" || ft === "Currency";

export interface DisplayFormat { date: string; number: string }
/** How this company shows dates and numbers (set in Settings; every list, report and form follows it). */
let display: DisplayFormat = { date: "YYYY-MM-DD", number: "1,234.56" };
export const setDisplayFormat = (f: Partial<DisplayFormat> | null) => { display = { date: f?.date || "YYYY-MM-DD", number: f?.number || "1,234.56" }; };
export const getDisplayFormat = () => display;

const SEPARATORS: Record<string, [string, string]> = { "1,234.56": [",", "."], "1.234,56": [".", ","], "1 234,56": ["\u00a0", ","], "1'234.56": ["'", "."] };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatNumber(n: number, min: number, max: number): string {
  const [group, decimal] = SEPARATORS[display.number] ?? SEPARATORS["1,234.56"];
  return n.toLocaleString("en-US", { minimumFractionDigits: min, maximumFractionDigits: max }).replace(/[,.]/g, (c) => (c === "," ? group : decimal));
}

/** "2026-12-31" shown the way this company chose; anything that is not an ISO date is returned as it came. */
export function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const [, y, mo, d] = m;
  switch (display.date) {
    case "DD/MM/YYYY": return `${d}/${mo}/${y}`;
    case "MM/DD/YYYY": return `${mo}/${d}/${y}`;
    case "DD-MMM-YYYY": return `${d}-${MONTHS[Number(mo) - 1]}-${y}`;
    case "DD MMM YYYY": return `${d} ${MONTHS[Number(mo) - 1]} ${y}`;
    default: return `${y}-${mo}-${d}`;
  }
}

export function formatCell(value: unknown, ft: FieldType | string): string {
  if (value === null || value === undefined || value === "") return "";
  switch (ft) {
    case "Currency": return formatNumber(Number(value), 2, 2);
    case "Float": return formatNumber(Number(value), 0, 6);
    case "Int": return formatNumber(Number(value), 0, 0);
    case "Date": return formatDate(String(value).slice(0, 10));
    case "Datetime": return `${formatDate(String(value).slice(0, 10))} ${String(value).slice(11, 16)}`.trim();
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
  if (ft === "Date" || ft === "Datetime") {
    const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}:\d{2}))?/.exec(String(value));
    if (m) return `${m[3]}/${m[2]}/${m[1]}${ft === "Datetime" && m[4] ? ` ${m[4]}` : ""}`;
  }
  return String(value);
}
