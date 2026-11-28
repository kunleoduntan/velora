import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import TreasuryCentre from "../components/TreasuryCentre";
import * as apiMod from "../api";

beforeEach(() => { vi.restoreAllMocks(); });

const dash = (over: any = {}) => ({ base_currency: "NGN", total_debt: "5000000", net_debt: "1000000", cash: "4000000", weighted_rate: "20", floating_share: "0", undrawn: "5000000", facilities: 1, loans: 1,
  debt_service_30: "500000", debt_service_90: "1500000", overdue_amount: "0", overdue_loans: 0, accrued_unpaid: "84931.51", rate_shock_cost: "0", rate_shock_points: "2", covenants: { Breach: 1 }, tests_overdue: 0,
  lenders: [{ lender: "First Bank", amount: "5000000", percent: "100" }], ladder: [{ bucket: "Next 30 days", principal: "400000" }], facility_usage: [{ name: "Term loan A", limit: "10000000", outstanding: "5000000", percent: "50", currency: "NGN", expires: "2027-09-01" }],
  findings: [{ severity: "critical", area: "Covenants", title: "Term loan A: Debt service cover breached", detail: "Seek a waiver.", route: "Covenant Test" }], finding_counts: { critical: 1, warning: 0, info: 0 }, ...over });

describe("Treasury Centre", () => {
  it("shows the debt position, the adviser's findings, headroom, covenants and shortcuts", async () => {
    vi.spyOn(apiMod.api, "treasuryDashboard").mockResolvedValue(dash());
    vi.spyOn(apiMod.api, "treasuryLiquidity").mockResolvedValue({ opening: "4000000", assumption: "Receivables are assumed collected on their due date.", rows: [{ week: 1, closing: "3500000", short: false, below_buffer: false }] });
    vi.spyOn(apiMod.api, "treasuryFx").mockResolvedValue({ rows: [] });
    render(<TreasuryCentre />);
    await waitFor(() => expect(screen.getByText("Term loan A: Debt service cover breached")).toBeTruthy());
    expect(screen.getByText("Total debt (NGN)")).toBeTruthy();
    expect(screen.getByText("Facility headroom")).toBeTruthy();
    expect(screen.getByText("Open").getAttribute("href")).toBe("#/app/Covenant%20Test");
    expect(screen.getByText("Debt Maturity Ladder", { selector: "a.btn" }).getAttribute("href")).toBe("#/report/Debt%20Maturity%20Ladder");
    expect(screen.getByText("Breach", { selector: "small" })).toBeTruthy();
  });

  it("says plainly when nothing needs attention", async () => {
    vi.spyOn(apiMod.api, "treasuryDashboard").mockResolvedValue(dash({ findings: [], finding_counts: { critical: 0, warning: 0, info: 0 }, covenants: {}, ladder: [], facility_usage: [], lenders: [] }));
    vi.spyOn(apiMod.api, "treasuryLiquidity").mockResolvedValue({ opening: "0", rows: [] });
    vi.spyOn(apiMod.api, "treasuryFx").mockResolvedValue({ rows: [] });
    render(<TreasuryCentre />);
    await waitFor(() => expect(screen.getByText("Nothing needs attention.")).toBeTruthy());
  });
});
