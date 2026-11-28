import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import PortalApp from "../portal/PortalApp";
import PortalAccess from "../components/PortalAccess";
import { portal } from "../portal/portalApi";
import * as apiMod from "../api";

const customer = { id: "1", email: "buyer@example.com", full_name: "Bola Buyer", roles: ["Customer Portal"] };
const overview = {
  who: { name: "Bola Buyer", email: "buyer@example.com" }, party: { code: "C001", customer_name: "Acme Ltd", payment_terms: "Net 30" },
  summary: { open_invoices: 2, overdue_invoices: 1, by_currency: [{ currency: "NGN", outstanding: 1500, overdue: 500, open_invoices: 2 }] },
  ageing: [{ currency: "NGN", total: 1500, buckets: [{ label: "Current", amount: 1000 }, { label: "1-30 days", amount: 500 }, { label: "31-60 days", amount: 0 }, { label: "61-90 days", amount: 0 }, { label: "Over 90 days", amount: 0 }] }],
  recent_invoices: [{ name: "SI-1", invoice_date: "2026-11-01", due_date: "2026-12-01", currency: "NGN", grand_total: 1000, amount_settled: 0, outstanding: 1000, overdue_days: 0, state: "Open" }], open_orders: 3, open_complaints: 1,
};

describe("Portal", () => {
  beforeEach(() => { location.hash = ""; });
  it("shows the sign-in form when nobody is signed in, and signs in", async () => {
    vi.spyOn(portal, "me").mockRejectedValue(new Error("no"));
    vi.spyOn(portal, "overview").mockResolvedValue(overview as never);
    const login = vi.spyOn(portal, "login").mockResolvedValue(customer);
    render(<PortalApp />);
    fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: "buyer@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a long secure passphrase" } });
    fireEvent.click(screen.getByText("Sign in"));
    await waitFor(() => expect(login).toHaveBeenCalledWith("buyer@example.com", "a long secure passphrase"));
    expect(await screen.findByText("Welcome, Bola Buyer")).toBeTruthy();
    expect(screen.getByText("1,500.00")).toBeTruthy();
  });
  it("shows a clear message for a wrong password", async () => {
    vi.spyOn(portal, "me").mockRejectedValue(new Error("no"));
    vi.spyOn(portal, "login").mockRejectedValue(new Error("Invalid portal email or password"));
    render(<PortalApp />);
    fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: "a@b.co" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "x" } });
    fireEvent.click(screen.getByText("Sign in"));
    expect((await screen.findByRole("alert")).textContent).toContain("Invalid portal email or password");
  });
  it("gives customers a Help page and suppliers none", async () => {
    vi.spyOn(portal, "me").mockResolvedValue(customer);
    vi.spyOn(portal, "overview").mockResolvedValue(overview as never);
    const { unmount } = render(<PortalApp />);
    expect(await screen.findByText("Help")).toBeTruthy();
    unmount();
    vi.spyOn(portal, "me").mockResolvedValue({ ...customer, roles: ["Supplier Portal"] });
    render(<PortalApp />);
    await screen.findByText("Overview");
    expect(screen.queryByText("Help")).toBeNull();
  });
  it("filters invoices by status through the server and raises a complaint", async () => {
    vi.spyOn(portal, "me").mockResolvedValue(customer);
    vi.spyOn(portal, "overview").mockResolvedValue(overview as never);
    const invoices = vi.spyOn(portal, "invoices").mockResolvedValue([]);
    vi.spyOn(portal, "complaints").mockResolvedValue([]);
    const raise = vi.spyOn(portal, "raiseComplaint").mockResolvedValue({ name: "CC-1" });
    render(<PortalApp />);
    fireEvent.click(await screen.findByText("Invoices"));
    fireEvent.click(await screen.findByText("Overdue"));
    await waitFor(() => expect(invoices).toHaveBeenCalledWith("customer", "overdue"));
    fireEvent.click(screen.getByText("Help"));
    fireEvent.change(await screen.findByLabelText("Describe the problem"), { target: { value: "Late again" } });
    fireEvent.click(screen.getByText("Send"));
    await waitFor(() => expect(raise).toHaveBeenCalledWith(expect.objectContaining({ category: "Service", description: "Late again", sales_invoice: undefined })));
    expect(await screen.findByText(/CC-1/)).toBeTruthy();
  });
  it("refuses a password change when the two new passwords differ", async () => {
    vi.spyOn(portal, "me").mockResolvedValue(customer);
    vi.spyOn(portal, "overview").mockResolvedValue(overview as never);
    const change = vi.spyOn(portal, "changePassword").mockResolvedValue({});
    vi.spyOn(portal, "preferences").mockResolvedValue({ email: "bola@example.com", email_opted_out: false } as never);
    render(<PortalApp />);
    fireEvent.click(await screen.findByText("My account"));
    fireEvent.change(await screen.findByLabelText("Current password"), { target: { value: "old password 1" } });
    fireEvent.change(screen.getByLabelText(/New password/), { target: { value: "new password 123" } });
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "different 123456" } });
    fireEvent.click(screen.getByText("Change password"));
    expect((await screen.findByRole("alert")).textContent).toContain("do not match");
    expect(change).not.toHaveBeenCalled();
  });
});

