import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, clearCaches, setAuthMode, setProfile, setSession } from "../api";
import LayoutDesigner from "../components/LayoutDesigner";
import type { Field, GridLayout } from "../types";
import { fail, mockServer } from "./helpers";

const f = (n: string, t: Field["fieldtype"] = "Data", extra: Partial<Field> = {}): Field => ({ fieldname: n, fieldtype: t, label: n.toUpperCase(), ...extra });
const ALL = [f("a", "Data", { required: true }), f("b"), f("c"), f("d"), f("e"), f("memo", "Text")];
const layout = (): GridLayout => ({ tabs: [{ label: "Main", sections: [
  { label: "Top", collapsible: false, rows: [[{ field: "a", span: 6 }, { field: "b", span: 6 }], [{ field: "c", span: 12 }]] },
  { label: "Second", collapsible: false, rows: [[{ field: "d", span: 12 }]] }] }] });
const info = (over: Record<string, unknown> = {}) => ({ source: "auto", layout: layout(), unplaced: [ALL[4], ALL[5]], fields: ALL, editable: true, can_write_app: false, ...over });

beforeEach(() => { clearCaches(); localStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "boss", roles: "System Manager" }); window.location.hash = ""; vi.stubGlobal("confirm", () => true); });

const rowsOf = (c: HTMLElement) => Array.from(c.querySelectorAll(".drow")).map((r) => Array.from(r.querySelectorAll(".dcell")).map((x) => `${x.getAttribute("data-field")}:${x.getAttribute("data-span")}`).join(" "));
const open = async (over = {}, extra: Record<string, any> = {}) => {
  const calls = mockServer({ "GET /api/layout/Customer": () => info(over), ...extra });
  const r = render(<LayoutDesigner doctype="Customer" />);
  await screen.findByText(/Customize form: Customer/);
  return { calls, ...r };
};
const btn = (name: string | RegExp) => screen.getByRole("button", { name });

