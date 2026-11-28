import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setSession } from "../api";
import { resetScripts } from "../clientScripts";
import LinkField from "../components/LinkField";
import ListView from "../components/ListView";
import { DEFAULTS, loadSettings, saveSettings } from "../listSettings";
import customerMeta from "./fixtures/customer.meta.json";
import listJs from "./fixtures/customer.list.js?raw";
import { mockServer, type Call } from "./helpers";

const rows = (n: number, from = 1) => Array.from({ length: n }, (_, i) => ({
  name: `CUST-${String(from + i).padStart(4, "0")}`, customer_name: `Cust ${from + i}`, status: i % 2 ? "Blocked" : "Active",
  credit_limit: (from + i) * 1000.5, docstatus: 0, modified: "2026-11-07T10:00:00",
}));

const GROUPS: Record<string, unknown[]> = {
  status: [{ value: "Active", count: 4 }, { value: "Blocked", count: 2 }],
  customer_group: [{ value: "Retail", count: 5 }, { value: null, count: 1 }],
  tax_exempt: [{ value: 1, count: 1 }, { value: 0, count: 5 }],
  owner: [{ value: "sam", count: 6 }],
};

function server(extra: Record<string, any> = {}, total = 45) {
  return mockServer({
    "GET /api/client_script/Customer": listJs,
    "GET /api/resource/Customer": ({ url }: any) => rows(Math.min(Number(url.searchParams.get("limit")), total), Number(url.searchParams.get("offset")) + 1),
    "GET /api/count/Customer": () => total,
    "GET /api/group_by/Customer": ({ url }: any) => GROUPS[url.searchParams.get("field")!] ?? [],
    "GET /api/aggregate/Customer": () => ({ credit_limit: 123456.5 }),
    ...extra,
  });
}
const lastList = (calls: Call[]) => calls.filter((c) => c.key === "GET /api/resource/Customer").at(-1)!;
const filtersOf = (c: Call) => JSON.parse(c.url.searchParams.get("filters") ?? "[]");
const withPerms = (p: Record<string, boolean>) => ({ ...customerMeta, permissions: { ...customerMeta.permissions, ...p } });

beforeEach(() => {
  resetScripts(); localStorage.clear();
  setSession({ user: "sam", roles: "Sales User" });
  window.location.hash = "";
  vi.stubGlobal("confirm", () => true);
});

async function open(query: Record<string, string> = {}) {
  const r = render(<ListView doctype="Customer" query={query} />);
  await screen.findByText("CUST-0001");
  return r;
}

