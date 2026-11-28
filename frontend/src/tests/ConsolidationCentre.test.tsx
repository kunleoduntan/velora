import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ConsolidationCentre from "../components/ConsolidationCentre";

const calls: { url: string; body: string }[] = [];
const ok = (data: unknown) => Promise.resolve(new Response(JSON.stringify({ data }), { status: 200, headers: { "Content-Type": "application/json" } }));
const result = (good: boolean) => ({
  group: "Whole Group", from_date: "2026-01-01", to_date: "2026-11-27", currency: "NGN", ok: good,
  members: [{ company_id: "A", name: "Parent Ltd", currency: "NGN", ownership: 100, method: "Full", profit: 100, rates: {} }, { company_id: "B", name: "Subsidiary Inc", currency: "USD", ownership: 80, method: "Full", profit: 50, rates: {} }],
  lines: [{ key: "1000", label: "Bank", root_type: "Asset", cells: { A: 1000, B: 690000 }, elimination: 0, total: 691000 }, { key: "3000", label: "Share Capital", root_type: "Equity", cells: { A: -1000, B: -690000 }, elimination: 0, total: -691000 }],
  eliminations: [{ description: "Loan to subsidiary", company_one: "A", account_one: "1200", company_two: "B", account_two: "2100", amount: 15000 }],
  income_statement: { income: { rows: [{ key: "4000", label: "Revenue", amount: 300 }], total: 300 }, expense: { rows: [], total: 0 }, profit: 300, profit_attributable_to_owners: 290, non_controlling_profit: 10 },
  balance_sheet: { assets: { rows: [{ key: "1000", label: "Bank", amount: 691000 }], total: 691000 }, liabilities: { rows: [], total: 0 }, equity: { rows: [{ key: "3000", label: "Share Capital", amount: 691000 }], total: 691000 }, current_result: 0, total_equity: 691000, non_controlling_interest: 110, equity_attributable_to_owners: 690890, check: 0 },
  checks: good ? [{ level: "info", code: "scope", message: "Goodwill is not calculated.", company: "" }] : [{ level: "error", code: "member_unavailable", message: "Subsidiary Inc was left out: You do not have access to this company", company: "B" }],
});
let good = true, groups: unknown[] = [{ name: "Whole Group", status: "Active" }];
beforeEach(() => {
  calls.length = 0; good = true; groups = [{ name: "Whole Group", status: "Active" }];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, body: String(init?.body ?? "") });
    if (url.includes("/api/consolidation/companies")) return ok([{ id: "A", name: "Parent Ltd", roles: ["Finance Manager"], current: true }, { id: "B", name: "Subsidiary Inc", roles: ["Finance Manager"] }]);
    if (url.includes("/api/resource/Consolidation%20Group") && (init?.method ?? "GET") === "GET") return ok(groups);
    if (url.includes("/api/resource/Consolidation%20Group")) return ok({ name: "My Group" });
    if (url.endsWith("/api/consolidation/run")) return ok(result(good));
    if (url.endsWith("/api/consolidation/export")) return Promise.resolve(new Response("x", { status: 200, headers: { "Content-Disposition": 'attachment; filename="g.xlsx"' } }));
    return ok([]);
  }));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Consolidation Centre", () => {
  it("runs a group for a period and shows the worksheet with a column per company", async () => {
    render(<ConsolidationCentre />);
    fireEvent.click(await screen.findByRole("button", { name: "Consolidate" }));
    expect(await screen.findByText(/Ready: 2 company/)).toBeTruthy();
    expect(screen.getByText("Subsidiary Inc")).toBeTruthy();
    expect(screen.getAllByText("691,000.00").length).toBeGreaterThan(0);
    const body = JSON.parse(calls.find(c => c.url.endsWith("/api/consolidation/run"))!.body);
    expect(body.group).toBe("Whole Group"); expect(body.save).toBe(false);
  });
  it("says plainly when the result cannot be relied on and lists what to fix", async () => {
    good = false;
    render(<ConsolidationCentre />);
    fireEvent.click(await screen.findByRole("button", { name: "Consolidate" }));
    expect(await screen.findByText(/Not ready to rely on: 1 problem/)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /Checks/ }));
    expect(screen.getByText(/do not have access to this company/)).toBeTruthy();
  });
  it("shows the statements, the eliminations, exports to Excel and saves a run", async () => {
    render(<ConsolidationCentre />);
    fireEvent.click(await screen.findByRole("button", { name: "Consolidate" }));
    await screen.findByText(/Ready/);
    fireEvent.click(screen.getByRole("tab", { name: "Income statement" })); expect(screen.getByText("Attributable to non-controlling interests")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Balance sheet" })); expect(screen.getByText("Equity attributable to owners")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Eliminations" })); expect(screen.getByText("Loan to subsidiary")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Balance sheet" }));
    fireEvent.click(screen.getByRole("button", { name: "Export to Excel" }));
    await waitFor(() => expect(calls.some(c => c.url.endsWith("/api/consolidation/export") && JSON.parse(c.body).view === "balance")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Save this consolidation" }));
    await waitFor(() => expect(calls.filter(c => c.url.endsWith("/api/consolidation/run")).some(c => JSON.parse(c.body).save === true)).toBe(true));
  });
  it("offers a guided set-up when no group exists yet and creates one from the chosen companies", async () => {
    groups = [];
    render(<ConsolidationCentre />);
    expect(await screen.findByText("Set up a consolidation group")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Include Subsidiary Inc"));            // leave the subsidiary out
    fireEvent.click(screen.getByRole("button", { name: "Create group" }));
    await waitFor(() => expect(calls.some(c => c.url.includes("/api/resource/Consolidation%20Group") && c.body.includes("group_name"))).toBe(true));
    const post = calls.find(c => c.body.includes("group_name"))!;
    expect(JSON.parse(post.body).members).toEqual([{ company_id: "A", include: 1, ownership_percent: 100, method: "Full" }]);
  });
});
