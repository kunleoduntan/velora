import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAuthMode, setProfile, setSession } from "../api";
import ReportView from "../components/ReportView";
import { formatReportValue } from "../format";
import { fail, mockServer, reportDef, reportResult } from "./helpers";

const NAME = "Sales by Customer Group";
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "sam", roles: "Sales User" });
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

const routes = (extra: Record<string, any> = {}) => mockServer({
  [`GET /api/report/${NAME}`]: () => reportDef(), [`POST /api/report/${NAME}/run`]: () => reportResult(), "GET /api/resource/Customer Group": () => [{ name: "Retail" }], "GET /api/search-link": () => [{ name: "Retail", title: "", description: "" }], ...extra,
});
const runBodies = (calls: any[]) => calls.filter((c) => c.key === `POST /api/report/${NAME}/run`).map((c) => c.body);

describe("formatReportValue (accounting style)", () => {
  it("shows negatives in parentheses, zero as a dash, percentages from fractions", () => {
    expect(formatReportValue(1250.5, "Currency")).toBe("1,250.50");
    expect(formatReportValue(-300.25, "Currency")).toBe("(300.25)");
    expect(formatReportValue(0, "Currency")).toBe("-");
    expect(formatReportValue(0.256, "Percent")).toBe("25.6%");
    expect(formatReportValue(-0.1, "Percent")).toBe("(10.0%)");
    expect(formatReportValue(1234567, "Int")).toBe("1,234,567");
    expect(formatReportValue(null, "Currency")).toBe("");
    expect(formatReportValue(true, "Check")).toBe("Yes");
    expect(formatReportValue("2026-11-07T10:30:00", "Datetime")).toBe("2026-11-07 10:30");
  });
});

