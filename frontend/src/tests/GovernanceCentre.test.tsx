import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GovernanceCentre from "../components/GovernanceCentre";

const calls: string[] = [];
const ok = (data: unknown) => Promise.resolve(new Response(JSON.stringify({ data }), { status: 200, headers: { "Content-Type": "application/json" } }));
beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    calls.push(`${url} ${init?.body ?? ""}`);
    if (url.endsWith("get_governance_report_catalog")) return ok([{ report_id: "board_register", title: "Board Register", description: "d", doctype: "Board" }, { report_id: "obligations", title: "Obligations", description: "o", doctype: "Governance Obligation" }]);
    if (url.endsWith("run_governance_report")) return ok({ report_id: "board_register", title: "Board Register", columns: ["name", "board_name"], rows: [{ name: "BRD-0001", board_name: "Main Board" }], summary: { record_count: 1, groups: [] } });
    if (url.endsWith("export_governance_report_xlsx")) return ok({ filename: "board.xlsx", content_base64: btoa("x") });
    if (url.endsWith("get_governance_exception_centre")) return ok({ rows: [{ name: "GEX-1", title: "Late return", severity: "High", status: "Open" }], total: 1, kpis: { total: 1, active: 1, overdue_active: 1, critical_active: 0 } });
    if (url.endsWith("get_governance_automation_execution_history_page")) return ok({ rows: [{ name: "GAE-1", status: "Failed", error_message: "boom" }], total: 1 });
    if (url.endsWith("retry_governance_automation_execution")) return ok({ ok: true });
    return ok({ periods: 2, readiness_percent: 75 });
  }));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Governance centre", () => {
  it("lists the report catalogue, runs the first report and exports it to Excel", async () => {
    render(<GovernanceCentre page="reports" />);
    expect(await screen.findByText("Main Board")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Export to Excel" }));
    await waitFor(() => expect(calls.some(c => c.includes("export_governance_report_xlsx") && c.includes("board_register"))).toBe(true));
  });
  it("shows exceptions with their counts", async () => {
    render(<GovernanceCentre page="exceptions" />);
    expect(await screen.findByText("Late return")).toBeTruthy();
  });
  it("offers Retry only for failed automation runs", async () => {
    render(<GovernanceCentre page="automation" />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText(/queued to run again/)).toBeTruthy();
  });
  it("shows sustainability readiness", async () => {
    render(<GovernanceCentre page="sustainability" />);
    expect(await screen.findByText("75%")).toBeTruthy();
  });
});

describe("Governance reporting screens", () => {
  it("shows the IFRS checklist for the chosen entity and period and opens requirements", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation((url: string, init?: RequestInit) => {
      calls.push(`${url} ${init?.body ?? ""}`);
      if (url.includes("/api/resource/Governance%20Entity")) return ok([{ name: "ACME" }]);
      if (url.includes("/api/resource/Sustainability%20Reporting%20Period")) return ok([{ period_name: "FY2026" }]);
      if (url.endsWith("get_issb_readiness")) return ok({ requirements: 82, assessed: 82, rows: [{ code: "S2.29(a)", title: "Scope 1", status: "Ready", readiness_percent: 100, evidence: "3 calculation(s) for Scope 1" }], summary: [], open_items: 1, inconsistencies: ["S2.22: marked complete, but the system finds: none"], notes: [], can_state_compliance: false });
      if (url.endsWith("generate_issb_checklist")) return ok({ created: 5, total: 82 });
      return ok({});
    });
    render(<GovernanceCentre page="issb" />);
    expect(await screen.findByText("3 calculation(s) for Scope 1")).toBeTruthy();
    expect(screen.getByText(/marked complete, but the system finds/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Generate checklist" }));
    expect(await screen.findByText(/5 requirement\(s\) opened/)).toBeTruthy();
  });
  it("lets a principle's practices be answered and saved, with the server's explanation rule surfaced", async () => {
    let saved = "";
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation((url: string, init?: RequestInit) => {
      calls.push(`${url} ${init?.body ?? ""}`);
      if (url.includes("/api/resource/Code%20Compliance%20Assessment")) return ok([{ name: "CCA-1" }]);
      if (url.endsWith("get_code_assessment")) return ok({ name: "CCA-1", principles: [{ number: 1, part: "A. Board", title: "Role of the Board", status: "Not assessed", how: "", evidence: "", practices: [{ reference: "1.1", requirement: "Board leads with integrity", status: "Not assessed", how: "", evidence: "" }] }], summary: { applied: 0, application_percent: 0, practices_assessed: 0, practices_in_scope: 1, practice_application_percent: 0 } });
      if (url.endsWith("save_code_assessment_answers")) { saved = String(init?.body); return Promise.resolve(new Response(JSON.stringify({ error: "Practice 1.1: give the explanation." }), { status: 400, headers: { "Content-Type": "application/json" } })); }
      return ok({});
    });
    render(<GovernanceCentre page="code" />);
    fireEvent.click(await screen.findByRole("button", { name: /Show 1 practices/ }));
    fireEvent.change(screen.getByLabelText("Status of practice 1.1"), { target: { value: "Explained (not applied)" } });
    fireEvent.click(screen.getByRole("button", { name: /Save answers \(1\)/ }));
    await waitFor(() => expect(saved).toContain("1.1"));
    expect(saved).toContain("Explained (not applied)");
  });
  it("offers the SASB template and counts responses without pretending any content is preloaded", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes("/api/resource/Governance%20Entity")) return ok([{ name: "ACME" }]);
      if (url.includes("/api/resource/Sustainability%20Reporting%20Period")) return ok([{ period_name: "FY2026" }]);
      if (url.endsWith("get_sasb_summary")) return ok({ total: 4, Reported: 2, Omitted: 1, "Not started": 1, "Not applicable": 0, answered_percent: 75 });
      return ok({});
    });
    render(<GovernanceCentre page="sasb" />);
    expect(await screen.findByText("75%")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download Excel template" })).toBeTruthy();
    expect(screen.getByText(/nothing is pre-loaded/)).toBeTruthy();
  });
});
