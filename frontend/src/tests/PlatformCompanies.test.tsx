import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PlatformCompanies from "../components/PlatformCompanies";
import { mockServer } from "./helpers";

const companies = [
  { id: "COMP-001", tenant_id: "T1", tenant_name: "Group", name: "My Company", code: "my-company", status: "active", db_engine: "postgres" },
  { id: "COMP-002", tenant_id: "T1", tenant_name: "Group", name: "Complexia Ltd", code: "complexia-ltd", status: "failed", db_engine: "postgres", provisioning_error: "password authentication failed" },
  { id: "COMP-003", tenant_id: "T1", tenant_name: "Group", name: "Paused Ltd", code: "paused", status: "suspended", db_engine: "postgres" },
];
const base = (pgAdmin: { configured: boolean; user: string }) => ({
  "GET /api/platform/companies": () => companies, "GET /api/platform/tenants": () => [{ id: "T1", name: "Group", status: "active" }],
  "GET /api/platform/users": () => [], "GET /api/platform/pg-admin": () => pgAdmin,
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Company administration", () => {
  it("does not ask for a PostgreSQL password when the server already has an administrator login", async () => {
    mockServer(base({ configured: true, user: "velora_root" }));
    render(<PlatformCompanies />);
    expect(await screen.findByText(/Nothing to type/)).toBeTruthy();
    expect(screen.queryByLabelText("PostgreSQL administrator password")).toBeNull();
  });
  it("asks for the password only when the server has none saved", async () => {
    mockServer(base({ configured: false, user: "postgres" }));
    render(<PlatformCompanies />);
    expect(await screen.findByText("PostgreSQL administrator password")).toBeTruthy();
  });
  it("shows why a company failed", async () => {
    mockServer(base({ configured: true, user: "velora_root" }));
    render(<PlatformCompanies />);
    expect(await screen.findByText("password authentication failed")).toBeTruthy();
  });
  it("suspends and activates", async () => {
    const calls = mockServer({ ...base({ configured: true, user: "velora_root" }), "POST /api/platform/companies/COMP-001/status": () => ({}), "POST /api/platform/companies/COMP-003/status": () => ({}) });
    render(<PlatformCompanies />);
    fireEvent.click(await screen.findByLabelText("Suspend My Company"));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/platform/companies/COMP-001/status" && c.body.status === "suspended")).toBe(true));
    fireEvent.click(await screen.findByLabelText("Activate Paused Ltd"));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/platform/companies/COMP-003/status" && c.body.status === "active")).toBe(true));
  });
  it("deletes only after the exact name is typed", async () => {
    const calls = mockServer({ ...base({ configured: true, user: "velora_root" }), "DELETE /api/platform/companies/COMP-002": () => ({ id: "COMP-002", deleted: true, note: "done" }) });
    render(<PlatformCompanies />);
    fireEvent.click(await screen.findByLabelText("Delete Complexia Ltd"));
    const go = screen.getByText("Delete permanently") as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Confirm company name"), { target: { value: "complexia ltd" } });
    expect(go.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Confirm company name"), { target: { value: "Complexia Ltd" } });
    expect(go.disabled).toBe(false);
    fireEvent.click(go);
    await waitFor(() => expect(calls.some((c) => c.key === "DELETE /api/platform/companies/COMP-002" && c.body.confirm === "Complexia Ltd")).toBe(true));
  });
});

describe("Open a company", () => {
  it("opens an active company and asks the Desk to refresh the company list", async () => {
    const calls = mockServer({ ...base({ configured: true, user: "velora_root" }), "POST /api/platform/companies/COMP-001/open": () => ({ id: "COMP-001", name: "My Company" }) });
    const seen = vi.fn(); window.addEventListener("velora:profile-changed", seen);
    render(<PlatformCompanies />);
    fireEvent.click(await screen.findByLabelText("Open My Company"));
    await waitFor(() => expect(seen).toHaveBeenCalled());
    expect(calls.some(c => c.key === "POST /api/platform/companies/COMP-001/open")).toBe(true);
    expect(screen.queryByLabelText("Open Paused Ltd")).toBeNull();      // only active companies can be opened
    window.removeEventListener("velora:profile-changed", seen);
  });
});

describe("Developer mode switch", () => {
  it("turns developer mode on from the Desk", async () => {
    const calls = mockServer({ ...base({ configured: true, user: "velora_root" }), "GET /api/platform/developer-mode": () => ({ enabled: false }), "PUT /api/platform/developer-mode": ({ body }: any) => ({ enabled: body.enabled }) });
    render(<PlatformCompanies />);
    const box = (await screen.findByLabelText("Developer mode")) as HTMLInputElement;
    await waitFor(() => expect(box.disabled).toBe(false));
    fireEvent.click(box);
    expect(await screen.findByText("Developer mode is on.")).toBeTruthy();
    expect(calls.find(c => c.key === "PUT /api/platform/developer-mode")!.body).toEqual({ enabled: true });
  });

  it("duplicates with tick-box setup sections instead of typed DocType names", async () => {
    const calls = mockServer({ ...base({ configured: true, user: "postgres" }),
      "GET /api/platform/companies/COMP-001/copy-setup/sections": () => [{ id: "chart_of_accounts", label: "Chart of accounts" }, { id: "hr_masters", label: "HR masters" }],
      "POST /api/platform/companies/COMP-001/duplicate": () => ({ company: { id: "COMP-009" }, copied: [], settings_copied: [], sections: ["chart_of_accounts"] }) });
    render(<PlatformCompanies />);
    const boxes = await screen.findAllByLabelText("Chart of accounts");
    fireEvent.click(boxes[0]);
    fireEvent.change(screen.getByPlaceholderText("Copied company name"), { target: { value: "Copy Ltd" } });
    fireEvent.click(screen.getByRole("button", { name: "Duplicate company" }));
    await waitFor(() => expect(calls.some(c => c.key === "POST /api/platform/companies/COMP-001/duplicate")).toBe(true));
    const body = calls.find(c => c.key === "POST /api/platform/companies/COMP-001/duplicate")!.body;
    expect(body.sections).toEqual(["chart_of_accounts"]);
    expect(body.doctypes).toEqual([]);
  });

  it("grant access no longer pre-fills System Manager for every company", async () => {
    mockServer({ ...base({ configured: true, user: "postgres" }), "GET /api/platform/users": () => [{ email: "a@x.com", full_name: "A", is_active: true, is_platform_admin: false }] });
    render(<PlatformCompanies />);
    const input = await screen.findByLabelText("Roles for My Company");
    expect((input as HTMLInputElement).value).toBe("");
  });
});
