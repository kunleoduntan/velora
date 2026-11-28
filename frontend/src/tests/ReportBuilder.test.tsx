import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAuthMode, setProfile, setSession } from "../api";
import ReportBuilder from "../components/ReportBuilder";
import customerMeta from "./fixtures/customer.meta.json";
import { fail, mockServer, reportResult } from "./helpers";

const TYPES = [{ name: "Customer", module: "Demo", app: "demo", is_submittable: false, can_create: true }, { name: "Sales Order", module: "Demo", app: "demo", is_submittable: true, can_create: true }];
const SPEC = { doctype: "Customer", group_by: ["customer_group", "status"], date_field: null, date_bucket: null, measures: [{ fn: "count", label: "Customers" }, { fn: "sum", field: "credit_limit", label: "Limit" }], filters: [["status", "=", "Blocked"]], title: "Credit by group" };
const SAVED = { id: "SR-ab12", name: "Credit by group", doctype: "Customer", owner: "sam", shared: false, can_edit: true, updated_on: "2026-11-07T10:00:00", spec: SPEC };

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "sam", roles: "Sales User" });
  window.location.hash = "";
  vi.stubGlobal("confirm", () => true);
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

const server = (extra: Record<string, any> = {}) => mockServer({ "GET /api/doctypes": () => TYPES, "POST /api/adhoc-report/run": () => reportResult({ title: "Credit by group" }), ...extra });
const bodies = (calls: any[], key: string) => calls.filter((c) => c.key === key).map((c) => c.body);
const choose = async (doctype = "Customer") => { fireEvent.change(await screen.findByLabelText("Report on"), { target: { value: doctype } }); await waitFor(() => expect((screen.getByLabelText("Group by") as HTMLSelectElement).disabled).toBe(false)); };
const options = (label: string) => Array.from((screen.getByLabelText(label) as HTMLSelectElement).options).map((o) => o.textContent);

describe("ReportBuilder - defining a report", () => {
  it("offers only sensible fields: groupable ones for Group by, numeric ones for totals", async () => {
    server();
    render(<ReportBuilder />);
    await choose();
    const g = options("Group by");
    expect(g).toEqual(expect.arrayContaining(["Customer Group", "Status", "Customer Name", "Tax Exempt", "Created By", "Created On"]));
    expect(g).not.toContain("Credit Limit");                      // a currency is something you total, not group by
    expect(g).not.toContain("ID");
    expect(g).not.toContain("Contacts");                          // child tables are not groupable
    fireEvent.change(screen.getByLabelText("Total 1 function"), { target: { value: "sum" } });
    expect(options("Total 1 field")).toEqual(["Field…", "Credit Limit"]);
  });

  it("tells you what is missing and blocks Run until the definition is complete", async () => {
    const calls = server();
    render(<ReportBuilder />);
    expect(await screen.findByTestId("builder-hint")).toHaveProperty("textContent", "Choose what to report on.");
    expect(screen.getByRole("button", { name: "Run report" }).hasAttribute("disabled")).toBe(true);
    await choose();
    expect(screen.getByTestId("builder-hint").textContent).toBe("Choose at least one field to group by.");
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "status" } });
    expect(screen.queryByTestId("builder-hint")).toBeNull();
    fireEvent.change(screen.getByLabelText("Total 1 function"), { target: { value: "avg" } });
    expect(screen.getByTestId("builder-hint").textContent).toBe("Pick a field for each total.");
    expect(screen.getByRole("button", { name: "Run report" }).hasAttribute("disabled")).toBe(true);
    expect(calls.some((c) => c.key === "POST /api/adhoc-report/run")).toBe(false);          // nothing was sent while incomplete
  });

  it("runs the exact definition: two group levels, several totals, a filter and a title", async () => {
    const calls = server();
    render(<ReportBuilder />);
    await choose();
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "customer_group" } });
    expect(options("Then by (optional)")).not.toContain("Customer Group");                  // no duplicate grouping
    fireEvent.change(screen.getByLabelText("Then by (optional)"), { target: { value: "status" } });
    fireEvent.change(screen.getByLabelText("Total 1 label"), { target: { value: "Customers" } });
    fireEvent.click(screen.getByRole("button", { name: /Add a total/ }));
    fireEvent.change(screen.getByLabelText("Total 2 function"), { target: { value: "sum" } });
    fireEvent.change(screen.getByLabelText("Total 2 field"), { target: { value: "credit_limit" } });
    fireEvent.change(screen.getByLabelText("Total 2 label"), { target: { value: "Limit" } });
    fireEvent.change(screen.getByLabelText("Report title"), { target: { value: "Credit by group" } });
    fireEvent.click(screen.getByRole("button", { name: /Filter/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add a filter" }));
    fireEvent.change(screen.getByLabelText("Field"), { target: { value: "status" } });
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "Blocked" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(screen.getByText("Status equals Blocked")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Run report" }));
    expect(await screen.findByText("Velora Technologies")).toBeTruthy();                      // the shared report sheet is shown
    expect(bodies(calls, "POST /api/adhoc-report/run")).toEqual([SPEC]);
    fireEvent.click(screen.getByRole("button", { name: "Remove filter Status equals Blocked" }));
    expect(screen.queryByText("Status equals Blocked")).toBeNull();
  });

  it("grouping by a date field reveals a date bucket and sends it; other fields do not", async () => {
    const calls = server({ "GET /api/meta/Sales Order": () => ({ ...(customerMeta as any), name: "Sales Order", is_submittable: true, fields: [{ fieldname: "order_date", label: "Order Date", fieldtype: "Date" }, { fieldname: "total", label: "Total", fieldtype: "Currency" }, { fieldname: "customer", label: "Customer", fieldtype: "Link", options: "Customer" }] }) });
    render(<ReportBuilder />);
    await choose("Sales Order");
    expect(screen.queryByLabelText("Group dates by")).toBeNull();
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "customer" } });
    expect(screen.queryByLabelText("Group dates by")).toBeNull();
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "order_date" } });
    fireEvent.change(await screen.findByLabelText("Group dates by"), { target: { value: "quarter" } });
    expect(options("Group by")).toContain("Status");                                          // submittable DocTypes can group by document status
    fireEvent.click(screen.getByRole("button", { name: "Run report" }));
    await waitFor(() => expect(bodies(calls, "POST /api/adhoc-report/run")).toHaveLength(1));
    expect(bodies(calls, "POST /api/adhoc-report/run")[0]).toMatchObject({ doctype: "Sales Order", group_by: ["order_date"], date_field: "order_date", date_bucket: "quarter" });
  });

  it("a system date (Created On) also offers buckets", async () => {
    server();
    render(<ReportBuilder />);
    await choose();
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "creation" } });
    expect(await screen.findByLabelText("Group dates by")).toBeTruthy();
  });

  it("changing the DocType clears the old definition (fields no longer exist)", async () => {
    server();
    render(<ReportBuilder />);
    await choose();
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "status" } });
    fireEvent.change(screen.getByLabelText("Report on"), { target: { value: "Sales Order" } });
    await waitFor(() => expect((screen.getByLabelText("Group by") as HTMLSelectElement).value).toBe(""));
    expect(screen.getByTestId("builder-hint").textContent).toBe("Choose at least one field to group by.");
  });
});

