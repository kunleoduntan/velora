import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { clearCaches, setAuthMode, setProfile, setSession } from "../api";
import FormView from "../components/FormView";
import GridForm from "../components/GridForm";
import type { Field, GridLayout, Meta } from "../types";
import { META, mockServer } from "./helpers";

const f = (n: string, t: Field["fieldtype"] = "Data", extra: Partial<Field> = {}): Field => ({ fieldname: n, fieldtype: t, label: n.toUpperCase(), ...extra });
const FIELDS = Object.fromEntries([f("a"), f("b"), f("c"), f("secret", "Data", { hidden: true }), f("memo", "Text")].map((x) => [x.fieldname, x]));
const LAYOUT: GridLayout = { tabs: [
  { label: "Main", sections: [{ label: "Top", rows: [[{ field: "a", span: 8 }, { field: "b", span: 4 }], [{ field: "c", span: 12 }]] }, { label: "More", auto: true, rows: [[{ field: "memo", span: 12 }]] }] },
  { label: "Hidden tab", sections: [{ label: "x", rows: [[{ field: "secret", span: 12 }]] }] },
] };
const props = (over = {}) => ({ layout: LAYOUT, fields: FIELDS, hidden: {}, tabIdx: 0, onTab: () => {}, collapsed: {}, onToggle: () => {}, render: (fld: Field) => <input aria-label={fld.label} />, ...over });

