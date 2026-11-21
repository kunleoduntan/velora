import { describe, expect, it } from "vitest";
import { defaultListColumns, PRESET_LIST_COLUMNS } from "../listSettings";

const f = (fieldname: string, fieldtype = "Data", extra: object = {}) => ({ fieldname, fieldtype, ...extra });

describe("default list columns", () => {
  it("keeps the DocType's own list columns and tops them up to the preset with important fields", () => {
    const cols = defaultListColumns([f("employee", "Link", { in_list_view: true }), f("notes", "Text"), f("status", "Select"), f("posting_date", "Date"), f("grand_total", "Currency"),
      f("department", "Link"), f("remarks_long", "Long Text"), f("approval_status", "Select", { required: true }), f("misc")]);
    expect(cols[0]).toBe("employee");
    expect(cols).toContain("status"); expect(cols).toContain("grand_total"); expect(cols).toContain("posting_date");
    expect(cols).not.toContain("notes"); expect(cols).not.toContain("remarks_long");
    expect(cols.length).toBeLessThanOrEqual(PRESET_LIST_COLUMNS);
  });
  it("never alters a DocType that already declares a curated list", () => {
    const many = Array.from({ length: 4 }, (_, i) => f(`c${i}`, "Data", { in_list_view: true })).concat([f("status", "Select")]);
    expect(defaultListColumns(many)).toEqual(["c0", "c1", "c2", "c3"]);
  });
});
