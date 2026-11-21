import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { api, clearCaches, setAuthMode, setProfile, setSession } from "../api";
import TableField from "../components/TableField";
import * as G from "../gridConfig";
import type { Field, GridColumn, Meta } from "../types";
import { fail, mockServer } from "./helpers";

const mk = (n: string, t: Field["fieldtype"] = "Data", extra: Partial<Field> = {}): Field => ({ fieldname: n, fieldtype: t, label: n.toUpperCase(), ...extra });
const child = (fields: Field[], extra: Partial<Meta> = {}): Meta => ({ name: "Line", module: "M", autoname: null, title_field: null, is_submittable: false, istable: true, track_changes: false,
  sort_field: "idx", sort_order: "asc", permissions: {}, fields, ...extra });
const SMALL = child([mk("item", "Data", { required: true }), mk("qty", "Float", { default: 1 }), mk("rate", "Currency"), mk("note"), mk("secret", "Data", { hidden: true }), mk("sec", "Section Break")]);
const MANY = child(Array.from({ length: 12 }, (_, i) => mk(`f${i}`, "Data", i >= 9 ? { in_list_view: true } : {})));
const ROWS = () => [{ name: "r1", item: "Bolt", qty: 2, rate: 5, note: "a" }, { name: "r2", item: "Nut", qty: 1, rate: 1, note: "b" }, { name: "r3", item: "Screw", qty: 9, rate: 3, note: "c" }];
const FIELD: Field = { fieldname: "lines", fieldtype: "Table", label: "Lines", options: "Line" };

let latest: Record<string, unknown>[] = [];
function Harness({ meta = SMALL, rows = ROWS(), readOnly = false }: { meta?: Meta; rows?: Record<string, unknown>[]; readOnly?: boolean }) {
  const [r, setR] = useState(rows);
  latest = r;
  return <TableField field={FIELD} rows={r} onChange={setR} childMeta={meta} readOnly={readOnly} />;
}
const heads = () => screen.getAllByRole("columnheader").map((h) => h.textContent!.replace(/\s*\*$/, "")).filter((t) => t && !/Resize/.test(t));
const widths = (c: HTMLElement) => Array.from(c.querySelectorAll("col")).slice(1).map((x) => (x as HTMLElement).style.width);
const btn = (n: string | RegExp) => screen.getByRole("button", { name: n });

beforeEach(() => { clearCaches(); localStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "boss", roles: "System Manager" }); });