describe("ReportBuilder - export, errors and permissions", () => {
  const ready = async () => { await choose(); fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "status" } }); };

  it("exports the SAME definition to Excel and downloads it", async () => {
    const calls = server({ "POST /api/adhoc-report/export": () => new Response(new Blob(["PK"]), { status: 200, headers: { "Content-Disposition": 'attachment; filename="Customer_summary_20261107_1000.xlsx"' } }) });
    render(<ReportBuilder />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Export to Excel" }));
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled());
    expect(bodies(calls, "POST /api/adhoc-report/export")[0]).toMatchObject({ doctype: "Customer", group_by: ["status"], measures: [{ fn: "count" }] });
  });

  it("hides Excel export when the DocType's export permission is missing", async () => {
    server({ "GET /api/meta/Customer": () => ({ ...(customerMeta as any), permissions: { ...(customerMeta as any).permissions, export: false } }) });
    render(<ReportBuilder />);
    await ready();
    expect(screen.queryByRole("button", { name: "Export to Excel" })).toBeNull();
    expect(screen.getByRole("button", { name: "Run report" })).toBeTruthy();
  });

  it("shows server errors for running and exporting, and clears the stale result", async () => {
    server({ "POST /api/adhoc-report/run": () => fail(422, "ValidationError", "Invalid field(s): ['nope']"), "POST /api/adhoc-report/export": () => fail(403, "PermissionDenied", "sam has no 'export' permission") });
    render(<ReportBuilder />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Run report" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Invalid field");
    fireEvent.click(screen.getByRole("button", { name: "Export to Excel" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("no 'export' permission"));
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  });
});

