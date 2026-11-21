import { describe, expect, it } from "vitest";
import { buildLayout } from "../layout";
import type { Field, Meta } from "../types";
import { META } from "./helpers";

const f = (fieldname: string, fieldtype = "Data", label = fieldname): Field => ({ fieldname, fieldtype: fieldtype as Field["fieldtype"], label });

describe("buildLayout", () => {
  it("lays out the real Customer metadata as tab > sections > columns", () => {
    const tabs = buildLayout((META.Customer as Meta).fields);
    expect(tabs.map((t) => t.label)).toEqual(["Details"]);
    const [main, contacts] = tabs[0].sections;
    expect(main.columns.map((c) => c.fields.map((x) => x.fieldname))).toEqual([
      ["customer_name", "email"],
      ["customer_group", "status", "credit_limit", "tax_exempt"],
    ]);
    expect(main.columns.map((c) => c.label)).toEqual([undefined, "Classification"]);   // Column Break label = group heading
    expect(contacts.label).toBe("Contacts");
    expect(contacts.columns[0].fields[0].fieldname).toBe("contacts");
  });

  it("needs no breaks at all: one default tab, section and column", () => {
    const tabs = buildLayout((META["Sales Order"] as Meta).fields);
    expect(tabs).toHaveLength(1);
    expect(tabs[0].sections[0].columns[0].fields.map((x) => x.fieldname)).toEqual(["customer", "order_date", "items", "total"]);
  });

  it("supports several tabs and drops empty ones from consecutive breaks", () => {
    const tabs = buildLayout([
      f("t1", "Tab Break", "One"), f("a"), f("b", "Column Break"), f("c", "Column Break"), f("d"),
      f("t2", "Tab Break", "Two"), f("s", "Section Break", "S"), f("e"),
      f("t3", "Tab Break", "Empty"),
    ]);
    expect(tabs.map((t) => t.label)).toEqual(["One", "Two"]);
    expect(tabs[0].sections[0].columns.map((c) => c.fields.map((x) => x.fieldname))).toEqual([["a"], ["d"]]);
  });
});
