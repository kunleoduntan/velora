import { vi } from "vitest";
import type { ThemeState } from "../api";
import customer from "./fixtures/customer.meta.json";
import contact from "./fixtures/customer_contact.meta.json";
import group from "./fixtures/customer_group.meta.json";
import so from "./fixtures/sales_order.meta.json";
import soItem from "./fixtures/sales_order_item.meta.json";

export const META: Record<string, unknown> = {
  Customer: customer, "Customer Contact": contact, "Customer Group": group, "Sales Order": so, "Sales Order Item": soItem,
};

export interface Call { key: string; body: any; url: URL; headers?: Record<string, string> }
type Handler = (req: { url: URL; body: any }) => unknown | Promise<unknown>;

/** Stub fetch with a route table keyed "METHOD /path". Returns the recorded calls. */
export function mockServer(routes: Record<string, Handler | string>) {
  const calls: Call[] = [];
  const all: Record<string, Handler | string> = {
    "GET /api/files": () => [],                    // the attachment panel of every saved form
    "GET /api/app-extensions": () => [],           // loaded once when the Desk starts
    ...Object.fromEntries(Object.keys(META).map((n) => [`GET /api/meta/${n}`, () => META[n]])),
    ...routes,
  };
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const key = `${init?.method ?? "GET"} ${decodeURIComponent(url.pathname)}`;
    const headers = (init?.headers ?? {}) as Record<string, string>;
    const body = init?.body ? (headers["Content-Type"] === "application/octet-stream" ? init.body : JSON.parse(String(init.body))) : undefined;     // a file is kept as it is
    calls.push({ key, body, url, headers });
    const h = all[key];
    if (h === undefined) return new Response(JSON.stringify({ error: "NotMocked", message: `no mock for ${key}` }), { status: 404 });
    if (typeof h === "string") return new Response(h, { status: 200 });
    const out = await h({ url, body });
    return out instanceof Response ? out : new Response(JSON.stringify({ data: out }), { status: 200 });
  }));
  return calls;
}

export const fail = (status: number, error: string, message: string) =>
  new Response(JSON.stringify({ error, message }), { status });

const BASE_SPEC = { preset: "velora", brand: null, accent: null, radius: "square", density: "comfortable", font: "system", default_mode: null, allow_user_override: true, brand_name: "" };
const TOK = (bg: string, brand: string) => ({ "--bg": bg, "--card": "#ffffff", "--text": "#222222", "--muted": "#555555", "--brand": brand, "--on-brand": "#ffffff", "--brand-text": brand, "--brand-soft": "#eef", "--header-bg": "#eee", "--zebra": "#f7f7f7", "--ok": "#116611", "--ok-soft": "#dfd", "--danger": "#aa1111", "--danger-soft": "#fdd", "--line": "#ddd" });

/** A compiled theme as the server returns it (same shape as GET /api/theme). */
export function themeState(over: { default_mode?: string; spec?: Record<string, unknown>; can_edit?: boolean; audit?: unknown[]; brand?: string; css?: string } = {}): ThemeState {
  const brand = over.brand ?? "#0f6cbd";
  const audit = over.audit ?? Array.from({ length: 40 }, (_, i) => ({ mode: i % 2 ? "dark" : "light", pair: `pair ${i}`, fg: "#000", bg: "#fff", ratio: 12.5, required: 4.5, pass: true }));
  return {
    spec: { ...BASE_SPEC, ...(over.spec ?? {}) }, css: over.css ?? ":root{--brand:" + brand + "}", default_mode: over.default_mode ?? "system", brand,
    passed: (audit as { pass: boolean }[]).every((a) => a.pass), audit, tokens: { light: TOK("#f3f2f1", brand), dark: TOK("#1b1a19", "#479ef5") },
    excel: { header_bg: "d5e9ff", header_text: "0b3a63", rule: "3b82c4", section_bg: "f1f7fd", total_bg: "e7f1fb", title: "0f4c81" },
    presets: [
      { name: "velora", label: "Velora", description: "Clean enterprise blue (default)", brand: "#0f6cbd", default_mode: "system", source: "velora" },
      { name: "farepoint", label: "Farepoint", description: "Bold magenta", brand: "#e91e8c", default_mode: "system", source: "vic_theme" },
      { name: "verdant", label: "Verdant", description: "Natural green", brand: "#059669", default_mode: "system", source: "vic_theme" },
    ],
    can_edit: over.can_edit ?? true,
  } as unknown as ThemeState;
}

export const reportDef = (over: Record<string, unknown> = {}) => ({
  name: "Sales by Customer Group", module: "Demo", description: "Sales order value grouped by customer group.", ref_doctype: "Sales Order", type: "script", can_export: true,
  filters: [
    { fieldname: "from_date", label: "From Date", fieldtype: "Date", default: "Year Start" },
    { fieldname: "to_date", label: "To Date", fieldtype: "Date", default: "Today" },
    { fieldname: "customer_group", label: "Customer Group", fieldtype: "Link", options: "Customer Group" },
    { fieldname: "status", label: "Status", fieldtype: "Select", options: ["Active", "Blocked"] },
    { fieldname: "include_drafts", label: "Include drafts", fieldtype: "Check" },
  ], ...over,
});

export const reportResult = (over: Record<string, unknown> = {}) => ({
  title: "Sales by Customer Group", subtitle: "1 Jan 2026 to 7 Nov 2026", company: "Velora Technologies", currency: "NGN", report_name: "Sales by Customer Group",
  generated_at: "07 Nov 2026 10:00 UTC", filters: [["Customer Group", "Retail"]], notes: [],
  summary: [{ label: "Orders", value: 10, fieldtype: "Int" }, { label: "Revenue", value: 10750.25, fieldtype: "Currency" }],
  columns: [{ fieldname: "name", label: "Customer", fieldtype: "Data" }, { fieldname: "orders", label: "Orders", fieldtype: "Int" }, { fieldname: "amount", label: "Amount", fieldtype: "Currency" }, { fieldname: "share", label: "Share", fieldtype: "Percent" }],
  rows: [
    { type: "header", indent: 0, values: { name: "Retail" }, children: null },
    { type: "data", indent: 1, values: { name: "Acme Ltd", orders: 3, amount: 1250.5, share: 0.4 }, children: null },
    { type: "data", indent: 1, values: { name: "Zenith Foods", orders: 2, amount: -300.25, share: 0.1 }, children: null },
    { type: "subtotal", indent: 0, values: { name: "Total Retail", orders: 5, amount: 950.25 }, children: [1, 2] },
    { type: "data", indent: 1, values: { name: "Idle Co", orders: 0, amount: 0, share: 0 }, children: null },
    { type: "total", indent: 0, values: { name: "TOTAL", orders: 5, amount: 950.25 }, children: [3] },
  ], ...over,
});
