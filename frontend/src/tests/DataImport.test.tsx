import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearCaches, setAuthMode, setProfile, setSession } from "../api";
import DataImportPage from "../components/DataImportPage";
import ListView from "../components/ListView";
import { resetScripts } from "../clientScripts";
import { parseHash } from "../router";
import so from "./fixtures/sales_order.meta.json";
import customer from "./fixtures/customer.meta.json";
import { fail, mockServer } from "./helpers";

const REPORT = (over: Record<string, unknown> = {}) => ({ doctype: "Customer", mode: "insert", dry_run: true, total: 3, created: 2, updated: 0, failed: 1, ok: false, unknown_columns: [], errors: [{ row: 3, field: "Customer Group", message: "'Nowhere' is not an existing Customer Group. Create it first, or fix the spelling" }],
  errors_truncated: false, names: ["CUST-0001", "CUST-0002"], failed_rows: [{ row: 3, error: "Customer Group: 'Nowhere' is not an existing Customer Group", data: { "Customer Name": "Bad", "Customer Group": "Nowhere" } }], rolled_back: true, duration_ms: 5, ...over });
const CUST = (perms: Record<string, boolean> = {}) => ({ ...(customer as any), permissions: { ...(customer as any).permissions, ...perms } });
const SO = (perms: Record<string, boolean> = {}) => ({ ...(so as any), permissions: { ...(so as any).permissions, ...perms } });
const FILE = () => new File(["Customer Name\nAcme\n"], "Ọmọlọlá customers.csv", { type: "text/csv" });
const pick = (f: File | null) => fireEvent.change(screen.getByLabelText("File to import"), { target: { files: f ? [f] : [] } });
const btn = (n: RegExp | string) => screen.getByRole("button", { name: n });

beforeEach(() => { clearCaches(); resetScripts(); setAuthMode("developer"); setProfile(null); setSession({ user: "sam", roles: "Sales User" }); window.location.hash = ""; vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} })); });

const serve = (extra: Record<string, any> = {}, perms: Record<string, boolean> = {}) =>
  mockServer({ "GET /api/meta/Customer": () => CUST(perms), "GET /api/meta/Sales Order": () => SO(perms), ...extra });
const csvResp = (name: string) => new Response("a,b\n", { status: 200, headers: { "Content-Disposition": `attachment; filename="${name}"` } });