describe("ListView - grid", () => {
  it("renders in_list_view columns with formatting, list-script indicators, count and paging", async () => {
    const calls = server();
    await open();
    expect(screen.getByRole("columnheader", { name: "Customer Name" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Credit Limit" })).toBeTruthy();
    expect(screen.getByText("1,000.50")).toBeTruthy();                           // Currency formatted
    expect(screen.getAllByText("Blocked").length).toBeGreaterThan(0);            // customer_list.js indicator
    expect(screen.getByText("1–20 of 45")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("CUST-0021")).toBeTruthy();
    expect(lastList(calls).url.searchParams.get("offset")).toBe("20");
    expect(screen.getByRole("button", { name: /New/ })).toBeTruthy();
  });

  it("changes page size and remembers it", async () => {
    const calls = server();
    await open();
    fireEvent.change(screen.getByLabelText("Rows per page"), { target: { value: "100" } });
    await waitFor(() => expect(lastList(calls).url.searchParams.get("limit")).toBe("100"));
    expect(loadSettings("sam", "Customer").pageSize).toBe(100);
  });

  it("sorts by clicking a header: asc, desc, then back to default", async () => {
    const calls = server();
    await open();
    const head = () => within(screen.getByRole("columnheader", { name: "Customer Name" })).getByRole("button", { name: "Customer Name" });
    fireEvent.click(head());
    await waitFor(() => expect(lastList(calls).url.searchParams.get("order_by")).toBe("customer_name asc"));
    fireEvent.click(head());
    await waitFor(() => expect(lastList(calls).url.searchParams.get("order_by")).toBe("customer_name desc"));
    expect(screen.getByRole("columnheader", { name: "Customer Name" }).getAttribute("aria-sort")).toBe("descending");
    fireEvent.click(head());
    await waitFor(() => expect(lastList(calls).url.searchParams.get("order_by")).toBeNull());
  });

  it("selects rows, ranges with shift-click, and the whole page", async () => {
    server();
    await open();
    const box = (n: number) => screen.getByLabelText(`Select CUST-000${n}`) as HTMLInputElement;
    fireEvent.click(box(1));
    fireEvent.click(box(4), { shiftKey: true });
    expect(screen.getByText("4 selected")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Select all on this page"));
    expect(screen.getByText("20 selected")).toBeTruthy();
    fireEvent.click(screen.getByText("Clear selection"));
    expect(screen.queryByText(/selected$/)).toBeNull();
  });

  it("offers 'select all N' beyond the page and fetches every matching name", async () => {
    const calls = server();
    await open();
    fireEvent.click(screen.getByLabelText("Select all on this page"));
    fireEvent.click(await screen.findByText("Select all 45 records"));
    expect(await screen.findByText("45 selected")).toBeTruthy();
    const all = calls.filter((c) => c.key === "GET /api/resource/Customer" && c.url.searchParams.get("limit") === "500");
    expect(all).toHaveLength(1);
  });

  it("shows an empty state that clears filters", async () => {
    server({ "GET /api/resource/Customer": () => [], "GET /api/count/Customer": () => 0 });
    render(<ListView doctype="Customer" query={{ status: "Blocked" }} />);
    expect(await screen.findByText(/No records match your filters/)).toBeTruthy();
  });

  it("applies URL filters as a chip (e.g. from 'View Orders')", async () => {
    const calls = server();
    await open({ customer_group: "Retail" });
    expect(screen.getByText("customer_group = Retail")).toBeTruthy();
    expect(filtersOf(lastList(calls))).toEqual([["customer_group", "=", "Retail"]]);
  });

  it("searches every column of the list with the _search filter", async () => {
    const calls = server();
    await open();
    fireEvent.change(screen.getByLabelText("Search this list"), { target: { value: "acme" } });
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([["_search", "like", "%acme%"]]));
  });

  it("shows backend permission errors", async () => {
    mockServer({
      "GET /api/client_script/Customer": "",
      "GET /api/resource/Customer": () => new Response(JSON.stringify({ error: "PermissionDenied", message: "no 'read' permission" }), { status: 403 }),
      "GET /api/count/Customer": () => 0, "GET /api/group_by/Customer": () => [],
    });
    render(<ListView doctype="Customer" query={{}} />);
    expect((await screen.findByRole("alert")).textContent).toContain("permission");
  });
});

describe("ListView - filtering", () => {
  it("standard filters (from in_standard_filter) filter inline", async () => {
    const calls = server();
    await open();
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "Blocked" } });
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([["status", "=", "Blocked"]]));
    fireEvent.change(screen.getByRole("combobox", { name: "Tax Exempt" }), { target: { value: "1" } });
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([["status", "=", "Blocked"], ["tax_exempt", "=", "1"]]));
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "" } });
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([["tax_exempt", "=", "1"]]));
  });

  it("advanced filter builder: add conditions, apply, see chips, remove one", async () => {
    const calls = server();
    await open();
    fireEvent.click(screen.getByRole("button", { name: /Filter/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add a filter" }));
    fireEvent.change(screen.getByLabelText("Field"), { target: { value: "credit_limit" } });
    fireEvent.change(screen.getByLabelText("Condition"), { target: { value: ">=" } });
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "5000" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a filter" }));
    const fields = screen.getAllByLabelText("Field");
    fireEvent.change(fields[1], { target: { value: "customer_name" } });           // default op = contains
    fireEvent.change(screen.getAllByLabelText("Value")[1], { target: { value: "acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([["credit_limit", ">=", "5000"], ["customer_name", "like", "%acme%"]]));
    expect(screen.getByText("Credit Limit at least 5000")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Filter\s*2/ })).toBeTruthy();       // badge count
    fireEvent.click(screen.getByRole("button", { name: "Remove filter Credit Limit at least 5000" }));
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([["customer_name", "like", "%acme%"]]));
  });

  it("'between' and 'is set' conditions", async () => {
    const calls = server();
    await open();
    fireEvent.click(screen.getByRole("button", { name: /Filter/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add a filter" }));
    fireEvent.change(screen.getByLabelText("Field"), { target: { value: "credit_limit" } });
    fireEvent.change(screen.getByLabelText("Condition"), { target: { value: "between" } });
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "900" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a filter" }));
    fireEvent.change(screen.getAllByLabelText("Field")[1], { target: { value: "email" } });
    fireEvent.change(screen.getAllByLabelText("Condition")[1], { target: { value: "is not set" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([["credit_limit", "between", ["100", "900"]], ["email", "is", "not set"]]));
  });

  it("group-by sidebar shows counts and filters on click (toggle off to clear)", async () => {
    const calls = server();
    await open();
    const side = within(await screen.findByLabelText("Group by"));
    expect(await side.findByText("Retail")).toBeTruthy();
    expect(side.getByText("Not set")).toBeTruthy();                                 // null bucket
    expect(side.getByText("Yes")).toBeTruthy();                                     // Check values read Yes/No
    const blocked = side.getByRole("button", { name: /Blocked/ });
    fireEvent.click(blocked);
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([["status", "=", "Blocked"]]));
    await waitFor(() => expect(side.getByRole("button", { name: /Blocked/ }).getAttribute("aria-pressed")).toBe("true"));
    fireEvent.click(side.getByRole("button", { name: /Blocked/ }));
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([]));
    fireEvent.click(side.getByRole("button", { name: /Not set/ }));
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([["customer_group", "is", "not set"]]));
  });

  it("saves, applies and deletes named views", async () => {
    const calls = server();
    await open();
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "Blocked" } });
    await waitFor(() => expect(filtersOf(lastList(calls))).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: /Views/ }));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "Blocked ones" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(loadSettings("sam", "Customer").views.map((v) => v.name)).toEqual(["Blocked ones"]);
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "" } });   // clear filter
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([]));
    fireEvent.click(screen.getByRole("button", { name: "Blocked ones" }));
    await waitFor(() => expect(filtersOf(lastList(calls))).toEqual([["status", "=", "Blocked"]]));
    fireEvent.click(screen.getByRole("button", { name: /Views/ }));
    fireEvent.click(screen.getByRole("button", { name: "Delete view Blocked ones" }));
    expect(loadSettings("sam", "Customer").views).toEqual([]);
  });
});

