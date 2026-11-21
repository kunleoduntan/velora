import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setSession } from "../api";
import FormView, { fieldGridSpan } from "../components/FormView";
import { resetScripts } from "../clientScripts";
import customerDoc from "./fixtures/customer.doc.json";
import customerJs from "./fixtures/customer.form.js?raw";
import { fail, mockServer, META } from "./helpers";

const DOC = customerDoc as Record<string, any>;
const GET_DOC = { "GET /api/resource/Customer/CUST-0001": () => DOC, "GET /api/client_script/Customer": customerJs };

beforeEach(() => {
  resetScripts();
  setSession({ user: "sam", roles: "Sales User" });
  vi.stubGlobal("confirm", () => true);
  window.location.hash = "";
});

const ready = () => screen.findByRole("heading", { name: /Acme Ltd/ });
const input = (label: RegExp) => screen.getByLabelText(label) as HTMLInputElement;

describe("FormView - generated from metadata", () => {
  it("renders fields, required markers, child table and script effects with no Customer-specific React code", async () => {
    mockServer(GET_DOC);
    render(<FormView doctype="Customer" name="CUST-0001" />);
    await ready();
    expect(input(/Customer Name/).value).toBe("Acme Ltd");
    expect(screen.getByText("Customer Name").querySelector(".req")).not.toBeNull();   // required star
    expect((screen.getByLabelText("Status") as HTMLSelectElement).value).toBe("Blocked");
    expect(within(screen.getByTestId("table-contacts")).getByDisplayValue("Ada")).toBeTruthy();
    const toggle = screen.getByRole("switch", { name: /Tax Exempt/ }) as HTMLInputElement;  // Check field = switch
    expect(toggle.checked).toBe(true);
    expect(await screen.findByText(/customer is blocked/i)).toBeTruthy();              // customer.js set_intro
    expect(screen.getByRole("button", { name: "View Orders" })).toBeTruthy();          // customer.js add_button
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();               // Sales User cannot delete
    expect(screen.getByText("Saved")).toBeTruthy();
  });

  it("field-change scripts run: status toggles credit limit read-only", async () => {
    mockServer(GET_DOC);
    render(<FormView doctype="Customer" name="CUST-0001" />);
    await ready();
    const status = screen.getByLabelText("Status");
    fireEvent.change(status, { target: { value: "Active" } });
    expect(input(/Credit Limit/).readOnly).toBe(false);
    fireEvent.change(status, { target: { value: "Blocked" } });
    expect(input(/Credit Limit/).readOnly).toBe(true);
    expect(screen.getByText("Not Saved")).toBeTruthy();
  });

  it("saves with PUT, sending `modified` back for optimistic locking, then shows saved state", async () => {
    const calls = mockServer({ ...GET_DOC, "PUT /api/resource/Customer/CUST-0001": ({ body }) => ({ ...DOC, ...body, modified: "2030-01-01T00:00:00" }) });
    render(<FormView doctype="Customer" name="CUST-0001" />);
    await ready();
    fireEvent.change(input(/^Email/), { target: { value: "new@acme.ng" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByText("Saved")).toBeTruthy());
    const put = calls.find((c) => c.key.startsWith("PUT"))!;
    expect(put.body.modified).toBe(DOC.modified);
    expect(put.body.email).toBe("new@acme.ng");
    expect(put.body.contacts[0].contact_name).toBe("Ada");
  });

  it("shows the server's error (stale write -> 409) and stays dirty", async () => {
    mockServer({ ...GET_DOC, "PUT /api/resource/Customer/CUST-0001": () => fail(409, "TimestampMismatchError", "Customer CUST-0001 was modified by someone else. Reload and retry.") });
    render(<FormView doctype="Customer" name="CUST-0001" />);
    await ready();
    fireEvent.change(input(/^Email/), { target: { value: "x@y.ng" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toContain("modified by someone else");
    expect(screen.getByText("Not Saved")).toBeTruthy();
  });

  it("blocks save client-side when a required field is empty (no request sent)", async () => {
    const calls = mockServer(GET_DOC);
    render(<FormView doctype="Customer" name="CUST-0001" />);
    await ready();
    fireEvent.change(input(/Customer Name/), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Missing required: Customer Name");
    expect(input(/Customer Name/).className).toContain("invalid");
    expect(calls.some((c) => c.key.startsWith("PUT"))).toBe(false);
  });

  it("edits child rows: add + delete", async () => {
    const calls = mockServer({ ...GET_DOC, "PUT /api/resource/Customer/CUST-0001": ({ body }) => body });
    render(<FormView doctype="Customer" name="CUST-0001" />);
    await ready();
    const table = screen.getByTestId("table-contacts");
    fireEvent.click(within(table).getByRole("button", { name: "Add row" }));
    const inputs = within(table).getAllByRole("textbox");
    fireEvent.change(inputs[3], { target: { value: "Bola" } });       // row 2, contact_name
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.key.startsWith("PUT"))).toBe(true));
    expect(calls.find((c) => c.key.startsWith("PUT"))!.body.contacts.map((r: any) => r.contact_name)).toEqual(["Ada", "Bola"]);
    fireEvent.click(within(screen.getByTestId("table-contacts")).getByLabelText("Select row 1"));
    fireEvent.click(within(screen.getByTestId("table-contacts")).getByRole("button", { name: "Delete selected rows" }));
    expect(within(screen.getByTestId("table-contacts")).queryByDisplayValue("Ada")).toBeNull();
  });

  it("Check fields are switches; sections collapse and expand", async () => {
    mockServer(GET_DOC);
    render(<FormView doctype="Customer" name="CUST-0001" />);
    await ready();
    const sw = screen.getByRole("switch", { name: /Tax Exempt/ }) as HTMLInputElement;
    fireEvent.click(sw);
    expect(sw.checked).toBe(false);
    expect(screen.getByText("Not Saved")).toBeTruthy();
    const head = screen.getByRole("button", { name: /Contacts/ });
    expect(screen.getByTestId("table-contacts")).toBeTruthy();
    fireEvent.click(head);
    expect(screen.queryByTestId("table-contacts")).toBeNull();
    fireEvent.click(head);
    expect(screen.getByTestId("table-contacts")).toBeTruthy();
  });

  it("new document: applies metadata defaults and creates with POST", async () => {
    const calls = mockServer({ "GET /api/client_script/Customer": "", "POST /api/resource/Customer": ({ body }) => ({ ...DOC, ...body, name: "CUST-0002" }) });
    render(<FormView doctype="Customer" name="new" />);
    await screen.findByRole("heading", { name: "New Customer" });
    expect((screen.getByLabelText("Status") as HTMLSelectElement).value).toBe("Active");   // Select default
    fireEvent.change(input(/Customer Name/), { target: { value: "Fresh Co" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/resource/Customer")).toBe(true));
    expect(calls.find((c) => c.key.startsWith("POST"))!.body.customer_name).toBe("Fresh Co");
    await waitFor(() => expect(window.location.hash).toBe("#/app/Customer/CUST-0002"));
  });

  it("submittable: Submit for a draft, read-only once submitted", async () => {
    const order = { name: "SO-00001", doctype: "Sales Order", docstatus: 0, customer: "CUST-0001", order_date: "2026-11-07", total: 300.3, modified: "2026-11-07T10:00:00.1",
      items: [{ name: "i1", idx: 1, description: "Widget", qty: 3, rate: 100.1, amount: 300.3 }] };
    const calls = mockServer({
      "GET /api/client_script/Sales Order": "", "GET /api/resource/Sales Order/SO-00001": () => order,
      "POST /api/resource/Sales Order/SO-00001/submit": () => ({ ...order, docstatus: 1 }),
    });
    render(<FormView doctype="Sales Order" name="SO-00001" />);
    await screen.findByRole("heading", { name: "SO-00001" });
    expect(screen.getByText("Draft")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("Submitted");
    expect(calls.some((c) => c.key.endsWith("/submit"))).toBe(true);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Submit" })).toBeNull();
    expect((screen.getByLabelText(/Customer/) as HTMLInputElement).readOnly).toBe(true);
  });

  it("shows a load error for a document the user cannot read", async () => {
    mockServer({ "GET /api/client_script/Customer": "", "GET /api/resource/Customer/NOPE": () => fail(404, "DoesNotExistError", "Customer NOPE does not exist") });
    render(<FormView doctype="Customer" name="NOPE" />);
    expect(await screen.findByText(/does not exist/)).toBeTruthy();
    void META;
  });
});


describe("adaptive business form sizing", () => {
  it("uses narrower widths for dates and numeric fields, and wider widths for descriptive fields", () => {
    expect(fieldGridSpan({ fieldname: "posting_date", fieldtype: "Date", label: "Posting Date" } as any)).toBe(3);
    expect(fieldGridSpan({ fieldname: "description", fieldtype: "Data", label: "Description" } as any)).toBe(8);
    expect(fieldGridSpan({ fieldname: "amount", fieldtype: "Currency", label: "Amount" } as any)).toBe(3);
    expect(fieldGridSpan({ fieldname: "customer", fieldtype: "Link", label: "Customer" } as any)).toBe(4);
  });
});
