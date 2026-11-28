import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import AppHub from "../components/AppHub";
import { arrange, addShortcut, moveItem, readLayout, EMPTY_LAYOUT, validRoute } from "../hubLayout";
import { visibleHubs } from "../hubs";
import type { DocTypeInfo } from "../types";

const t = (name: string, app: string, module: string): DocTypeInfo => ({ name, app, module, is_submittable: false, can_create: true });
const types = [t("Sales Invoice", "velora_erp", "Finance"), t("Sales Order", "velora_erp", "Finance"), t("Supplier", "velora_erp", "Finance"), t("Payment", "velora_erp", "Finance"), t("Account", "velora_erp", "Finance")];
afterEach(() => { cleanup(); localStorage.clear(); });

const items = () => visibleHubs(types, []).find(h => h.hub.id === "finance")!.items;
const natural = () => ["Centres", ...visibleHubs(types, []).find(h => h.hub.id === "finance")!.hub.sections!.map(s => s.name), "Setup & Other", "Reports"];
const sectionNames = (el: HTMLElement) => [...el.querySelectorAll("section.hub-card")].map(s => s.getAttribute("aria-label"));
const keysIn = (el: HTMLElement, name: string) => [...el.querySelector(`section[aria-label="${name}"]`)!.querySelectorAll("li[data-key]")].map(li => li.getAttribute("data-key"));

describe("hub layout (pure)", () => {
  it("moves a shortcut into another section before a given one and keeps the order", () => {
    const v = arrange(items(), natural(), EMPTY_LAYOUT);
    const l = moveItem(EMPTY_LAYOUT, v, "doctype|Supplier", "Sales & Receivables", "doctype|Sales Order");
    const after = arrange(items(), natural(), l);
    expect(after.find(s => s.name === "Sales & Receivables")!.items.map(i => i.label)).toEqual(["Sales Invoice", "Supplier", "Sales Order"]);
    expect(after.find(s => s.name === "Purchasing & Payables")?.items.map(i => i.label) ?? []).not.toContain("Supplier");
  });
  it("only lets a shortcut lead to a place inside the desk", () => {
    expect(validRoute("#/app/Customer")).toBe(true);
    for (const bad of ["javascript:alert(1)", "https://evil.test", "//evil.test", "#/a<b>", ""]) expect(validRoute(bad)).toBe(false);
    expect(addShortcut(EMPTY_LAYOUT, "X", "javascript:alert(1)", "Centres").error).toBeTruthy();
  });
  it("ignores a damaged saved layout", () => {
    localStorage.setItem(Object.keys(localStorage)[0] ?? "x", "{");
    expect(readLayout("finance")).toEqual(EMPTY_LAYOUT);
  });
});

describe("hub customise mode", () => {
  const open = () => render(<AppHub types={types} reports={[]} hubId="finance" />);

  it("drags a shortcut into another section and remembers it", () => {
    const { container, unmount } = open();
    fireEvent.click(screen.getByRole("button", { name: /Customise/ }));
    const li = container.querySelector('li[data-key="doctype|Supplier"]')!;
    fireEvent.dragStart(li, { dataTransfer: { setData() {} } });
    fireEvent.drop(container.querySelector('section[aria-label="Sales & Receivables"]')!);
    expect(keysIn(container, "Sales & Receivables")).toContain("doctype|Supplier");
    unmount();
    const again = open();
    expect(keysIn(again.container, "Sales & Receivables")).toContain("doctype|Supplier");     // kept for this person
  });

  it("drops onto a shortcut to sit just before it", () => {
    const { container } = open();
    fireEvent.click(screen.getByRole("button", { name: /Customise/ }));
    fireEvent.dragStart(container.querySelector('li[data-key="doctype|Sales Order"]')!, { dataTransfer: { setData() {} } });
    fireEvent.drop(container.querySelector('li[data-key="doctype|Sales Invoice"]')!);
    expect(keysIn(container, "Sales & Receivables").slice(0, 2)).toEqual(["doctype|Sales Order", "doctype|Sales Invoice"]);
  });

  it("reorders sections by dragging and with the arrows", () => {
    const { container } = open();
    fireEvent.click(screen.getByRole("button", { name: /Customise/ }));
    const before = sectionNames(container);
    fireEvent.click(screen.getByRole("button", { name: `Move section ${before[1]} earlier` }));
    expect(sectionNames(container).slice(0, 2)).toEqual([before[1], before[0]]);
    const last = sectionNames(container).at(-1)!, first = sectionNames(container)[0]!;
    fireEvent.dragStart(container.querySelector(`section[aria-label="${last}"] h2`)!, { dataTransfer: { setData() {} } });
    fireEvent.drop(container.querySelector(`section[aria-label="${first}"]`)!);
    expect(sectionNames(container)[0]).toBe(last);
  });

  it("adds, edits and deletes a shortcut of my own, and refuses an unsafe link", () => {
    const { container } = open();
    fireEvent.click(screen.getByRole("button", { name: /Customise/ }));
    fireEvent.click(screen.getByRole("button", { name: /Add shortcut/ }));
    const form = screen.getByRole("group", { name: "Add shortcut" });
    const name = within(form).getByLabelText("Name"), opens = within(form).getByLabelText("Opens"), section = within(form).getByLabelText("Section");
    fireEvent.change(name, { target: { value: "Month-end" } }); fireEvent.change(opens, { target: { value: "javascript:alert(1)" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add" }));
    expect(screen.getByRole("alert").textContent).toMatch(/place inside Velora/);
    fireEvent.change(opens, { target: { value: "#/gl-review" } }); fireEvent.change(section, { target: { value: "My Close Tasks" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add" }));
    expect(container.querySelector('section[aria-label="My Close Tasks"] a[href="#/gl-review"]')?.textContent).toBe("Month-end");
    fireEvent.click(screen.getByRole("button", { name: "Edit Month-end" }));
    const edit = screen.getByRole("group", { name: "Edit shortcut" });
    fireEvent.change(within(edit).getByLabelText("Name"), { target: { value: "Close the month" } });
    fireEvent.click(within(edit).getByRole("button", { name: "Save shortcut" }));
    expect(screen.getByText("Close the month")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete Close the month" }));
    expect(screen.queryByText("Close the month")).toBeNull();
  });

  it("hides a built-in shortcut, brings it back, and resets to the standard layout", () => {
    const { container } = open();
    fireEvent.click(screen.getByRole("button", { name: /Customise/ }));
    fireEvent.click(screen.getByRole("button", { name: "Hide Payment" }));
    expect(container.querySelector('li[data-key="doctype|Payment"]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /＋ Payment/ }));
    expect(container.querySelector('li[data-key="doctype|Payment"]')).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Move Supplier up" }));
    fireEvent.click(screen.getByRole("button", { name: "Hide Account" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset to standard layout" }));
    expect(container.querySelector('li[data-key="doctype|Account"]')).not.toBeNull();
  });

  it("leaves the normal page free of editing controls", () => {
    const { container } = open();
    expect(container.querySelector("[draggable=true]")).toBeNull();
    expect(screen.queryByRole("button", { name: /Hide Payment/ })).toBeNull();
  });
});