const heads = () => screen.getAllByRole("columnheader").map((h) => h.getAttribute("aria-label") ?? h.textContent);
const menuOn = (name: string) => fireEvent.contextMenu(screen.getByRole("columnheader", { name }), { clientX: 20, clientY: 20 });
const pick = (item: string | RegExp) => fireEvent.click(screen.getByRole("menuitem", { name: item }));

describe("ListView - report view columns (D365-style)", () => {
  it("Insert columns dialog: search, tick, order, OK applies + persists; Reset restores the defaults", async () => {
    server();
    await open();
    expect(heads().slice(1, 4)).toEqual(["ID", "Customer Name", "Status"]);
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    const dlg = within(screen.getByRole("dialog", { name: "Insert columns" }));
    fireEvent.change(dlg.getByLabelText("Search columns"), { target: { value: "email" } });
    expect(dlg.queryByLabelText("Credit Limit")).toBeNull();                       // search narrows the list
    fireEvent.click(dlg.getByLabelText("Email Address"));
    fireEvent.change(dlg.getByLabelText("Search columns"), { target: { value: "" } });
    fireEvent.click(dlg.getByRole("button", { name: "Move Email Address up" }));    // order: ... email, credit limit
    fireEvent.click(dlg.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(heads()).toContain("Email Address"));
    expect(heads().indexOf("Email Address")).toBeLessThan(heads().indexOf("Credit Limit"));
    expect(loadSettings("sam", "Customer").columns).toContain("email");
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Reset to default" }));
    await waitFor(() => expect(heads()).not.toContain("Email Address"));
    expect(loadSettings("sam", "Customer").columns).toBeNull();
  });

  it("'Select all shown' respects the search filter", async () => {
    server();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    const dlg = within(screen.getByRole("dialog"));
    fireEvent.change(dlg.getByLabelText("Search columns"), { target: { value: "email" } });
    fireEvent.click(dlg.getByLabelText("Select all shown"));
    fireEvent.change(dlg.getByLabelText("Search columns"), { target: { value: "" } });
    expect((dlg.getByLabelText("Email Address") as HTMLInputElement).checked).toBe(true);     // matched by the search: ticked
    expect((dlg.getByLabelText("Created On") as HTMLInputElement).checked).toBe(false);       // hidden by the search: untouched
  });

  it("right-click a header: sort from the menu, and insert columns right AFTER that column", async () => {
    const calls = server();
    await open();
    menuOn("Customer Name");
    pick("Sort A to Z");
    await waitFor(() => expect(lastList(calls).url.searchParams.get("order_by")).toBe("customer_name asc"));
    menuOn("Credit Limit");
    pick("Sort largest to smallest");                                              // numeric columns get number wording
    await waitFor(() => expect(lastList(calls).url.searchParams.get("order_by")).toBe("credit_limit desc"));
    menuOn("Credit Limit");
    pick("Clear sort");
    await waitFor(() => expect(lastList(calls).url.searchParams.get("order_by")).toBeNull());
    menuOn("Customer Name");
    pick("Insert columns…");
    fireEvent.click(within(screen.getByRole("dialog", { name: "Insert columns" })).getByLabelText("Email Address"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "OK" }));
    await waitFor(() => expect(heads()).toContain("Email Address"));
    expect(heads().slice(1, 5)).toEqual(["ID", "Customer Name", "Email Address", "Status"]);     // inserted right after Customer Name
  });

  it("the column-options chevron opens the same menu; Remove this column hides it (ID cannot be removed)", async () => {
    server();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Column options for Credit Limit" }));
    pick("Remove this column");
    await waitFor(() => expect(heads()).not.toContain("Credit Limit"));
    menuOn("ID");
    expect(screen.queryByRole("menuitem", { name: "Remove this column" })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Pin column/ })).toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("freezes the ID and the first four columns by default, like freeze panes in a spreadsheet", async () => {
    server();
    await open();
    expect(screen.getByRole("columnheader", { name: "Customer Name" }).className).toContain("sticky-col");
    expect(screen.getByRole("columnheader", { name: "Customer Name" }).style.left).toBe("190px");   // checkbox 40 + ID 150
  });

  it("pinning moves the column next to ID and makes it sticky with a computed offset; unpin releases it", async () => {
    server();
    saveSettings("sam", "Customer", { ...DEFAULTS, freeze: 0 });                 // no automatic freeze: pin by hand
    await open();
    menuOn("Credit Limit");
    pick("Pin column");
    await waitFor(() => expect(heads().slice(1, 4)).toEqual(["ID", "Credit Limit", "Customer Name"]));
    const th = screen.getByRole("columnheader", { name: "Credit Limit" });
    expect(th.className).toContain("sticky-col");
    expect(th.style.left).toBe("190px");                                           // checkbox 40 + ID 150
    expect(screen.getByRole("columnheader", { name: "Customer Name" }).className).not.toContain("sticky-col");
    expect(loadSettings("sam", "Customer").pinned).toEqual(["credit_limit"]);
    menuOn("Credit Limit");
    pick("Unpin column");
    await waitFor(() => expect(screen.getByRole("columnheader", { name: "Credit Limit" }).className).not.toContain("sticky-col"));
  });

  it("drag the header edge to resize (min 60px), persist it, double-click to reset", async () => {
    server();
    await open();
    const col = (i: number) => document.querySelectorAll<HTMLElement>("table.list-grid colgroup col")[i];
    expect(col(2).style.width).toBe("180px");                                      // [checkbox, ID, Customer Name, ...]
    const handle = screen.getByRole("separator", { name: "Resize Customer Name" });
    fireEvent.mouseDown(handle, { clientX: 100 });
    fireEvent.mouseMove(document, { clientX: 160 });
    expect(col(2).style.width).toBe("240px");                                      // live while dragging
    fireEvent.mouseUp(document);
    expect(loadSettings("sam", "Customer").widths.customer_name).toBe(240);
    fireEvent.mouseDown(handle, { clientX: 300 });
    fireEvent.mouseMove(document, { clientX: -900 });
    fireEvent.mouseUp(document);
    expect(col(2).style.width).toBe("60px");                                       // clamped
    fireEvent.doubleClick(handle);
    expect(col(2).style.width).toBe("180px");
    expect(loadSettings("sam", "Customer").widths.customer_name).toBeUndefined();
  });

  it("resizing does not reload the data or reset the page", async () => {
    const calls = server();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("CUST-0021");
    const before = calls.filter((c) => c.key === "GET /api/resource/Customer").length;
    const handle = screen.getByRole("separator", { name: "Resize Credit Limit" });
    fireEvent.mouseDown(handle, { clientX: 0 }); fireEvent.mouseMove(document, { clientX: 50 }); fireEvent.mouseUp(document);
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.filter((c) => c.key === "GET /api/resource/Customer").length).toBe(before);
    expect(screen.getByText("21–40 of 45")).toBeTruthy();
  });
});