describe("default columns", () => {
  it("a big table starts with at most six columns, the important ones in the form's own order", () => {
    const meta = child([
      mk("custom_note"), mk("description", "Small Text"), mk("posting_date", "Date"), mk("warehouse", "Link", { options: "Warehouse" }),
      mk("item_code", "Link", { options: "Item" }), mk("item_name"), mk("qty", "Float"), mk("uom", "Link", { options: "UOM" }), mk("rate", "Currency"), mk("amount", "Currency"),
    ]);
    const names = G.resolveColumns(meta).map((c) => c.field.fieldname);
    expect(names).toHaveLength(6);
    expect(names).toEqual(expect.arrayContaining(["item_code", "item_name", "qty", "rate", "amount"]));
    expect(names).not.toContain("custom_note");
    expect(names.indexOf("item_code")).toBeLessThan(names.indexOf("qty"));
  });
  it("a small child table shows every visible field, as it always did (hidden fields and breaks stay out)", () => {
    render(<Harness />);
    expect(heads()).toEqual(["ITEM", "QTY", "RATE", "NOTE"]);
  });
  it("a small table keeps showing every field even when ONE is marked 'in list view' (that flag must not hide quantity and rate)", () => {
    render(<Harness meta={child(SMALL.fields.map((f) => (f.fieldname === "item" ? { ...f, in_list_view: true } : f)))} />);
    expect(heads()).toEqual(["ITEM", "QTY", "RATE", "NOTE"]);
  });
  it("never shows more than six columns by default, however many fields the table has", () => {
    const { unmount } = render(<Harness meta={MANY} rows={[]} />);
    expect(heads()).toHaveLength(6);
    unmount();
    render(<Harness meta={child(Array.from({ length: 24 }, (_, i) => mk(`col${i}`)))} rows={[]} />);
    expect(heads()).toHaveLength(6);
  });
  it("uses the company/app grid_columns, in that order, with independent pixel widths", () => {
    const meta = child(SMALL.fields, { grid_columns: [{ field: "rate", width: 2 }, { field: "item", width: 6 }, { field: "ghost", width: 1 }, { field: "qty", width: 2 }] });
    const { container } = render(<Harness meta={meta} />);
    expect(heads()).toEqual(["RATE", "ITEM", "QTY"]);                                                       // a column that no longer exists is ignored
    expect(widths(container as HTMLElement).slice(1, 4)).toEqual(["140px", "420px", "140px"]);
  });
  it("your own setting beats the company's; 'Reset' brings the default back", async () => {
    localStorage.setItem("velora.grid.Line", JSON.stringify([{ field: "note", width: 5 }, { field: "item", width: 5 }]));
    const meta = child(SMALL.fields, { grid_columns: [{ field: "rate", width: 10 }] });
    render(<Harness meta={meta} />);
    expect(heads()).toEqual(["NOTE", "ITEM"]);
    fireEvent.click(btn("Configure columns"));
    fireEvent.click(btn("Reset to default"));
    expect(heads()).toEqual(["RATE"]);
    expect(localStorage.getItem("velora.grid.Line")).toBeNull();
  });
});

