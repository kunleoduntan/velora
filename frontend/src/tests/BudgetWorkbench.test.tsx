import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import BudgetWorkbench from "../components/BudgetWorkbench";
import * as apiMod from "../api";

const zero = Object.fromEntries(apiMod.MONTHS.map(m => [m, 0]));
const wb = {
  budget: { name: "FB-1", budget_name: "Opex 2026", financial_year: "FY-2026", budget_type: "Operational", budget_against: "Whole Company", is_group_budget: false, approval_status: "Pending", budget_status: "Draft", docstatus: 0, currency: "NGN" },
  year: { start: "2026-01-01", end: "2026-12-31", months: {} }, through_month: 2,
  plan: [{ account: "5000", jan: 100, feb: 200, total: 300, previous_year_actual: 250 }],
  month_totals: { ...zero, jan: 100, feb: 200 }, actual_months: { ...zero, jan: 120, feb: 150 }, total: 300,
  variance: [{ account: "5000", annual_budget: 300, budget_to_date: 300, actual_to_date: 270, variance: 30, variance_percent: 10, utilisation_percent: 90, better_when: "lower", projected_year_end: 1620 }],
  allocation: [], allocation_dimension: null,
  scenarios: [{ scenario_name: "Tight", scenario_type: "Worst Case", adjustment_percent: -10, probability: 100, is_active: true, total_budget: 270, variance_from_base: -30, variance_percent: -10, expected_total: 270 }],
  scenario_months: [], children: [], children_total: 0,
};

describe("BudgetWorkbench", () => {
  beforeEach(() => {
    vi.spyOn(apiMod.api, "list").mockResolvedValue([{ name: "FB-1", budget_name: "Opex 2026", financial_year: "FY-2026", total_budget_amount: 300, approval_status: "Pending" }] as never);
    vi.spyOn(apiMod.budgetPlanner, "workbench").mockResolvedValue(wb as never);
  });
  it("lists budgets when none is open", async () => {
    render(<BudgetWorkbench />);
    expect(await screen.findByText("Opex 2026")).toBeTruthy();
  });
  it("shows the plan, totals the grid as it is edited and saves only the plan rows", async () => {
    const update = vi.spyOn(apiMod.api, "update").mockResolvedValue({} as never);
    render(<BudgetWorkbench name="FB-1" />);
    const jan = (await screen.findByLabelText("Jan row 1")) as HTMLInputElement;
    expect(jan.value).toBe("100");
    fireEvent.change(jan, { target: { value: "150" } });
    expect(screen.getAllByText("350.00").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Save plan"));
    await waitFor(() => expect(update).toHaveBeenCalled());
    const [dt, name, body] = update.mock.calls[0] as [string, string, { account_budgets: Record<string, unknown>[] }];
    expect(dt).toBe("Financial Budget"); expect(name).toBe("FB-1");
    expect(body.account_budgets[0]).toMatchObject({ account: "5000", jan: 150, feb: 200 });
    expect(body.account_budgets[0]).not.toHaveProperty("total");
  });
  it("projects the chosen rows from last year", async () => {
    const project = vi.spyOn(apiMod.budgetPlanner, "project").mockResolvedValue({ rows: [{ account: "5000", jan: 500, feb: 600 }] } as never);
    render(<BudgetWorkbench name="FB-1" />);
    await screen.findByLabelText("Jan row 1");
    fireEvent.click(screen.getByText("Project all rows"));
    await waitFor(() => expect(project).toHaveBeenCalledWith("FY-2026", expect.any(Array), "Historical Pattern", 0));
    await waitFor(() => expect((screen.getByLabelText("Jan row 1") as HTMLInputElement).value).toBe("500"));
  });
  it("makes the plan read-only once approved", async () => {
    vi.spyOn(apiMod.budgetPlanner, "workbench").mockResolvedValue({ ...wb, budget: { ...wb.budget, approval_status: "Approved", docstatus: 1 } } as never);
    render(<BudgetWorkbench name="FB-1" />);
    const jan = (await screen.findByLabelText("Jan row 1")) as HTMLInputElement;
    expect(jan.disabled).toBe(true);
    expect(screen.queryByText("Save plan")).toBeNull();
  });
  it("shows variance and scenarios", async () => {
    render(<BudgetWorkbench name="FB-1" />);
    await screen.findByLabelText("Jan row 1");
    fireEvent.click(screen.getByText("Budget vs actual"));
    expect((await screen.findAllByText("90.0%")).length).toBeGreaterThan(1);
    fireEvent.click(screen.getByText("Scenarios"));
    expect(await screen.findByText("Tight")).toBeTruthy();
  });
});