describe("ReportView", () => {
  it("runs on open and lays out the report like the Excel export: title block, summary, hierarchy, subtotals, total", async () => {
    const calls = routes();
    render(<ReportView name={NAME} />);
    expect(await screen.findByText("Velora Technologies")).toBeTruthy();
    expect(screen.getByRole("heading", { name: NAME, level: 2 })).toBeTruthy();
    expect(screen.getByText(/1 Jan 2026 to 7 Nov 2026\s+\|\s+Amounts in NGN/)).toBeTruthy();
    expect(screen.getByText("Filters: Customer Group = Retail")).toBeTruthy();
    expect(within(screen.getByText("Revenue").closest(".summary-card") as HTMLElement).getByText("10,750.25")).toBeTruthy();
    expect(runBodies(calls)).toEqual([{ filters: {} }]);                                  // defaults are resolved server-side
    const rows = Array.from(document.querySelectorAll("tbody tr")) as HTMLElement[];
    expect(rows.map((r) => r.dataset.rowType)).toEqual(["header", "data", "data", "subtotal", "data", "total"]);
    const cells = (i: number) => Array.from(rows[i].querySelectorAll("td")).map((c) => c.textContent);
    expect(cells(1)).toEqual(["Acme Ltd", "3", "1,250.50", "40.0%"]);
    expect(cells(2)).toEqual(["Zenith Foods", "2", "(300.25)", "10.0%"]);                 // negative in parentheses
    expect(cells(3)).toEqual(["Total Retail", "5", "950.25", ""]);
    expect(cells(4)).toEqual(["Idle Co", "-", "-", "-"]);                                   // zero is a dash - exactly like the Excel number format
    expect(cells(0)).toEqual(["Retail", "", "", ""]);                                       // section rows carry only the label
    expect((rows[1].querySelector("td") as HTMLElement).style.paddingLeft).toBe("30px");     // indent 1 -> 12 + 18
    expect((rows[0].querySelector("td") as HTMLElement).style.paddingLeft).toBe("12px");
    expect(rows[1].querySelectorAll("td")[2].className).toContain("num");                    // numbers right-aligned
    expect(screen.getByText(/Generated 07 Nov 2026/)).toBeTruthy();
  });

  it("prints plain-language (ad-hoc) filters without a stray '='", async () => {
    routes({ [`POST /api/report/${NAME}/run`]: () => reportResult({ filters: [["Status is not Inactive", ""], ["Customer Group", "Retail"]] }) });
    render(<ReportView name={NAME} />);
    expect(await screen.findByText("Filters: Status is not Inactive; Customer Group = Retail")).toBeTruthy();
  });

  it("builds filter inputs from the definition and sends only the filled ones", async () => {
    const calls = routes();
    render(<ReportView name={NAME} />);
    await screen.findByText("Velora Technologies");
    expect(screen.getByText("Default: Year Start")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("From Date"), { target: { value: "2026-02-01" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "Blocked" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Include drafts/ }));
    fireEvent.focus(screen.getByLabelText("Customer Group"));
    fireEvent.mouseDown(await screen.findByText("Retail", { selector: "strong" }));
    fireEvent.click(screen.getByRole("button", { name: "Run report" }));
    await waitFor(() => expect(runBodies(calls)).toHaveLength(2));
    expect(runBodies(calls)[1]).toEqual({ filters: { from_date: "2026-02-01", status: "Blocked", include_drafts: true, customer_group: "Retail" } });   // no empty keys
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "" } });                    // back to "All" removes it again
    fireEvent.submit(document.querySelector("form.report-filters") as HTMLFormElement);               // Enter in a filter runs the report
    await waitFor(() => expect(runBodies(calls)).toHaveLength(3));
    expect(runBodies(calls)[2].filters).not.toHaveProperty("status");
  });

  it("exports to Excel with the SAME filters and triggers a download", async () => {
    const calls = routes({ [`POST /api/report/${NAME}/export`]: () => new Response(new Blob(["PK"]), { status: 200, headers: { "Content-Disposition": 'attachment; filename="Sales_by_Customer_Group_20261107_1000.xlsx"' } }) });
    render(<ReportView name={NAME} />);
    await screen.findByText("Velora Technologies");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "Active" } });
    fireEvent.click(screen.getByRole("button", { name: "Export to Excel" }));
    await waitFor(() => expect(calls.some((c) => c.key === `POST /api/report/${NAME}/export`)).toBe(true));
    expect(calls.find((c) => c.key.endsWith("/export"))!.body).toEqual({ filters: { status: "Active" } });
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled());
  });

  it("hides Excel export when the user lacks the export permission", async () => {
    routes({ [`GET /api/report/${NAME}`]: () => reportDef({ can_export: false }) });
    render(<ReportView name={NAME} />);
    await screen.findByText("Velora Technologies");
    expect(screen.queryByRole("button", { name: "Export to Excel" })).toBeNull();
    expect(screen.getByRole("button", { name: "Print" })).toBeTruthy();
  });

  it("shows a refusal from the server and does not download", async () => {
    routes({ [`POST /api/report/${NAME}/export`]: () => fail(403, "PermissionDenied", "sam has no 'export' permission for 'Sales Order'") });
    render(<ReportView name={NAME} />);
    await screen.findByText("Velora Technologies");
    fireEvent.click(screen.getByRole("button", { name: "Export to Excel" }));
    expect((await screen.findByRole("alert")).textContent).toContain("no 'export' permission");
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  });

  it("shows run errors, clears the old result, and survives a missing report", async () => {
    routes({ [`POST /api/report/${NAME}/run`]: () => fail(422, "ValidationError", "Filter 'From Date': 'x' is not a valid Date") });
    render(<ReportView name={NAME} />);
    expect((await screen.findByRole("alert")).textContent).toContain("not a valid Date");
    expect(screen.queryByText("Velora Technologies")).toBeNull();
    mockServer({ "GET /api/report/Ghost": () => fail(404, "DoesNotExistError", "Report 'Ghost' does not exist") });
    render(<ReportView name="Ghost" />);
    expect(await screen.findByText(/does not exist/)).toBeTruthy();
  });

  it("shows an empty state, and Print uses the browser print dialog", async () => {
    routes({ [`POST /api/report/${NAME}/run`]: () => reportResult({ rows: [], summary: [] }) });
    const print = vi.fn();
    vi.stubGlobal("print", print);
    render(<ReportView name={NAME} />);
    expect(await screen.findByTestId("report-empty")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    expect(print).toHaveBeenCalled();
  });

  it("ignores a slow, out-of-date response (the latest run always wins)", async () => {
    let n = 0;
    routes({ [`POST /api/report/${NAME}/run`]: async () => {
      n += 1;
      if (n === 1) { await new Promise((r) => setTimeout(r, 150)); return reportResult({ title: "OLD result", company: "" }); }
      return reportResult({ title: "NEW result", company: "" });
    } });
    render(<ReportView name={NAME} />);                                                         // run #1 starts (slow)...
    await screen.findByRole("button", { name: "Running…" });                                    // ...and is genuinely in flight
    fireEvent.submit(document.querySelector("form.report-filters") as HTMLFormElement);        // Enter in a filter starts run #2 meanwhile
    expect(await screen.findByRole("heading", { name: "NEW result" })).toBeTruthy();
    await new Promise((r) => setTimeout(r, 300));                                               // let the old response arrive late
    expect(n).toBe(2);
    expect(screen.queryByRole("heading", { name: "OLD result" })).toBeNull();                  // it did not overwrite the newer result
    expect(screen.getByRole("heading", { name: "NEW result" })).toBeTruthy();
  });
});

describe("ReportView check filters with a default", () => {
  it("opens with the default ticked and can switch it off (sent as an explicit false)", async () => {
    const def = reportDef();
    def.filters = [{ fieldname: "include_open_orders", label: "Include Open Sales Orders", fieldtype: "Check", default: 1 }] as never;
    const calls = routes({ [`GET /api/report/${NAME}`]: () => def });
    render(<ReportView name={NAME} />);
    const box = (await screen.findByLabelText(/Include Open Sales Orders/)) as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    fireEvent.click(screen.getByRole("button", { name: /Run report/ }));
    await waitFor(() => expect(runBodies(calls).at(-1)).toMatchObject({ filters: { include_open_orders: false } }));
  });
});
