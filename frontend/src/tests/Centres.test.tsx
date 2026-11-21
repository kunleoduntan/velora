import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import InvestmentPortfolio from "../components/InvestmentPortfolio";
import SupportDesk from "../components/SupportDesk";
import BroadcastCentre from "../components/BroadcastCentre";
import GlReview from "../components/GlReview";
import ShortcutHub from "../components/ShortcutHub";
import * as apiMod from "../api";
import { getPins, recordVisit, getRecents, search, CENTRES } from "../shortcuts";

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

const portfolio = {
  as_of: "2026-11-18", currency_note: "Amounts are in NGN.",
  kpis: { carrying: 1500000, cost: 1400000, unrealised: 100000, accrued_receivable: 25000, income_ytd: 90000, tax_withheld_ytd: 9000, weighted_yield: 14.5, holdings: 2 },
  by_group: [{ label: "Money Market", amount: 1000000, percent: 66.7, over_limit: false }, { label: "Equities", amount: 500000, percent: 33.3, over_limit: false }],
  by_class: [{ label: "Fixed Deposit", amount: 1000000, percent: 66.7 }], by_counterparty: [{ label: "First Bank", amount: 1000000, percent: 66.7, over_limit: true }],
  ladder: [{ label: "0 to 30 days", amount: 1000000, count: 1 }], upcoming: [{ date: "2026-12-01", event: "Maturity", investment: "INV-1", name: "FD One", amount: 1000000 }],
  holdings: [{ name: "INV-1", investment_name: "FD One", investment_class: "Fixed Deposit", counterparty: "First Bank", carrying_amount: 1000000, effective_yield: 15, maturity_date: "2026-12-01", days_to_maturity: 13, accrued_receivable: 25000, measurement: "Amortised cost" }],
  alerts: [{ kind: "concentration", severity: "warning", message: "First Bank holds 66.7% of the portfolio (limit 25%)." }], limits: { counterparty_percent: 25, asset_group_percent: 70 },
};

describe("InvestmentPortfolio", () => {
  it("shows the book, alerts and flags concentration, and accrues income", async () => {
    vi.spyOn(apiMod.investments, "portfolio").mockResolvedValue(portfolio as never);
    const accrue = vi.spyOn(apiMod.investments, "accrueAll").mockResolvedValue({ made: ["INVT-1"], failed: [] });
    render(<InvestmentPortfolio />);
    expect(await screen.findByText("1,500,000")).toBeTruthy();
    expect(screen.getByText(/holds 66.7% of the portfolio/)).toBeTruthy();
    expect(screen.getByText("over limit")).toBeTruthy();
    expect(screen.getAllByText("FD One", { selector: "a" })[0].getAttribute("href")).toBe("#/app/Investment/INV-1");
    fireEvent.click(screen.getByText("Accrue income to this date"));
    await waitFor(() => expect(accrue).toHaveBeenCalled());
    expect(await screen.findByText("Income recognised in 1 transaction.")).toBeTruthy();
  });
  it("shows the server's message when loading fails", async () => {
    vi.spyOn(apiMod.investments, "portfolio").mockRejectedValue(new Error("Permission denied"));
    render(<InvestmentPortfolio />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});

const row = (o: object) => ({ name: "TKT-1", subject: "Cannot log in", status: "Open", priority: "High", category: null, customer: "C1", assigned_to: "a@x.com", team: "T", response_sla: "On track", resolution_sla: "On track", resolution_due: "2026-11-19T10:00:00", first_response_due: "2026-11-18T12:00:00", escalation_level: 0, age_hours: 3, ...o });
describe("SupportDesk", () => {
  it("lists the queue and filters to breached/at-risk and unassigned", async () => {
    vi.spyOn(apiMod.support, "summary").mockResolvedValue({
      kpis: { open: 2, unassigned: 1, mine: 0, at_risk: 0, breached: 1, waiting: 0, resolved_today: 3, avg_first_response_hours: 1.5, avg_resolution_hours: 60, sla_met_percent: 80, satisfaction: 4.5 },
      queue: [row({ name: "TKT-2", subject: "Printer down", response_sla: "Breached", escalation_level: 1 }), row({ name: "TKT-3", subject: "Invoice query", assigned_to: null })],
      workload: [{ agent: "a@x.com", open: 1, breached: 1 }], ageing: [{ bucket: "Under 1 day", count: 2 }], trend: [{ date: "2026-11-18", opened: 2, resolved: 1 }], categories: [],
    } as never);
    render(<SupportDesk />);
    expect(await screen.findByText("Printer down")).toBeTruthy();
    expect(screen.getByText("2.5d")).toBeTruthy();                                            // 60 hours reads as days
    fireEvent.click(screen.getByText("Unassigned", { selector: "button" }));
    expect(screen.queryByText("Printer down")).toBeNull();
    expect(screen.getByText("Invoice query")).toBeTruthy();
    fireEvent.click(screen.getByText("Breached or at risk"));
    expect(screen.getByText("Printer down")).toBeTruthy();
    expect(screen.queryByText("Invoice query")).toBeNull();
  });
});

describe("BroadcastCentre", () => {
  it("shows channel readiness and reports a gateway test result", async () => {
    vi.spyOn(apiMod.broadcasts, "summary").mockResolvedValue({
      recent: [{ name: "BC-1", title: "Festive", channel: "Email", status: "Partly Sent", total_recipients: 10, sent_count: 8, failed_count: 2, opted_out_count: 0, scheduled_for: null, started_on: "2026-11-01T09:00:00" }],
      scheduled: [], running: [], by_channel: { Email: { broadcasts: 1, sent: 8, failed: 2 }, SMS: { broadcasts: 0, sent: 0, failed: 0 }, WhatsApp: { broadcasts: 0, sent: 0, failed: 0 } },
      opt_outs: 4, gateways: { Email: true, SMS: false, WhatsApp: false, base_url: false }, outbox: { Queued: 3, Dead: 1 },
    } as never);
    const t = vi.spyOn(apiMod.broadcasts, "testGateway").mockResolvedValue({ sent: false, error: "SMS is not set up" });
    render(<BroadcastCentre />);
    expect(await screen.findByText("Festive")).toBeTruthy();
    expect(screen.getAllByText("Not set up").length).toBe(2);
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "SMS" } });
    fireEvent.change(screen.getByLabelText("Send a test to"), { target: { value: "08031234567" } });
    fireEvent.click(screen.getByText("Send test"));
    await waitFor(() => expect(t).toHaveBeenCalledWith("SMS", "08031234567"));
    expect(await screen.findByText("Could not send: SMS is not set up")).toBeTruthy();
  });
});