describe("ListView - totals row and clipboard", () => {
  it("Totals shows the sum over ALL matching rows (server-side) and follows the filters", async () => {
    const calls = server();
    await open();
    expect(screen.queryByTestId("totals-row")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Totals" }));
    const row = await screen.findByTestId("totals-row");
    await waitFor(() => expect(within(row).getByText("123,456.50")).toBeTruthy());
    expect(within(row).getByText("Total (45)")).toBeTruthy();
    const agg = () => calls.filter((c) => c.key === "GET /api/aggregate/Customer").at(-1)!;
    expect(JSON.parse(agg().url.searchParams.get("fields")!)).toEqual(["credit_limit"]);              // only numeric visible columns
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "Blocked" } });
    await waitFor(() => expect(JSON.parse(agg().url.searchParams.get("filters")!)).toEqual([["status", "=", "Blocked"]]));
    expect(loadSettings("sam", "Customer").totals).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Totals" }));
    expect(screen.queryByTestId("totals-row")).toBeNull();
  });

  it("Copy to clipboard puts the selected rows on the clipboard as Excel-pasteable text", async () => {
    server();
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const toasts: string[] = [];
    window.addEventListener("velora:msg", (e) => toasts.push((e as CustomEvent).detail.message));
    await open();
    fireEvent.click(screen.getByLabelText("Select CUST-0001"));
    fireEvent.click(screen.getByLabelText("Select CUST-0002"));
    fireEvent.click(screen.getByRole("button", { name: /Actions/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Copy to clipboard" }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const lines = (writeText.mock.calls[0] as unknown as [string])[0].split("\n");
    expect(lines[0]).toBe("ID\tCustomer Name\tStatus\tCredit Limit");
    expect(lines.slice(1)).toEqual(["CUST-0001\tCust 1\tActive\t1,000.50", "CUST-0002\tCust 2\tBlocked\t2,001.00"]);
    await waitFor(() => expect(toasts).toContain("Copied 2 rows to the clipboard"));
  });
});

describe("ListView - bulk actions", () => {
  it("hides destructive actions the user has no permission for", async () => {
    server();
    await open();
    expect(screen.queryByRole("button", { name: /^Delete/ })).toBeNull();           // Sales User cannot delete Customers
  });

  it("bulk deletes, reports partial failures and keeps failed rows selected", async () => {
    const calls = server({
      "GET /api/meta/Customer": () => withPerms({ delete: true }),
      "POST /api/bulk/Customer": ({ body }: any) => body.names.map((n: string, i: number) => i === 1 ? { name: n, ok: false, error: `${n} is linked from Sales Order SO-1` } : { name: n, ok: true }),
    });
    const toasts: string[] = [];
    window.addEventListener("velora:msg", (e) => toasts.push((e as CustomEvent).detail.message));
    await open();
    fireEvent.click(screen.getByLabelText("Select CUST-0001"));
    fireEvent.click(screen.getByLabelText("Select CUST-0002"));
    fireEvent.click(screen.getByLabelText("Select CUST-0003"));
    fireEvent.click(screen.getByRole("button", { name: /^Delete/ }));
    const dlg = await screen.findByRole("dialog", { name: /1 of 3|2 of 3/ });
    expect(within(dlg).getByText(/CUST-0002 is linked from Sales Order/)).toBeTruthy();
    expect(calls.find((c) => c.key === "POST /api/bulk/Customer")!.body).toEqual({ action: "delete", names: ["CUST-0001", "CUST-0002", "CUST-0003"] });
    expect(toasts).toContain("Deleted 2 of 3");
    fireEvent.click(within(dlg).getByRole("button", { name: "OK" }));
    expect(await screen.findByText("1 selected")).toBeTruthy();                      // only the failed one stays selected
  });

  it("bulk edit sends the chosen field/value", async () => {
    const calls = server({
      "GET /api/meta/Customer": () => withPerms({ write: true }),
      "POST /api/bulk/Customer": ({ body }: any) => body.names.map((n: string) => ({ name: n, ok: true })),
    });
    await open();
    fireEvent.click(screen.getByLabelText("Select CUST-0001"));
    fireEvent.click(screen.getByRole("button", { name: /Actions/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Edit/ }));
    const dlg = within(screen.getByRole("dialog"));
    fireEvent.change(dlg.getByLabelText("Field"), { target: { value: "status" } });
    fireEvent.change(dlg.getByLabelText("New value"), { target: { value: "Inactive" } });
    fireEvent.click(dlg.getByRole("button", { name: "Update" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/bulk/Customer")).toBe(true));
    expect(calls.find((c) => c.key === "POST /api/bulk/Customer")!.body).toEqual({ action: "update", names: ["CUST-0001"], values: { status: "Inactive" } });
  });
});

describe("ListView - Excel export", () => {
  const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const xlsx = (rowsN: number) => () => new Response(new Blob(["PK"]), { status: 200, headers: {
    "Content-Type": XLSX, "Content-Disposition": 'attachment; filename="Customer_20261107_1000.xlsx"', "X-Velora-Rows": String(rowsN) } });
  let clicked: string[];
  beforeEach(() => {
    clicked = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked.push(this.download); });
  });

  it("exports the CURRENT VIEW: visible columns in order + active filters + sort", async () => {
    const calls = server({ "POST /api/export/Customer": xlsx(45) });
    await open();
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "Active" } });
    fireEvent.click(within(screen.getByRole("columnheader", { name: "Customer Name" })).getByRole("button", { name: "Customer Name" }));
    await waitFor(() => expect(lastList(calls).url.searchParams.get("order_by")).toBe("customer_name asc"));
    fireEvent.click(screen.getByRole("button", { name: /^Export$/ }));
    const dlg = within(screen.getByRole("dialog"));
    expect((dlg.getByLabelText(/Current view/) as HTMLInputElement).checked).toBe(true);   // default scope
    expect((dlg.getByLabelText(/All rows matching/) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(dlg.getByRole("button", { name: "Export" }));
    expect(await dlg.findByText(/Exported 45 rows to Customer_20261107_1000.xlsx/)).toBeTruthy();
    const body = calls.find((c) => c.key === "POST /api/export/Customer")!.body;
    expect(body).toEqual({ header: "label", order_by: "customer_name asc", columns: ["name", "customer_name", "status", "credit_limit"],
      filters: [["status", "=", "Active"]] });
    expect(clicked).toEqual(["Customer_20261107_1000.xlsx"]);                                // a real download was triggered
  });

  it("exports ALL FIELDS for the selected rows only, with field-name headers", async () => {
    const calls = server({ "POST /api/export/Customer": xlsx(2) });
    await open();
    fireEvent.click(screen.getByLabelText("Select CUST-0001"));
    fireEvent.click(screen.getByLabelText("Select CUST-0002"));
    fireEvent.click(screen.getByRole("button", { name: /Actions/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Export selected/ }));
    const dlg = within(screen.getByRole("dialog"));
    expect((dlg.getByLabelText(/Selected rows \(2\)/) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(dlg.getByLabelText(/All fields/));
    fireEvent.click(dlg.getByLabelText(/Field names/));
    fireEvent.click(dlg.getByRole("button", { name: "Export" }));
    await dlg.findByText(/Exported 2 rows/);
    expect(calls.find((c) => c.key === "POST /api/export/Customer")!.body).toEqual({
      header: "fieldname", all_fields: true, names: ["CUST-0001", "CUST-0002"] });
  });

  it("can export just the current page", async () => {
    const calls = server({ "POST /api/export/Customer": xlsx(20) });
    await open();
    fireEvent.click(screen.getByRole("button", { name: /^Export$/ }));
    const dlg = within(screen.getByRole("dialog"));
    fireEvent.click(dlg.getByLabelText(/This page only \(20\)/));
    fireEvent.click(dlg.getByRole("button", { name: "Export" }));
    await dlg.findByText(/Exported 20 rows/);
    const names = calls.find((c) => c.key === "POST /api/export/Customer")!.body.names;
    expect(names).toHaveLength(20);
    expect(names[0]).toBe("CUST-0001");
  });

  it("shows the server's refusal (e.g. no export permission) and downloads nothing", async () => {
    server({ "POST /api/export/Customer": () => new Response(JSON.stringify({ error: "PermissionDenied", message: "sam has no 'export' permission on Customer" }), { status: 403 }) });
    await open();
    fireEvent.click(screen.getByRole("button", { name: /^Export$/ }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Export" }));
    expect((await screen.findByRole("alert")).textContent).toContain("no 'export' permission");
    expect(clicked).toEqual([]);
  });

  it("hides every export entry point without the export permission", async () => {
    server({ "GET /api/meta/Customer": () => withPerms({ export: false }) });
    await open();
    expect(screen.queryByRole("button", { name: /^Export$/ })).toBeNull();
    fireEvent.click(screen.getByLabelText("Select CUST-0001"));
    fireEvent.click(screen.getByRole("button", { name: /Actions/ }));
    expect(screen.queryByRole("menuitem", { name: /Export selected/ })).toBeNull();
  });
});

describe("LinkField", () => {
  it("suggests records from the target DocType and selects one", async () => {
    mockServer({ "GET /api/search-link": () => [{ name: "Retail", title: "", description: "" }, { name: "Wholesale", title: "", description: "" }] });
    let chosen = "";
    render(<LinkField doctype="Customer Group" value="" onChange={(v) => (chosen = v)} />);
    fireEvent.focus(screen.getByRole("combobox"));
    const opt = await screen.findByText("Retail");
    fireEvent.mouseDown(opt);
    expect(chosen).toBe("Retail");
    void act;
  });
});
