import { beforeEach, describe, expect, it, vi } from "vitest";
import { setSession } from "../api";
import { loadScripts, resetScripts, trigger, velora, type FormApi } from "../clientScripts";
import { mockServer } from "./helpers";
import customerJs from "./fixtures/customer.form.js?raw";
import listJs from "./fixtures/customer.list.js?raw";

const frm = (doc: object) => ({ doc } as unknown as FormApi);

beforeEach(() => { resetScripts(); setSession({ user: "u", roles: "r" }); });

describe("client script runtime", () => {
  it("runs registered handlers per event", () => {
    const seen: string[] = [];
    velora.ui.form.on("X", { refresh: () => seen.push("a") });
    velora.ui.form.on("X", { refresh: () => seen.push("b"), qty: () => seen.push("qty") });
    trigger("X", "refresh", frm({}));
    trigger("X", "qty", frm({}));
    trigger("Other", "refresh", frm({}));
    expect(seen).toEqual(["a", "b", "qty"]);
  });

  it("passes child row and row index to child-table handlers", () => {
    const row = { item_code: "ITEM-1" };
    const seen: unknown[] = [];
    velora.ui.form.on("Sales Invoice Line", { item_code: (_frm, child, index) => seen.push([child, index]) });
    trigger("Sales Invoice Line", "item_code", frm({}), false, row, 2);
    expect(seen).toEqual([[row, 2]]);
  });

  it("isolates a failing handler, but lets validate abort when asked", () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    velora.ui.form.on("X", { refresh: () => { throw new Error("boom"); }, validate: () => { throw new Error("nope"); } });
    expect(() => trigger("X", "refresh", frm({}))).not.toThrow();
    expect(() => trigger("X", "validate", frm({}), true)).toThrow("nope");
    err.mockRestore();
  });

  it("loads the real Customer scripts served by the backend, once", async () => {
    const calls = mockServer({ "GET /api/client_script/Customer": ({ url }) =>
      new Response(url.searchParams.get("kind") === "list" ? listJs : customerJs) });
    await loadScripts("Customer", "form");
    await loadScripts("Customer", "form");
    await loadScripts("Customer", "list");
    expect(calls.filter((c) => c.key.includes("client_script"))).toHaveLength(2);
    expect(velora.listview_settings["Customer"].get_indicator!({ status: "Blocked" })).toEqual(["Blocked", "red"]);
    const set_intro = vi.fn(); const add_button = vi.fn();
    trigger("Customer", "refresh", { doc: { status: "Blocked", name: "C1" }, is_new: () => false, set_intro, add_button } as unknown as FormApi);
    expect(set_intro).toHaveBeenCalledWith(expect.stringContaining("blocked"));
    expect(add_button).toHaveBeenCalledWith("View Orders", expect.any(Function));
  });

  it("survives a broken script and a missing script", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    mockServer({ "GET /api/client_script/A": "this is not js(", "GET /api/client_script/B": "" });
    await expect(loadScripts("A", "form")).resolves.toBeUndefined();
    await expect(loadScripts("B", "form")).resolves.toBeUndefined();
    err.mockRestore();
  });
});

describe("Journal Entry Voucher balancing line", () => {
  it("adds the opposite line for the difference and nothing when it already balances", async () => {
    const js = (await import("../../../apps/velora_erp/velora_erp/finance/doctype/journal_entry_voucher/journal_entry_voucher.js?raw")).default as string;
    resetScripts();
    new Function("velora", js)(velora);
    const added: Record<string, unknown>[] = []; let action: (() => void) | undefined;
    const form = (lines: object[]) => ({ doc: { docstatus: 0, posting_date: "2026-03-01", lines }, add_button: (_l: string, fn: () => void) => { action = fn; }, add_table_row: (_t: string, row: Record<string, unknown>) => added.push(row) }) as unknown as FormApi;
    trigger("Journal Entry Voucher", "refresh", form([{ trans_effect: "Debit", amount: 500, trans_date: "2026-03-01" }]));
    action!();
    expect(added).toEqual([expect.objectContaining({ trans_effect: "Credit", amount: 500, account_type: "Account GL", trans_date: "2026-03-01" })]);
    action = undefined;
    trigger("Journal Entry Voucher", "refresh", form([{ trans_effect: "Credit", amount: 120.5 }, { trans_effect: "Debit", amount: 20.5 }]));
    action!();
    expect(added[1]).toMatchObject({ trans_effect: "Debit", amount: 100 });
    action = undefined;
    trigger("Journal Entry Voucher", "refresh", form([{ trans_effect: "Debit", amount: 10 }, { trans_effect: "Credit", amount: 10 }]));
    expect(action).toBeUndefined();                                                  // balanced: no button at all
  });
});
