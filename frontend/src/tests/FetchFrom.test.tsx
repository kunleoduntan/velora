import { describe, expect, it, vi, beforeEach } from "vitest";
import { dependents, fetchedValues, clearFetchCache } from "../fetchFrom";
import { api } from "../api";

const meta: any = { fields: [
  { fieldname: "item_code", fieldtype: "Link", label: "Item", options: "Inventory Item" },
  { fieldname: "item_name", fieldtype: "Data", label: "Name", fetch_from: "item_code.item_name" },
  { fieldname: "account", fieldtype: "Link", label: "Income Account", options: "Account", fetch_from: "item_code.income_account" },
  { fieldname: "note", fieldtype: "Data", label: "Note" },
] };

beforeEach(() => { clearFetchCache(); vi.restoreAllMocks(); });

describe("fetch from a linked document", () => {
  it("finds the fields that depend on a link", () => {
    expect(dependents(meta, "item_code").map((d) => d.field.fieldname)).toEqual(["item_name", "account"]);
    expect(dependents(meta, "note")).toEqual([]);
  });
  it("copies the linked values, and clears them when the link is cleared", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ name: "ITEM-1", item_name: "Laptop", income_account: "4000" } as any);
    expect(await fetchedValues(meta, "item_code", "ITEM-1")).toEqual({ item_name: "Laptop", account: "4000" });
    expect(await fetchedValues(meta, "item_code", "")).toEqual({ item_name: null, account: null });
  });
  it("copies nothing when the linked document cannot be read", async () => {
    vi.spyOn(api, "get").mockRejectedValue(new Error("403"));
    expect(await fetchedValues(meta, "item_code", "ITEM-2")).toEqual({});
  });
});