describe("GlReview", () => {
  it("runs with the chosen thresholds and shows the reasons", async () => {
    const run = vi.spyOn(apiMod.glReview, "run").mockResolvedValue({
      period: { from: "a", to: "b", prior_from: "c", prior_to: "d", threshold_percent: 40, minimum_amount: 5000 },
      summary: { accounts_current: 5, accounts_prior: 4, flagged: 1, suspense_lines: 0, journals_flagged: 0, months_clustered: 0 },
      flagged_accounts: [{ account: "Rent", code: "5100", name: "Rent", root_type: "Expense", current: 400000, prior: 100000, change: 300000, change_percent: 300, reasons: ["300.0% increase on the earlier period"] }],
      top_movements: [], suspense: [], period_end: [], journals: [],
    } as never);
    render(<GlReview />);
    fireEvent.change(screen.getByLabelText("Change of at least (%)"), { target: { value: "40" } });
    fireEvent.click(screen.getByText("Run review"));
    await waitFor(() => expect(run).toHaveBeenCalledWith(expect.any(String), expect.any(String), expect.any(String), expect.any(String), 40, 10000));
    expect(await screen.findByText("300.0% increase on the earlier period")).toBeTruthy();
  });
});

describe("Shortcut Hub", () => {
  const types = [{ name: "Customer", module: "Selling", app: "x", is_submittable: false, can_create: true }, { name: "Leave Application", module: "HR", app: "x", is_submittable: true, can_create: false }];
  it("searches records and centres, offers + only where creating is allowed, and pins", () => {
    render(<ShortcutHub types={types} />);
    fireEvent.change(screen.getByLabelText("Search shortcuts"), { target: { value: "leave" } });
    expect(screen.getByText("Leave Application")).toBeTruthy();
    expect(screen.getByText("Leave Management Centre")).toBeTruthy();                           // matched by name
    expect(screen.queryByTitle("New Leave Application")).toBeNull();
    fireEvent.change(screen.getByLabelText("Search shortcuts"), { target: { value: "tickets" } });
    expect(screen.getByText("Support Desk")).toBeTruthy();                                       // matched by keyword
    fireEvent.click(screen.getByLabelText("Pin Support Desk"));
    expect(getPins()).toEqual(["#/support"]);
    fireEvent.change(screen.getByLabelText("Search shortcuts"), { target: { value: "zzzz" } });
    expect(screen.getByText(/Nothing matches/)).toBeTruthy();
  });
  it("keeps recent places without repeats and never remembers the hub", () => {
    recordVisit("#/app/Customer/C1"); recordVisit("#/investments"); recordVisit("#/shortcuts"); recordVisit("#/app/Customer/C1?x=1");
    expect(getRecents()).toEqual(["#/app/Customer/C1", "#/investments"]);
    expect(search(CENTRES, "isa 520").map(s => s.label)).toEqual(["General Ledger Review"]);
  });
});