describe("configuring columns", () => {
  it("lists ALL the fields (not just the ones shown) and lets you show, order and size them", () => {
    const { container } = render(<Harness meta={child(MANY.fields, { grid_columns: [{ field: "f9", width: 2 }] })} rows={[]} />);
    fireEvent.click(btn("Configure columns"));
    const dlg = within(screen.getByRole("dialog"));
    expect(dlg.getAllByRole("checkbox")).toHaveLength(12);                                                  // every field, however many there are
    expect(dlg.getByText("1 columns selected · no fixed column limit")).toBeTruthy();
    fireEvent.click(dlg.getByLabelText("Show F0"));
    expect((btn("Save for me") as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(dlg.getByLabelText("Move up: F0"));
    fireEvent.click(btn("Save for me"));
    expect(heads()).toContain("F0");
    expect(JSON.parse(localStorage.getItem("velora.grid.Line")!).map((c: GridColumn) => c.field)).toContain("f0");
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });
  it("allows arbitrarily many columns and still requires at least one visible column", () => {
    render(<Harness meta={SMALL} />);
    fireEvent.click(btn("Configure columns"));
    const dlg = within(screen.getByRole("dialog"));
    for (let i = 0; i < 60; i++) fireEvent.click(dlg.getByLabelText("Wider: ITEM"));
    expect((btn("Save for me") as HTMLButtonElement).disabled).toBe(false);
    for (const n of ["ITEM", "QTY", "RATE", "NOTE"]) fireEvent.click(dlg.getByLabelText(`Show ${n}`));
    expect(dlg.getByRole("alert").textContent).toBe("Show at least one column");
  });
  it("repositions visible columns correctly when a hidden column is interleaved", () => {
    render(<Harness />);
    fireEvent.click(btn("Configure columns"));
    const dlg = within(screen.getByRole("dialog"));
    fireEvent.click(dlg.getByLabelText("Show QTY"));
    fireEvent.click(dlg.getByLabelText("Move down: ITEM"));
    fireEvent.click(btn("Save for me"));
    expect(heads()).toEqual(["RATE", "ITEM", "NOTE"]);
  });
  it("drag reorders visible columns even when a hidden column sits between them", () => {
    render(<Harness />);
    fireEvent.click(btn("Configure columns"));
    const dlg = within(screen.getByRole("dialog"));
    fireEvent.click(dlg.getByLabelText("Show QTY"));
    const rows = screen.getByRole("dialog").querySelectorAll(".cols-list li");
    fireEvent.dragStart(rows[0]); fireEvent.dragOver(rows[2]); fireEvent.drop(rows[2]);
    fireEvent.click(btn("Save for me"));
    expect(heads()).toEqual(["RATE", "ITEM", "NOTE"]);
  });
  it("changes the order of the shown columns", () => {
    render(<Harness meta={SMALL} />);
    fireEvent.click(btn("Configure columns"));
    fireEvent.click(within(screen.getByRole("dialog")).getByLabelText("Move down: ITEM"));
    fireEvent.click(btn("Save for me"));
    expect(heads()).toEqual(["QTY", "ITEM", "RATE", "NOTE"]);
  });
  it("reorders visible columns by drag and drop", () => {
    render(<Harness meta={SMALL} />);
    fireEvent.click(btn("Configure columns"));
    const rows = screen.getByRole("dialog").querySelectorAll(".cols-list li");
    fireEvent.dragStart(rows[0]); fireEvent.dragOver(rows[1]); fireEvent.drop(rows[1]);
    fireEvent.click(btn("Save for me"));
    expect(heads()).toEqual(["QTY", "ITEM", "RATE", "NOTE"]);
  });

  it("'Save for everyone' appears only for people who may customise, and saves company-wide (then forgets your own copy)", async () => {
    const calls = mockServer({ "PUT /api/grid/Line": ({ body }: any) => ({ columns: body.columns }) });
    localStorage.setItem("velora.grid.Line", JSON.stringify([{ field: "note", width: 10 }]));
    const { unmount } = render(<Harness meta={SMALL} />);
    fireEvent.click(btn("Configure columns"));
    expect(screen.queryByRole("button", { name: "Save for everyone" })).toBeNull();
    unmount();
    render(<Harness meta={{ ...SMALL, can_customize: true }} />);
    fireEvent.click(btn("Configure columns"));
    fireEvent.click(within(screen.getByRole("dialog")).getByLabelText("Show ITEM"));                        // swap the one shown column (NOTE) for ITEM
    fireEvent.click(within(screen.getByRole("dialog")).getByLabelText("Show NOTE"));
    fireEvent.click(btn("Save for everyone"));
    await waitFor(() => expect(calls.some((c) => c.key === "PUT /api/grid/Line")).toBe(true));
    expect(calls.find((c) => c.key === "PUT /api/grid/Line")!.body.target).toBe("company");
    await waitFor(() => expect(localStorage.getItem("velora.grid.Line")).toBeNull());                      // the company setting now applies to you too
    expect(heads()).not.toContain("NOTE");
  });
  it("after a company-wide save the cached meta is discarded, so every form fetches the new columns", async () => {
    let fetches = 0;
    mockServer({ "GET /api/meta/Line": () => { fetches += 1; return SMALL; }, "PUT /api/grid/Line": ({ body }: any) => ({ columns: body.columns }) });
    render(<Harness meta={{ ...SMALL, can_customize: true }} />);
    await api.meta("Line"); await api.meta("Line");
    expect(fetches).toBe(1);
    fireEvent.click(btn("Configure columns"));
    fireEvent.click(btn("Save for everyone"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await api.meta("Line");
    expect(fetches).toBe(2);
  });
  it("shows the server's reason if the company-wide save is refused, and keeps the dialog open", async () => {
    mockServer({ "PUT /api/grid/Line": () => fail(403, "PermissionDenied", "Only a System Manager can customise forms") });
    render(<Harness meta={{ ...SMALL, can_customize: true }} />);
    fireEvent.click(btn("Configure columns"));
    fireEvent.click(btn("Save for everyone"));
    await waitFor(() => expect(screen.getAllByRole("alert").some((a) => a.textContent!.includes("Only a System Manager"))).toBe(true));
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
  it("resizes a column from the keyboard without a grid-wide width ceiling, and remembers it", () => {
    render(<Harness meta={child(SMALL.fields, { grid_columns: [{ field: "item", width: 4 }, { field: "qty", width: 3 }] })} />);
    const h = screen.getByRole("separator", { name: "Resize column ITEM" });
    expect(h.getAttribute("aria-valuenow")).toBe("4");
    fireEvent.keyDown(h, { key: "ArrowRight" });
    expect(screen.getByRole("separator", { name: "Resize column ITEM" }).getAttribute("aria-valuenow")).toBe("5");
    for (let i = 0; i < 6; i++) fireEvent.keyDown(screen.getByRole("separator", { name: "Resize column ITEM" }), { key: "ArrowRight" });
    expect(screen.getByRole("separator", { name: "Resize column ITEM" }).getAttribute("aria-valuenow")).toBe("11");
    for (let i = 0; i < 9; i++) fireEvent.keyDown(screen.getByRole("separator", { name: "Resize column QTY" }), { key: "ArrowLeft" });
    expect(screen.getByRole("separator", { name: "Resize column QTY" }).getAttribute("aria-valuenow")).toBe("1");
    expect(JSON.parse(localStorage.getItem("velora.grid.Line")!)).toEqual([{ field: "item", width: 11 }, { field: "qty", width: 1 }]);
  });
});

describe("editing a whole row (any number of fields)", () => {
  it("opens every field - including ones the grid has no room for - and updates the row", () => {
    render(<Harness meta={child(SMALL.fields, { grid_columns: [{ field: "item", width: 10 }] })} />);
    expect(heads()).toEqual(["ITEM"]);
    fireEvent.click(btn("Edit row 1"));
    const dlg = within(screen.getByRole("dialog"));
    expect((dlg.getByLabelText(/^NOTE/) as HTMLInputElement).value).toBe("a");                            // not in the grid, but editable here
    expect(dlg.queryByLabelText(/SECRET/)).toBeNull();                                                      // hidden fields stay hidden
    fireEvent.change(dlg.getByLabelText(/^NOTE/), { target: { value: "changed" } });
    fireEvent.click(btn("Update"));
    expect(latest[0].note).toBe("changed");
    expect(latest[1].note).toBe("b");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("discards the edit when closed without updating", () => {
    render(<Harness />);
    fireEvent.click(btn("Edit row 2"));
    fireEvent.change(within(screen.getByRole("dialog")).getByLabelText(/^NOTE/), { target: { value: "zzz" } });
    fireEvent.click(btn("Close"));
    expect(latest[1].note).toBe("b");
  });
  it("is view-only on a read-only grid", () => {
    render(<Harness readOnly />);
    expect(screen.queryByRole("button", { name: "Add row" })).toBeNull();
    expect(screen.queryByLabelText("Select row 1")).toBeNull();
    expect(screen.queryByLabelText("Drag row 1")).toBeNull();
    fireEvent.click(btn("View row 1"));
    expect(screen.getByRole("dialog", { name: "Row 1" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Update" })).toBeNull();
    expect((within(screen.getByRole("dialog")).getByLabelText(/^NOTE/) as HTMLInputElement).readOnly || (within(screen.getByRole("dialog")).getByLabelText(/^NOTE/) as HTMLInputElement).disabled).toBe(true);
    expect(btn("Configure columns")).toBeTruthy();                                                           // you can still choose what YOU see
  });
});

describe("rows: add, delete, duplicate, reorder", () => {
  it("a new row gets the defaults of EVERY field, shown or not", () => {
    render(<Harness meta={child(SMALL.fields.map((f) => (f.fieldname === "secret" ? { ...f, hidden: false, default: "x", fieldname: "extra" } : f)), { grid_columns: [{ field: "item", width: 10 }] })} />);
    fireEvent.click(btn("Add row"));
    expect(latest[3]).toMatchObject({ qty: 1, extra: "x" });
  });
  it("deletes and duplicates the selected rows (a copy has no name of its own)", () => {
    render(<Harness />);
    fireEvent.click(screen.getByLabelText("Select row 1")); fireEvent.click(screen.getByLabelText("Select row 3"));
    fireEvent.click(btn("Duplicate selected rows"));
    expect(latest.map((r) => r.item)).toEqual(["Bolt", "Nut", "Screw", "Bolt", "Screw"]);
    expect(latest[3].name).toBeUndefined();
    expect(latest[0].name).toBe("r1");
    fireEvent.click(screen.getByLabelText("Select row 2")); fireEvent.click(btn("Delete selected rows"));
    expect(latest.map((r) => r.item)).toEqual(["Bolt", "Screw", "Bolt", "Screw"]);
  });
  it("moves the selected row up and down; disabled at the ends and with several selected", () => {
    render(<Harness />);
    expect((btn("Move row up") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Select row 2"));
    fireEvent.click(btn("Move row up"));
    expect(latest.map((r) => r.item)).toEqual(["Nut", "Bolt", "Screw"]);
    expect((btn("Move row up") as HTMLButtonElement).disabled).toBe(true);                                  // the selection follows the row: now first
    fireEvent.click(btn("Move row down")); fireEvent.click(btn("Move row down"));
    expect(latest.map((r) => r.item)).toEqual(["Bolt", "Screw", "Nut"]);
    expect((btn("Move row down") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Select row 1"));
    expect((btn("Move row down") as HTMLButtonElement).disabled).toBe(true);
  });
  it("reorders by dragging a row's grip onto another row", () => {
    render(<Harness />);
    const rows = screen.getAllByRole("row");
    fireEvent.dragStart(screen.getByLabelText("Drag row 1"));
    fireEvent.dragOver(rows[3]); fireEvent.drop(rows[3]);
    expect(latest.map((r) => r.item)).toEqual(["Nut", "Screw", "Bolt"]);
    fireEvent.drop(rows[1]);                                                                                  // nothing is being dragged any more
    expect(latest.map((r) => r.item)).toEqual(["Nut", "Screw", "Bolt"]);
  });
});

describe("gridConfig helpers", () => {
  it("resolves columns in the documented order of precedence", () => {
    const m = child(SMALL.fields, { grid_columns: [{ field: "rate", width: 4 }] });
    expect(G.resolveColumns(m, [{ field: "note", width: 9 }], [{ field: "qty", width: 2 }]).map((c) => c.field.fieldname)).toEqual(["note"]);
    expect(G.resolveColumns(m, null, [{ field: "qty", width: 2 }]).map((c) => c.field.fieldname)).toEqual(["qty"]);
    expect(G.resolveColumns(m, null, null).map((c) => c.field.fieldname)).toEqual(["rate"]);
    expect(G.resolveColumns(m, [{ field: "gone", width: 3 }]).map((c) => c.field.fieldname)).toEqual(["rate"]);       // a stale personal setting falls through
    expect(G.resolveColumns(SMALL).map((c) => c.width)).toEqual([3, 2, 2, 3]);
    expect(G.resolveColumns(m, [{ field: "note", width: 99 }])[0].width).toBe(99);                                      // width is independent of the total grid width
    expect(G.total(G.resolveColumns(SMALL))).toBeCloseTo(10);
  });
  it("reorders without ever losing or duplicating an item", () => {
    expect(G.reorder([1, 2, 3, 4], 0, 2)).toEqual([2, 3, 1, 4]);
    expect(G.reorder([1, 2, 3, 4], 3, 0)).toEqual([4, 1, 2, 3]);
    const same = [1, 2, 3];
    expect(G.reorder(same, 1, 1)).toBe(same);
    expect(G.reorder(same, -1, 2)).toBe(same);
    expect(G.reorder(same, 0, 9)).toBe(same);
  });
  it("survives a corrupt or unavailable localStorage", () => {
    localStorage.setItem("velora.grid.Line", "{not json");
    expect(G.loadPersonal("Line")).toBeNull();
    localStorage.setItem("velora.grid.Line", JSON.stringify({ not: "a list" }));
    expect(G.loadPersonal("Line")).toBeNull();
  });
});