describe("getting the file ready", () => {
  it("offers an Excel template and, with permission, an Excel export; no CSV or JSON", async () => {
    const calls = serve({ "GET /api/data-import/Customer/template": () => csvResp("Customer_import_template.xlsx"), "GET /api/data-export/Customer": () => csvResp("Customer.xlsx") }, { export: true });
    render(<DataImportPage doctype="Customer" />);
    fireEvent.click(await screen.findByRole("button", { name: /Excel template/ }));
    await waitFor(() => expect(calls.filter((c) => c.key.endsWith("/template")).pop()!.url.searchParams.get("format")).toBe("xlsx"));
    expect(screen.queryByRole("button", { name: /CSV/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /JSON/ })).toBeNull();
    fireEvent.click(btn(/Export all to Excel/));
    await waitFor(() => expect(calls.some((c) => c.key === "GET /api/data-export/Customer" && c.url.searchParams.get("format") === "xlsx")).toBe(true));
    expect(screen.getByText(/same layout this page reads/)).toBeTruthy();
  });

  it("without export permission there are no export buttons", async () => {
    serve({}, { export: false });
    render(<DataImportPage doctype="Customer" />);
    await screen.findByRole("button", { name: /Excel template/ });
    expect(screen.queryByRole("button", { name: /Export all/ })).toBeNull();
  });

  it("shows the server's reason when a download is refused", async () => {
    serve({ "GET /api/data-import/Customer/template": () => fail(403, "PermissionDenied", "You may not create Customer") });
    render(<DataImportPage doctype="Customer" />);
    fireEvent.click(await screen.findByRole("button", { name: /Excel template/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("You may not create Customer");
  });
});

describe("the options", () => {
  it("Submit is offered only for submittable DocTypes the user may submit", async () => {
    serve();
    const { unmount } = render(<DataImportPage doctype="Customer" />);
    await screen.findByRole("button", { name: /Excel template/ });
    expect(screen.queryByLabelText(/Submit the documents/)).toBeNull();
    unmount(); clearCaches();
    serve({}, { submit: true });
    render(<DataImportPage doctype="Sales Order" />);
    expect(await screen.findByLabelText(/Submit the documents/)).toBeTruthy();
    cleanupAll();
    clearCaches();
    serve({}, { submit: false });
    render(<DataImportPage doctype="Sales Order" />);
    await screen.findByRole("button", { name: /Excel template/ });
    expect(screen.queryByLabelText(/Submit the documents/)).toBeNull();
  });

  it("updating is offered only to people who may write, and 'match by' only when updating", async () => {
    serve({}, { write: false });
    const { unmount } = render(<DataImportPage doctype="Customer" />);
    await screen.findByRole("button", { name: /Excel template/ });
    expect(screen.queryByLabelText(/Update existing records/)).toBeNull();
    unmount(); clearCaches();
    serve({}, { write: true });
    render(<DataImportPage doctype="Customer" />);
    expect(screen.queryByLabelText(/Find existing records by/)).toBeNull();
    fireEvent.click(await screen.findByLabelText(/Update existing records/));
    expect(screen.queryByLabelText(/Find existing records by/)).toBeNull();                         // this DocType has no unique field to match on: the ID column is the only way
    expect(screen.queryByLabelText(/Keep the IDs/)).toBeNull();                                     // pointless when only updating
    fireEvent.click(screen.getByLabelText(/Create or update/));
    expect(screen.getByLabelText(/Keep the IDs/)).toBeTruthy();
  });
});
function cleanupAll() { document.body.innerHTML = ""; }

it("a DocType with a unique field can be matched on it, and the choice is sent", async () => {
  const withUnique = { ...CUST({ write: true }), fields: (customer as any).fields.map((f: any) => (f.fieldname === "customer_name" ? { ...f, unique: true } : f)) };
  const calls = mockServer({ "GET /api/meta/Customer": () => withUnique, "POST /api/data-import/Customer": () => REPORT() });
  render(<DataImportPage doctype="Customer" />);
  fireEvent.click(await screen.findByLabelText(/Update existing records/));
  const sel = screen.getByLabelText(/Find existing records by/) as HTMLSelectElement;
  expect([...sel.options].map((o) => o.value)).toEqual(["", "customer_name"]);
  fireEvent.change(sel, { target: { value: "customer_name" } });
  pick(FILE());
  fireEvent.click(btn(/Check file/));
  await screen.findByTestId("import-result");
  const q = calls.find((c) => c.key === "POST /api/data-import/Customer")!.url.searchParams;
  expect([q.get("mode"), q.get("match")]).toEqual(["update", "customer_name"]);
});

describe("check, then import", () => {
  it("sends the file as it is, with every option, and a check saves nothing", async () => {
    const calls = serve({ "POST /api/data-import/Customer": () => REPORT() }, { write: true });
    render(<DataImportPage doctype="Customer" />);
    fireEvent.click(await screen.findByLabelText(/Create or update/));
    fireEvent.click(screen.getByLabelText(/All or nothing/));
    fireEvent.click(screen.getByLabelText(/Keep the IDs/));
    fireEvent.change(screen.getByLabelText(/Dates in the file/), { target: { value: "MDY" } });
    expect(btn(/Check file/).hasAttribute("disabled")).toBe(true);                                 // nothing to check yet
    expect(btn("Import").hasAttribute("disabled")).toBe(true);
    pick(FILE());
    expect(screen.getByText(/Ọmọlọlá customers.csv \(1 KB\)/)).toBeTruthy();
    fireEvent.click(btn(/Check file/));
    const res = await screen.findByTestId("import-result");
    const c = calls.find((x) => x.key === "POST /api/data-import/Customer")!;
    const q = c.url.searchParams;
    expect([q.get("mode"), q.get("dry_run"), q.get("atomic"), q.get("keep_names"), q.get("date_format"), q.get("submit")]).toEqual(["upsert", "1", "1", "1", "MDY", "0"]);
    expect(c.headers!["Content-Type"]).toBe("application/octet-stream");
    expect(c.headers!["X-Filename"]).toMatch(/^[\x20-\x7e]+$/);                                      // a browser refuses non-ASCII header values: it must be encoded
    expect(decodeURIComponent(c.headers!["X-Filename"])).toBe("Ọmọlọlá customers.csv");             // ... and the real name survives, accents and all
    expect(c.body).toBeInstanceOf(Blob);
    expect(within(res).getByText("Check finished: nothing was saved.")).toBeTruthy();
    expect(within(res).getByText(/1 document could not be imported/)).toBeTruthy();
  });

  it("shows the summary and each problem with its line, column and reason", async () => {
    serve({ "POST /api/data-import/Customer": () => REPORT({ unknown_columns: ["Mystery"] }) });
    render(<DataImportPage doctype="Customer" />);
    await screen.findByRole("button", { name: /Excel template/ });
    pick(FILE());
    fireEvent.click(btn(/Check file/));
    const res = await screen.findByTestId("import-result");
    expect(within(res).getByText("would be created").previousSibling!.textContent).toBe("2");
    expect(within(res).getByText("failed").previousSibling!.textContent).toBe("1");
    const row = within(res).getByRole("row", { name: /Customer Group/ });
    expect(row.textContent).toContain("3");
    expect(row.textContent).toContain("'Nowhere' is not an existing Customer Group");
    expect(within(res).getByText(/Ignored columns.*Mystery/)).toBeTruthy();
  });

  it("a clean check says the file can be imported", async () => {
    serve({ "POST /api/data-import/Customer": () => REPORT({ failed: 0, ok: true, errors: [], failed_rows: [], created: 3, rolled_back: true }) });
    render(<DataImportPage doctype="Customer" />);
    await screen.findByRole("button", { name: /Excel template/ });
    pick(FILE());
    fireEvent.click(btn(/Check file/));
    expect(await screen.findByText(/No problems found: you can import this file/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Open the Customer list/ })).toBeNull();               // a check is not an import
  });

  it("a real import reports what was created and links to the list", async () => {
    const calls = serve({ "POST /api/data-import/Customer": () => REPORT({ dry_run: false, failed: 0, ok: true, errors: [], failed_rows: [], created: 3, rolled_back: false }) });
    render(<DataImportPage doctype="Customer" />);
    await screen.findByRole("button", { name: /Excel template/ });
    pick(FILE());
    fireEvent.click(btn("Import"));
    expect(await screen.findByText("Import finished.")).toBeTruthy();
    expect(screen.getByText("Every document was imported.")).toBeTruthy();
    expect(calls.find((c) => c.key === "POST /api/data-import/Customer")!.url.searchParams.get("dry_run")).toBe("0");
    expect(screen.getByRole("link", { name: /Open the Customer list/ }).getAttribute("href")).toBe("#/app/Customer");
  });

  it("says plainly when all-or-nothing imported nothing", async () => {
    serve({ "POST /api/data-import/Customer": () => REPORT({ dry_run: false, created: 0, rolled_back: true }) });
    render(<DataImportPage doctype="Customer" />);
    await screen.findByRole("button", { name: /Excel template/ });
    pick(FILE());
    fireEvent.click(btn("Import"));
    expect(await screen.findByText("Nothing was imported (all or nothing).")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Open the Customer list/ })).toBeNull();
  });

  it("long error lists show the first 100 and say there are more", async () => {
    const errors = Array.from({ length: 130 }, (_, i) => ({ row: i + 2, field: "Status", message: `problem ${i}` }));
    serve({ "POST /api/data-import/Customer": () => REPORT({ errors, failed: 130 }) });
    render(<DataImportPage doctype="Customer" />);
    await screen.findByRole("button", { name: /Excel template/ });
    pick(FILE());
    fireEvent.click(btn(/Check file/));
    const res = await screen.findByTestId("import-result");
    expect(within(res).getAllByRole("row")).toHaveLength(101);                                       // header + 100
    expect(within(res).getByText(/Showing the first 100 of 130 problems/)).toBeTruthy();
  });

  it("the failed rows come back as a file to fix and re-upload", async () => {
    const calls = serve({ "POST /api/data-import/Customer": () => REPORT(), "POST /api/data-import/errors-xlsx": () => csvResp("import_errors.xlsx") });
    render(<DataImportPage doctype="Customer" />);
    await screen.findByRole("button", { name: /Excel template/ });
    pick(FILE());
    fireEvent.click(btn(/Check file/));
    fireEvent.click(await screen.findByRole("button", { name: /Download the failed rows/ }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/data-import/errors-xlsx")).toBe(true));
    expect(calls.find((c) => c.key === "POST /api/data-import/errors-xlsx")!.body.failed_rows[0].data["Customer Name"]).toBe("Bad");
    expect(screen.getByText(/original columns plus an Error column/)).toBeTruthy();
  });

  it("shows the server's reason when the file itself is unusable, and changing an option clears a stale result", async () => {
    let n = 0;
    serve({ "POST /api/data-import/Customer": () => (n++ === 0 ? fail(422, "ImportFileError", "Unsupported file type. Use an Excel file (.xlsx), a CSV file (.csv) or a JSON file (.json).") : REPORT()) });
    render(<DataImportPage doctype="Customer" />);
    await screen.findByRole("button", { name: /Excel template/ });
    pick(new File(["x"], "a.exe"));
    fireEvent.click(btn(/Check file/));
    expect((await screen.findByRole("alert")).textContent).toContain("Unsupported file type");
    pick(FILE());
    expect(screen.queryByRole("alert")).toBeNull();                                                  // choosing another file clears the old error
    fireEvent.click(btn(/Check file/));
    await screen.findByTestId("import-result");
    fireEvent.click(screen.getByLabelText(/All or nothing/));
    expect(screen.queryByTestId("import-result")).toBeNull();                                        // the result described different options: it must not linger
  });
});

describe("getting here", () => {
  it("has its own address", () => {
    expect(parseHash("#/import/Sales%20Order")).toMatchObject({ kind: "import", doctype: "Sales Order" });
    expect(parseHash("#/import").kind).toBe("home");
  });

  it("a list offers Import to those who may create, and not otherwise", async () => {
    const list = { "GET /api/resource/Customer": () => [], "GET /api/count/Customer": () => 0 };
    serve(list, { create: true });
    const { unmount } = render(<ListView doctype="Customer" query={{}} />);
    const link = await screen.findByRole("link", { name: /Import/ });
    expect(link.getAttribute("href")).toBe("#/import/Customer");
    unmount(); clearCaches();
    serve(list, { create: false });
    render(<ListView doctype="Customer" query={{}} />);
    await screen.findByRole("toolbar", { name: "List actions" });
    expect(screen.queryByRole("link", { name: /Import/ })).toBeNull();
  });
});