describe("GridForm", () => {
  it("lays cells out in rows with their widths, in the order of the layout", () => {
    const { container } = render(<GridForm {...props()} />);
    const rows = Array.from(container.querySelectorAll(".grow")).map((r) => Array.from(r.querySelectorAll(".gcell")).map((c) => `${c.getAttribute("data-field")}:${c.getAttribute("data-span")}`));
    expect(rows).toEqual([["a:8", "b:4"], ["c:12"], ["memo:12"]]);
    expect((container.querySelector('[data-field="a"]') as HTMLElement).style.getPropertyValue("--span")).toBe("8");
    expect(container.querySelector('[data-field="b"]')!.getAttribute("data-narrow")).toBe("true");                 // narrow cells pair up on a phone
    expect(container.querySelector('[data-field="a"]')!.getAttribute("data-narrow")).toBeNull();
    expect(container.querySelector('section[data-auto="true"]')).toBeTruthy();                                       // the auto-added "More" section is marked
  });

  it("never shows hidden fields, and drops rows, sections and tabs that end up empty", () => {
    render(<GridForm {...props()} />);
    expect(screen.queryByLabelText("SECRET")).toBeNull();
    expect(screen.queryByRole("tab")).toBeNull();                                                                    // the second tab held only a hidden field: one tab left = no tab bar
    render(<GridForm {...props({ hidden: { a: true, b: true } })} />);
    expect(screen.getAllByLabelText("A")).toHaveLength(1);                                                           // (still the first render's) - the second render has none:
  });

  it("scripts can hide a field (toggle_hidden) and the layout simply closes up", () => {
    const { container } = render(<GridForm {...props({ hidden: { a: true } })} />);
    expect(Array.from(container.querySelectorAll(".grow")).map((r) => r.querySelectorAll(".gcell").length)).toEqual([1, 1, 1]);
    const { container: c2 } = render(<GridForm {...props({ hidden: { c: true } })} />);
    expect(c2.querySelectorAll(".grow")).toHaveLength(2);
  });

  it("shows a tab bar only when there is more than one visible tab, and switches panels", () => {
    const multi: GridLayout = { tabs: [LAYOUT.tabs[0], { label: "Notes", sections: [{ label: "", rows: [[{ field: "memo", span: 12 }]] }] }] };
    let idx = 0;
    const { rerender } = render(<GridForm {...props({ layout: multi, onTab: (i: number) => { idx = i; } })} />);
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Main", "Notes"]);
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    expect(idx).toBe(1);
    rerender(<GridForm {...props({ layout: multi, tabIdx: 1 })} />);
    expect(screen.getByRole("tab", { name: "Notes" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByRole("tabpanel", { hidden: true }).map((p) => p.hasAttribute("hidden"))).toEqual([true, false]);
  });

  it("sections collapse and expand", () => {
    let toggled = "";
    const { rerender } = render(<GridForm {...props({ onToggle: (k: string) => { toggled = k; } })} />);
    fireEvent.click(screen.getByRole("button", { name: /Top/ }));
    expect(toggled).toBe("0:0");
    rerender(<GridForm {...props({ collapsed: { "0:0": true } })} />);
    expect(screen.queryByLabelText("A")).toBeNull();
    expect(screen.getByRole("button", { name: /Top/ }).getAttribute("aria-expanded")).toBe("false");
  });

  it("ignores cells that name a field that does not exist (a stale layout can't crash the form)", () => {
    const { container } = render(<GridForm {...props({ layout: { tabs: [{ label: "T", sections: [{ label: "", rows: [[{ field: "gone", span: 6 }, { field: "a", span: 6 }]] }] }] } })} />);
    expect(container.querySelectorAll(".gcell")).toHaveLength(1);
  });
});

describe("FormView with a layout", () => {
  beforeEach(() => { clearCaches(); localStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "sam", roles: "Sales User" }); window.location.hash = ""; });
  const base = META.Customer as Meta;
  const withLayout = (extra: Partial<Meta> = {}): Meta => ({ ...base, ...extra, layout: { tabs: [{ label: "Details", sections: [{ label: "Who", rows: [[{ field: "customer_name", span: 8 }, { field: "status", span: 4 }]] },
    { label: "More", auto: true, rows: [[{ field: "credit_limit", span: 6 }]] }] }] }, layout_source: "company" });

  it("renders the company layout and keeps the fields editable and saved with the right values", async () => {
    const calls = mockServer({ "GET /api/meta/Customer": () => withLayout(), "POST /api/resource/Customer": ({ body }: any) => ({ ...body, name: "CUST-1", docstatus: 0, modified: "2026-01-01" }) });
    const { container } = render(<FormView doctype="Customer" name="new" />);
    await screen.findByText("New Customer");
    expect(Array.from(container.querySelectorAll(".gcell")).map((c) => c.getAttribute("data-field")).slice(0, 3)).toEqual(["customer_name", "status", "credit_limit"]);
    expect(container.querySelector(".columns")).toBeNull();                                                          // the classic column renderer is not used
    fireEvent.change(within(container.querySelector('[data-field="customer_name"]') as HTMLElement).getByRole("textbox"), { target: { value: "Gridded Ltd" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/resource/Customer")).toBe(true));
    expect(calls.find((c) => c.key === "POST /api/resource/Customer")!.body.customer_name).toBe("Gridded Ltd");
  });

  it("a doctype without a layout still uses the classic columns", async () => {
    mockServer({});
    const { container } = render(<FormView doctype="Customer" name="new" />);
    await screen.findByText("New Customer");
    expect(container.querySelector(".gcell")).toBeNull();
  });

  it("offers 'Customize form' only to people who may customise, never on child tables", async () => {
    mockServer({ "GET /api/meta/Customer": () => withLayout({ can_customize: true }) });
    const { unmount } = render(<FormView doctype="Customer" name="new" />);
    expect((await screen.findByRole("link", { name: /Customize form/ })).getAttribute("href")).toBe("#/settings/layout/Customer");
    unmount();
    clearCaches();                                                                                                    // (the client caches meta per DocType)
    mockServer({ "GET /api/meta/Customer": () => withLayout({ can_customize: false }) });
    render(<FormView doctype="Customer" name="new" />);
    await screen.findByText("New Customer");
    expect(screen.queryByRole("link", { name: /Customize form/ })).toBeNull();
  });
});