describe("LayoutDesigner - what you see", () => {
  it("shows the layout as rows of cells with their widths, the source, and the fields that are not on the form", async () => {
    const { container } = await open();
    expect(rowsOf(container)).toEqual(["a:6 b:6", "c:12", "d:12"]);
    expect(screen.getByText("Not customised yet")).toBeTruthy();
    const palette = within(screen.getByLabelText("Fields not on the form"));
    expect(palette.getByText("E")).toBeTruthy();
    expect(palette.getByText("MEMO")).toBeTruthy();
    expect(screen.getByText("A").parentElement!.textContent).toContain("*");                              // required fields are marked
  });

  it("explains the source of a saved layout, and offers 'Reset' only for a company layout", async () => {
    await open({ source: "company" });
    expect(screen.getByText("Company layout")).toBeTruthy();
    expect(btn("Reset to default")).toBeTruthy();
  });

  it("is read-only for people who may not customise: no tools, no save, only a way to open the form", async () => {
    const { container } = await open({ editable: false });
    expect(screen.getByText("Only a System Manager can change this layout.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Save/ })).toBeNull();
    expect(screen.queryByLabelText(/Wider/)).toBeNull();
    expect(container.querySelectorAll('[draggable="true"]')).toHaveLength(0);
    expect(screen.getByRole("link", { name: "Open the form" }).getAttribute("href")).toBe("#/app/Customer/new");
  });

  it("shows why it could not load", async () => {
    mockServer({ "GET /api/layout/Customer": () => fail(403, "PermissionDenied", "No access") });
    render(<LayoutDesigner doctype="Customer" />);
    expect((await screen.findByRole("alert")).textContent).toContain("No access");
  });
});

describe("LayoutDesigner - resizing with the buttons, the keyboard and the presets", () => {
  it("widens a cell (the neighbour gives way), narrows it, and sets a preset", async () => {
    const { container } = await open();
    fireEvent.click(btn("Wider: A"));
    expect(rowsOf(container)[0]).toBe("a:7 b:5");
    fireEvent.click(btn("Narrower: A")); fireEvent.click(btn("Narrower: A"));
    expect(rowsOf(container)[0]).toBe("a:5 b:5");
    fireEvent.change(screen.getByLabelText("Width of A"), { target: { value: "9" } });
    expect(rowsOf(container)[0]).toBe("a:9 b:3");                                                          // ¾ of the row; B gives up only what is needed
    fireEvent.change(screen.getByLabelText("Width of C"), { target: { value: "4" } });
    expect(rowsOf(container)[1]).toBe("c:4");
  });
  it("the resize handle is a keyboard-operable slider", async () => {
    const { container } = await open();
    const h = screen.getByRole("slider", { name: "Resize A" });
    expect([h.getAttribute("aria-valuenow"), h.getAttribute("aria-valuemin"), h.getAttribute("aria-valuemax")]).toEqual(["6", "1", "12"]);
    fireEvent.keyDown(h, { key: "ArrowLeft" }); fireEvent.keyDown(h, { key: "ArrowLeft" });
    expect(rowsOf(container)[0]).toBe("a:4 b:6");
    fireEvent.keyDown(h, { key: "ArrowRight" });
    expect(rowsOf(container)[0]).toBe("a:5 b:6");
  });
  it("narrower/wider are disabled at the limits", async () => {
    await open();
    expect((btn("Wider: C") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(btn("Narrower: C"));
    expect((btn("Wider: C") as HTMLButtonElement).disabled).toBe(false);
  });
  it("'equal widths' shares a row out evenly", async () => {
    const { container } = await open();
    fireEvent.click(btn("Narrower: A")); fireEvent.click(btn("Narrower: A")); fireEvent.click(btn("Wider: B"));
    fireEvent.click(btn("Equal widths in section 1, row 1"));
    expect(rowsOf(container)[0]).toBe("a:6 b:6");
  });
});

describe("LayoutDesigner - moving things with the buttons", () => {
  it("moves a cell left and right inside its row, and to the row above or below (or a new row)", async () => {
    const { container } = await open();
    fireEvent.click(btn("Move right: A"));
    expect(rowsOf(container)[0]).toBe("b:6 a:6");
    fireEvent.click(btn("Move left: A"));
    expect(rowsOf(container)[0]).toBe("a:6 b:6");
    fireEvent.click(btn("Move down: A"));
    expect(rowsOf(container)).toEqual(["b:6", "a:6 c:6", "d:12"]);                                          // joined the row below (sharing it)
    fireEvent.click(btn("Move up: C"));
    expect(rowsOf(container)[0]).toContain("c");
  });
  it("moves a whole row up or down", async () => {
    const { container } = await open();
    fireEvent.click(btn("Move section 1 row 2 up"));
    expect(rowsOf(container).slice(0, 2)).toEqual(["c:12", "a:6 b:6"]);
    expect((btn("Move section 1 row 1 up") as HTMLButtonElement).disabled).toBe(true);
  });
  it("removing a field puts it back in the palette - nothing is deleted", async () => {
    const { container } = await open();
    fireEvent.click(btn("Remove from the form: B"));
    expect(rowsOf(container)[0]).toBe("a:6");
    expect(within(screen.getByLabelText("Fields not on the form")).getByText("B")).toBeTruthy();
  });
});

describe("LayoutDesigner - the palette", () => {
  it("adds a field to the section of the selected cell, or to the first section", async () => {
    const { container } = await open();
    fireEvent.click(btn("Add E to the form"));
    expect(rowsOf(container)).toEqual(["a:6 b:6", "c:12", "e:6", "d:12"]);                                 // nothing selected: the first section, as a new row at its end
    fireEvent.click(screen.getByText("D"));                                                                   // select a cell in the second section
    fireEvent.click(btn("Add MEMO to the form"));
    expect(rowsOf(container).slice(-2)).toEqual(["d:12", "memo:12"]);                                        // a Text field defaults to the full width
  });
  it("filters by label or name, and says when everything is placed", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("Search fields"), { target: { value: "mem" } });
    const p = within(screen.getByLabelText("Fields not on the form"));
    expect(p.getByText("MEMO")).toBeTruthy();
    expect(p.queryByText("E")).toBeNull();
    fireEvent.change(screen.getByLabelText("Search fields"), { target: { value: "zzz" } });
    expect(p.getByText("No match.")).toBeTruthy();
  });
});

describe("LayoutDesigner - drag and drop", () => {
  const drag = (el: Element, zoneId: string) => { fireEvent.dragStart(el); fireEvent.dragOver(screen.getByTestId(`drop-${zoneId}`)); fireEvent.drop(screen.getByTestId(`drop-${zoneId}`)); };
  it("drops a palette field onto the end of a section to make a new row, or above a row", async () => {
    const { container } = await open();
    drag(screen.getByText("E").closest(".pitem")!, "0:0:end");
    expect(rowsOf(container)).toEqual(["a:6 b:6", "c:12", "e:6", "d:12"]);
    drag(screen.getByText("MEMO").closest(".pitem")!, "0:1:above-0");
    expect(rowsOf(container).slice(-2)).toEqual(["memo:12", "d:12"]);
  });
  it("drags a cell next to another (before it), sharing a full row evenly", async () => {
    const { container } = await open();
    drag(container.querySelector('[data-field="d"]')!, "0:0:0:before-0");
    expect(rowsOf(container)[0]).toBe("d:4 a:4 b:4");
  });
  it("drags a cell into the free space at the end of a row", async () => {
    const { container } = await open();
    fireEvent.click(btn("Narrower: C")); fireEvent.click(btn("Narrower: C"));                                  // row 2 now has 2 free columns
    drag(container.querySelector('[data-field="d"]')!, "0:0:1:fill");
    expect(rowsOf(container)).toEqual(["a:6 b:6", "c:10 d:2", ]);
  });
  it("shows the zones highlighted while dragging over them and clears them afterwards", async () => {
    await open();
    fireEvent.dragStart(screen.getByText("E").closest(".pitem")!);
    fireEvent.dragOver(screen.getByTestId("drop-0:0:end"));
    expect(screen.getByTestId("drop-0:0:end").className).toContain("over");
    fireEvent.dragLeave(screen.getByTestId("drop-0:0:end"));
    expect(screen.getByTestId("drop-0:0:end").className).not.toContain("over");
    fireEvent.dragEnd(screen.getByText("E").closest(".pitem")!);
  });
  it("ignores a drop when nothing is being dragged", async () => {
    const { container } = await open();
    fireEvent.drop(screen.getByTestId("drop-0:0:end"));
    expect(rowsOf(container)).toEqual(["a:6 b:6", "c:12", "d:12"]);
  });
  it("a full 12-cell row refuses another cell with a clear message and changes nothing", async () => {
    const many = Array.from({ length: 13 }, (_, i) => f(`f${i}`));
    const crowded: GridLayout = { tabs: [{ label: "T", sections: [{ label: "S", rows: [many.slice(0, 12).map((x) => ({ field: x.fieldname, span: 1 }))] }] }] };
    mockServer({ "GET /api/layout/Customer": () => ({ ...info(), layout: crowded, fields: many, unplaced: [many[12]] }) });
    const { container } = render(<LayoutDesigner doctype="Customer" />);
    await screen.findByText(/Customize form/);
    fireEvent.dragStart(screen.getByText("F12").closest(".pitem")!);
    expect(screen.queryByTestId("drop-0:0:0:fill")).toBeNull();                                                 // no free space: no fill zone offered
    fireEvent.dragOver(screen.getByTestId("drop-0:0:0:before-0")); fireEvent.drop(screen.getByTestId("drop-0:0:0:before-0"));
    expect((await screen.findByRole("alert")).textContent).toContain("That row is full");
    expect(container.querySelectorAll(".dcell")).toHaveLength(12);
  });
});

describe("LayoutDesigner - sections and tabs", () => {
  it("adds, renames, reorders and deletes sections; deleted sections' fields go back to the palette", async () => {
    const { container } = await open();
    fireEvent.click(btn("Add section"));
    expect(container.querySelectorAll(".dsection")).toHaveLength(3);
    fireEvent.change(screen.getByLabelText("Section 3 title"), { target: { value: "Notes" } });
    fireEvent.click(btn("Move section 3 up"));
    expect((screen.getByLabelText("Section 2 title") as HTMLInputElement).value).toBe("Notes");
    fireEvent.click(screen.getAllByLabelText(/Collapsible|collapsible/)[0] ?? document.body);
    fireEvent.click(btn("Delete section 3"));                                                                  // "Second", holding D
    expect(within(screen.getByLabelText("Fields not on the form")).getByText("D")).toBeTruthy();
  });
  it("adds, renames, reorders and deletes tabs - but never the last", async () => {
    await open();
    expect((btn("Delete tab") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(btn("Add tab"));
    expect(screen.getAllByRole("tab").map((x) => x.textContent)).toEqual(["Main", "New tab"]);
    fireEvent.change(screen.getByLabelText("Tab name"), { target: { value: "Notes" } });
    expect(screen.getAllByRole("tab")[1].textContent).toBe("Notes");
    expect(screen.getAllByRole("tab")[1].getAttribute("aria-selected")).toBe("true");
    fireEvent.click(btn("Move tab left"));
    expect(screen.getAllByRole("tab").map((x) => x.textContent)).toEqual(["Notes", "Main"]);
    fireEvent.click(btn("Delete tab"));
    expect(screen.getAllByRole("tab").map((x) => x.textContent)).toEqual(["Main"]);
  });
});

describe("LayoutDesigner - undo, redo, save and reset", () => {
  it("undoes and redoes every change", async () => {
    const { container } = await open();
    expect((btn("Undo") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(btn("Wider: A")); fireEvent.click(btn("Remove from the form: C"));
    expect(rowsOf(container)).toEqual(["a:7 b:5", "d:12"]);
    fireEvent.click(btn("Undo"));
    expect(rowsOf(container)).toEqual(["a:7 b:5", "c:12", "d:12"]);
    fireEvent.click(btn("Undo")); fireEvent.click(btn("Redo"));
    expect(rowsOf(container)[0]).toBe("a:7 b:5");
    fireEvent.click(btn("Wider: B"));                                                                          // a new edit clears what could be redone
    expect((btn("Redo") as HTMLButtonElement).disabled).toBe(true);
  });
  it("saves for everyone: sends exactly the layout on screen, refreshes the form's cached meta, and confirms", async () => {
    let stored = layout();
    const { calls } = await open({}, { "PUT /api/layout/Customer": ({ body }: any) => { stored = body.layout; return { saved: "company", layout: body.layout }; },
                                       "GET /api/layout/Customer": () => info({ source: "company", layout: stored }) });
    expect((btn("Save layout") as HTMLButtonElement).disabled).toBe(true);                                // nothing changed yet
    fireEvent.click(btn("Wider: A"));
    fireEvent.click(btn("Save layout"));
    expect(await screen.findByText("Saved for everyone in this company.")).toBeTruthy();
    const put = calls.find((c) => c.key === "PUT /api/layout/Customer")!;
    expect(put.body.target).toBe("company");
    expect(put.body.layout.tabs[0].sections[0].rows[0][0]).toEqual({ field: "a", span: 7 });
    expect(await screen.findByText("Company layout")).toBeTruthy();                                              // reloaded from the server
    expect((btn("Save layout") as HTMLButtonElement).disabled).toBe(true);                                // and clean again
  });
  it("after saving, the form fetches the NEW layout (the client's cached meta is discarded)", async () => {
    let metaFetches = 0;
    await open({}, { "GET /api/meta/Customer": () => { metaFetches += 1; return { name: "Customer", fields: [], permissions: {} }; }, "PUT /api/layout/Customer": ({ body }: any) => ({ saved: "company", layout: body.layout }) });
    await api.meta("Customer"); await api.meta("Customer");
    expect(metaFetches).toBe(1);                                                                               // cached: the second call did not hit the server
    fireEvent.click(btn("Wider: A")); fireEvent.click(btn("Save layout"));
    await screen.findByText("Saved for everyone in this company.");
    await api.meta("Customer");
    expect(metaFetches).toBe(2);                                                                               // saved: the cache was cleared, so the form sees the change
  });

  it("'Save into the app' exists only in developer mode and sends target app", async () => {
    const { calls } = await open({ can_write_app: true }, { "PUT /api/layout/Customer": ({ body }: any) => ({ saved: "app", layout: body.layout }) });
    fireEvent.click(btn("Wider: A")); fireEvent.click(btn("Save into the app"));
    expect(await screen.findByText("Saved into the app's DocType file.")).toBeTruthy();
    expect(calls.find((c) => c.key === "PUT /api/layout/Customer")!.body.target).toBe("app");
  });
  it("shows the server's reason when saving is refused, and keeps your changes", async () => {
    const { container } = await open({}, { "PUT /api/layout/Customer": () => fail(422, "ValidationError", "The layout is not valid:\n- tab 1: nope") });
    fireEvent.click(btn("Wider: A")); fireEvent.click(btn("Save layout"));
    expect((await screen.findByRole("alert")).textContent).toContain("The layout is not valid");
    expect(rowsOf(container)[0]).toBe("a:7 b:5");
  });
  it("resets to the app's layout after confirmation", async () => {
    let source = "company";
    const { calls } = await open({ source: "company" }, { "DELETE /api/layout/Customer": () => { source = "auto"; return { reset: "Customer" }; }, "GET /api/layout/Customer": () => info({ source }) });
    fireEvent.click(btn("Reset to default"));
    expect(await screen.findByText("Back to the default layout.")).toBeTruthy();
    expect(calls.some((c) => c.key === "DELETE /api/layout/Customer")).toBe(true);
    await waitFor(() => expect(screen.getByText("Not customised yet")).toBeTruthy());
  });
  it("does not reset when you cancel the confirmation", async () => {
    vi.stubGlobal("confirm", () => false);
    const { calls } = await open({ source: "company" });
    fireEvent.click(btn("Reset to default"));
    expect(calls.some((c) => c.key === "DELETE /api/layout/Customer")).toBe(false);
  });
});