describe("PortalAccess (staff)", () => {
  it("shows the one-time password after an invitation", async () => {
    vi.spyOn(apiMod.portalAdmin, "accounts").mockResolvedValue([]);
    vi.spyOn(apiMod.api, "searchLink").mockResolvedValue([{ name: "C001", title: "", description: "" }] as never);
    const invite = vi.spyOn(apiMod.portalAdmin, "invite").mockResolvedValue({ email: "buyer@example.com", temporary_password: "Xk9-temporary" });
    render(<PortalAccess />);
    const party = await screen.findByLabelText("Customer");
    fireEvent.focus(party);
    fireEvent.change(party, { target: { value: "C001" } });
    fireEvent.mouseDown(await screen.findByText("C001"));                // a link must be picked from the list
    await waitFor(() => expect((screen.getByText("Create sign-in") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("Contact name"), { target: { value: "Bola" } });
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "buyer@example.com" } });
    fireEvent.click(screen.getByText("Create sign-in"));
    await waitFor(() => expect(invite).toHaveBeenCalledWith({ portal_type: "Customer", party: "C001", full_name: "Bola", email: "buyer@example.com" }));
    expect(await screen.findByText("Xk9-temporary")).toBeTruthy();
  });
  it("shows an employee their own pages and keeps customer tabs away", async () => {
    vi.spyOn(portal, "me").mockResolvedValue({ ...customer, roles: ["Employee Portal"] });
    vi.spyOn(portal, "employeeOverview").mockResolvedValue({ profile: { full_name: "Tunde BELLO", designation: "Accountant" }, leave_balance: 0, last_payslip: null, greeting: "Good day" } as never);
    vi.spyOn(portal, "celebrations").mockResolvedValue([]);
    vi.spyOn(portal, "payslips").mockResolvedValue([]);
    render(<PortalApp />);
    expect(await screen.findByText("Payslips")).toBeTruthy();
    expect(screen.queryByText("Invoices")).toBeNull();
    expect(screen.getByText("Messages")).toBeTruthy();
  });
  it("lists received messages", async () => {
    vi.spyOn(portal, "me").mockResolvedValue(customer);
    vi.spyOn(portal, "overview").mockResolvedValue(overview as never);
    vi.spyOn(portal, "messages").mockResolvedValue([{ name: "ENG-1", moment_date: "2026-12-25", kind: "Holiday", subject: "Merry Christmas", message: "Warm wishes" }] as never);
    render(<PortalApp />);
    fireEvent.click(await screen.findByText("Messages"));
    expect(await screen.findByText("Merry Christmas")).toBeTruthy();
  });

  it("lets a contact ask for a reset from the sign-in page", async () => {
    vi.spyOn(portal, "me").mockRejectedValue(new Error("no"));
    const fp = vi.spyOn(portal, "forgotPassword").mockResolvedValue({ message: "ok", mode: "staff" });
    render(<PortalApp />);
    fireEvent.click(await screen.findByText("Forgot your password?"));
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "buyer@example.com" } });
    fireEvent.click(screen.getByText("Reset my password"));
    await waitFor(() => expect(fp).toHaveBeenCalledWith("buyer@example.com"));
    expect(await screen.findByText("Request sent")).toBeTruthy();
  });
  it("completes a reset from the emailed link", async () => {
    vi.spyOn(portal, "me").mockRejectedValue(new Error("no"));
    const rp = vi.spyOn(portal, "resetPassword").mockResolvedValue({ reset: true });
    location.hash = "#/reset?token=abc123";
    render(<PortalApp />);
    fireEvent.change(await screen.findByLabelText("New password"), { target: { value: "Brave-Lion-4582-ok" } });
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "Brave-Lion-4582-ok" } });
    fireEvent.click(screen.getByText("Save new password"));
    await waitFor(() => expect(rp).toHaveBeenCalledWith("abc123", "Brave-Lion-4582-ok"));
    expect(await screen.findByText("Password changed")).toBeTruthy();
  });
  it("forces a new password after a temporary one", async () => {
    vi.spyOn(portal, "me").mockResolvedValue({ ...customer, must_change: true });
    render(<PortalApp />);
    expect(await screen.findByText("Choose your own password")).toBeTruthy();
    expect(screen.queryByText("Invoices")).toBeNull();
  });
});