describe("ReportBuilder - saving and reopening", () => {
  it("saves a new report (name + definition + sharing) and tells the shell", async () => {
    const calls = server({ "POST /api/saved-reports": ({ body }: any) => ({ ...SAVED, name: body.name, spec: body.spec }) });
    const changed = vi.fn();
    window.addEventListener("velora:saved-reports-changed", changed);
    render(<ReportBuilder />);
    await choose();
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "status" } });
    fireEvent.click(screen.getByRole("button", { name: "Save report" }));
    fireEvent.change(screen.getByLabelText("Report name"), { target: { value: "My credit view" } });
    fireEvent.click(screen.getByRole("switch", { name: /Share with everyone/ }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Saved as "My credit view"/)).toBeTruthy();
    const body = bodies(calls, "POST /api/saved-reports")[0];
    expect(body).toMatchObject({ name: "My credit view", shared: true, spec: { doctype: "Customer", group_by: ["status"] } });
    expect(window.location.hash).toBe("#/builder/SR-ab12");
    expect(changed).toHaveBeenCalled();
    window.removeEventListener("velora:saved-reports-changed", changed);
  });

  it("shows the server's reason when saving is refused (e.g. sharing without rights)", async () => {
    server({ "POST /api/saved-reports": () => fail(403, "PermissionDenied", "Only a System Manager can share a report with the company") });
    render(<ReportBuilder />);
    await choose();
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "status" } });
    fireEvent.click(screen.getByRole("button", { name: "Save report" }));
    fireEvent.change(screen.getByLabelText("Report name"), { target: { value: "X" } });
    fireEvent.click(screen.getByRole("switch", { name: /Share with everyone/ }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Only a System Manager");
  });

  it("opens a saved report, restores every setting (filters included) and runs it", async () => {
    const calls = server({ "GET /api/saved-report/SR-ab12": () => SAVED });
    render(<ReportBuilder id="SR-ab12" />);
    expect(await screen.findByText("Velora Technologies")).toBeTruthy();                      // auto-ran
    expect((screen.getByLabelText("Report on") as HTMLSelectElement).value).toBe("Customer");
    await waitFor(() => expect((screen.getByLabelText("Group by") as HTMLSelectElement).value).toBe("customer_group"));
    expect((screen.getByLabelText("Then by (optional)") as HTMLSelectElement).value).toBe("status");
    expect((screen.getByLabelText("Total 2 field") as HTMLSelectElement).value).toBe("credit_limit");
    expect((screen.getByLabelText("Total 2 label") as HTMLInputElement).value).toBe("Limit");
    expect((screen.getByLabelText("Report title") as HTMLInputElement).value).toBe("Credit by group");
    expect(screen.getByText("Status equals Blocked")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Credit by group", level: 1 })).toBeTruthy();
    expect(bodies(calls, "POST /api/adhoc-report/run")[0]).toEqual(SPEC);                      // round trip is lossless
  });

  it("updates the saved report in place, or saves a copy", async () => {
    const calls = server({ "GET /api/saved-report/SR-ab12": () => SAVED, "PUT /api/saved-report/SR-ab12": ({ body }: any) => ({ ...SAVED, ...body }),
      "POST /api/saved-reports": ({ body }: any) => ({ ...SAVED, id: "SR-new1", name: body.name, spec: body.spec }) });
    render(<ReportBuilder id="SR-ab12" />);
    await screen.findByText("Velora Technologies");
    fireEvent.change(screen.getByLabelText("Report title"), { target: { value: "Renamed title" } });
    fireEvent.click(screen.getByRole("button", { name: "Save report" }));
    fireEvent.click(screen.getByRole("button", { name: /Update “Credit by group”/ }));
    await screen.findByText(/Saved changes/);
    expect(bodies(calls, "PUT /api/saved-report/SR-ab12")[0].spec.title).toBe("Renamed title");
    fireEvent.click(screen.getByRole("button", { name: "Save report" }));
    fireEvent.change(screen.getByLabelText("Report name"), { target: { value: "Copy of it" } });
    fireEvent.click(screen.getByRole("button", { name: "Save as new" }));
    await waitFor(() => expect(window.location.hash).toBe("#/builder/SR-new1"));
    expect(bodies(calls, "POST /api/saved-reports")[0].name).toBe("Copy of it");
  });

  it("deletes after confirmation and returns to a blank builder", async () => {
    const calls = server({ "GET /api/saved-report/SR-ab12": () => SAVED, "DELETE /api/saved-report/SR-ab12": () => ({ deleted: "SR-ab12" }) });
    render(<ReportBuilder id="SR-ab12" />);
    await screen.findByText("Velora Technologies");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.key === "DELETE /api/saved-report/SR-ab12")).toBe(true));
    expect(window.location.hash).toBe("#/builder");
  });

  it("someone else's shared report can be run but not changed or deleted", async () => {
    server({ "GET /api/saved-report/SR-ab12": () => ({ ...SAVED, owner: "boss", shared: true, can_edit: false }) });
    render(<ReportBuilder id="SR-ab12" />);
    await screen.findByText("Velora Technologies");
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save report" }));
    expect(screen.queryByRole("button", { name: /Update/ })).toBeNull();                     // only "Save" (as a copy of your own)
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Save as new" })).toBeTruthy();
  });

  it("reports a saved report that does not exist (or is private to someone else)", async () => {
    server({ "GET /api/saved-report/SR-zzzz": () => fail(404, "DoesNotExistError", "Saved report not found") });
    render(<ReportBuilder id="SR-zzzz" />);
    expect((await screen.findByRole("alert")).textContent).toContain("not found");
  });
});
