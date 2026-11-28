import { beforeEach, describe, expect, it } from "vitest";
import { dataFields, describe as describeFilter, fromApi, isComplete, opsFor, toApi, type Filter } from "../filters";
import { DEFAULTS, loadSettings, saveSettings } from "../listSettings";
import { formatCell, toTsv } from "../format";
import type { Meta } from "../types";
import { META } from "./helpers";

const customer = META.Customer as Meta;
const so = META["Sales Order"] as Meta;

describe("filters", () => {
  it("translates UI filters into API filters", () => {
    const f: Filter[] = [
      { field: "customer_name", op: "like", value: "acme" },
      { field: "customer_name", op: "not like", value: "%x%" },
      { field: "status", op: "in", value: "Active, Blocked" },
      { field: "credit_limit", op: "between", value: ["100", "900"] },
      { field: "email", op: "is not set", value: "" },
      { field: "email", op: "is set", value: "" },
      { field: "credit_limit", op: ">=", value: "5" },
    ];
    expect(toApi(f)).toEqual([
      ["customer_name", "like", "%acme%"],              // contains-semantics unless the user typed their own %
      ["customer_name", "not like", "%x%"],
      ["status", "in", ["Active", "Blocked"]],
      ["credit_limit", "between", ["100", "900"]],
      ["email", "is", "not set"],
      ["email", "is", "set"],
      ["credit_limit", ">=", "5"],
    ]);
  });

  it("round-trips: a saved API filter reopens as the same editable filter and serialises back identically", () => {
    const api: [string, string, unknown][] = [["customer_name", "like", "%acme%"], ["customer_name", "not like", "%x%"], ["status", "in", ["Active", "Blocked"]],
      ["credit_limit", "between", ["100", "900"]], ["email", "is", "not set"], ["email", "is", "set"], ["credit_limit", ">=", "5"], ["status", "=", "Active"]];
    expect(api.map((f) => toApi([fromApi(f)])[0])).toEqual(api);
    expect(fromApi(["email", "is", "not set"])).toEqual({ field: "email", op: "is not set", value: "" });
    expect(fromApi(["customer_name", "like", "%acme%"]).value).toBe("acme");                 // the % wrapping is re-applied on the way out
  });

  it("ignores incomplete filters instead of sending junk", () => {
    expect(toApi([{ field: "status", op: "=", value: "" }, { field: "x", op: "between", value: ["1", ""] }, { field: "x", op: "in", value: [] }])).toEqual([]);
    expect(isComplete({ field: "a", op: "is set", value: "" })).toBe(true);
  });

  it("offers sensible operators per field type", () => {
    expect(opsFor("Data")).toContain("like");
    expect(opsFor("Currency")).toEqual(expect.arrayContaining([">", "<", "between"]));
    expect(opsFor("Check")).toEqual(["="]);
    expect(opsFor("Datetime")).not.toContain("=");        // a day is expressed as between d and d
    expect(opsFor("Int", "docstatus")).toEqual(["=", "!="]);
  });

  it("exposes data fields incl. system fields; Status only for submittable DocTypes", () => {
    const names = (m: Meta) => dataFields(m).map((f) => f.fieldname);
    expect(names(customer)[0]).toBe("name");
    expect(names(customer)).toEqual(expect.arrayContaining(["customer_name", "credit_limit", "owner", "creation", "modified"]));
    expect(names(customer)).not.toContain("contacts");     // tables are not filterable columns
    expect(names(customer)).not.toContain("docstatus");
    expect(names(so)).toContain("docstatus");
  });

  it("describes filters in plain words for chips", () => {
    expect(describeFilter({ field: "credit_limit", op: ">=", value: "100" }, customer)).toBe("Credit Limit at least 100");
    expect(describeFilter({ field: "email", op: "is not set", value: "" }, customer)).toBe("Email Address is not set");
    expect(describeFilter({ field: "docstatus", op: "=", value: "1" }, so)).toBe("Status equals Submitted");
    expect(describeFilter({ field: "credit_limit", op: "between", value: ["1", "9"] }, customer)).toBe("Credit Limit between 1 and 9");
  });
});

describe("list settings + formatting", () => {
  beforeEach(() => localStorage.clear());

  it("persists per user and DocType, and survives corrupt storage", () => {
    saveSettings("sam", "Customer", { ...DEFAULTS, pageSize: 100, columns: ["email"] });
    expect(loadSettings("sam", "Customer")).toMatchObject({ pageSize: 100, columns: ["email"] });
    expect(loadSettings("other", "Customer")).toEqual(DEFAULTS);
    expect(loadSettings("sam", "Sales Order")).toEqual(DEFAULTS);
    localStorage.setItem("velora.list.sam.Customer", "{not json");
    expect(loadSettings("sam", "Customer")).toEqual(DEFAULTS);
  });

  it("builds Excel-pasteable TSV, quoting cells that contain tabs, quotes or newlines", () => {
    expect(toTsv(["A", "B"], [["1", "x y"], ["a\tb", 'say "hi"'], ["l1\nl2", ""]])).toBe('A\tB\n1\tx y\n"a\tb"\t"say ""hi"""\n"l1\nl2"\t');
  });

  it("formats cells by type", () => {
    expect(formatCell(1500.5, "Currency")).toBe("1,500.50");
    expect(formatCell(1234567, "Int")).toBe("1,234,567");
    expect(formatCell("2026-11-07T10:30:00.123", "Datetime")).toBe("2026-11-07 10:30");
    expect(formatCell("2026-11-07", "Date")).toBe("2026-11-07");
    expect(formatCell(1, "Check")).toBe("Yes");
    expect(formatCell(null, "Currency")).toBe("");
  });
});
