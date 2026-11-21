import { describe, expect, it } from "vitest";
import { defaultColumnWidth, defaultGridFields, resolveColumns } from "../gridConfig";
import type { Meta } from "../types";

const meta = (fields: any[]): Meta => ({ name: "Test Line", fields } as Meta);

describe("child grid defaults and persisted widths", () => {
  it("uses integer widths within the server's accepted range", () => {
    const fields = [
      { fieldname: "item_code", fieldtype: "Link", label: "Item Code", options: "Item" },
      { fieldname: "item_name", fieldtype: "Data", label: "Item Name" },
      { fieldname: "quantity", fieldtype: "Float", label: "Quantity" },
      { fieldname: "rate", fieldtype: "Currency", label: "Rate" },
      { fieldname: "description", fieldtype: "Text", label: "Description" },
    ];
    for (const field of fields) {
      const width = defaultColumnWidth(field as any);
      expect(Number.isInteger(width)).toBe(true);
      expect(width).toBeGreaterThanOrEqual(1);
      expect(width).toBeLessThanOrEqual(100);
    }
  });

  it("rounds legacy fractional widths before they can be saved", () => {
    const m = meta([{ fieldname: "item_code", fieldtype: "Link", label: "Item Code", options: "Item" }]);
    expect(resolveColumns(m, [{ field: "item_code", width: 2.8 }], null).map((c) => c.width)).toEqual([3]);
    expect(resolveColumns(m, [{ field: "item_code", width: 0.4 }], null).map((c) => c.width)).toEqual([1]);
    expect(resolveColumns(m, [{ field: "item_code", width: 100.6 }], null).map((c) => c.width)).toEqual([100]);
  });

  it("shows every field of a small table, and only list-view fields first for a big one", () => {
    const small = meta([
      { fieldname: "item_code", fieldtype: "Link", label: "Item", in_list_view: true },
      { fieldname: "item_name", fieldtype: "Data", label: "Item Name", in_list_view: true },
      { fieldname: "description", fieldtype: "Text", label: "Description" },
    ]);
    expect(defaultGridFields(small).map((f) => f.fieldname)).toEqual(["item_code", "item_name", "description"]);
    const big = meta([
      { fieldname: "item_code", fieldtype: "Link", label: "Item", in_list_view: true },
      { fieldname: "item_name", fieldtype: "Data", label: "Item Name", in_list_view: true },
      { fieldname: "quantity", fieldtype: "Float", label: "Quantity", in_list_view: true },
      ...Array.from({ length: 10 }, (_, i) => ({ fieldname: `extra_${i}`, fieldtype: "Data", label: `Extra ${i}` })),
    ]);
    const names = defaultGridFields(big).map((f) => f.fieldname);
    expect(names.length).toBeLessThanOrEqual(6);
    expect(names).toEqual(expect.arrayContaining(["item_code", "item_name", "quantity"]));
  });

  it("uses a compact fallback where metadata has no list-view selection", () => {
    const m = meta(Array.from({ length: 25 }, (_, i) => ({ fieldname: i === 0 ? "item_code" : `field_${i}`, fieldtype: "Data", label: `Field ${i}` })));
    const names = defaultGridFields(m).map((f) => f.fieldname);
    expect(names).toHaveLength(6);                                                    // never the whole 25
    expect(names).toContain("item_code");
  });
});

describe("technical columns", () => {
  it("never lead a default grid but stay selectable", () => {
    const f = (fieldname: string, extra: object = {}) => ({ fieldname, label: fieldname, fieldtype: "Data", ...extra });
    const meta = { fields: [f("source_line"), f("item_code"), f("item_name"), f("quantity"), f("rate"), f("amount"), f("uom"), f("warehouse")] } as any;
    const names = defaultGridFields(meta).map((x: any) => x.fieldname);
    expect(names).not.toContain("source_line");
    expect(names).toContain("item_code");
  });
});
