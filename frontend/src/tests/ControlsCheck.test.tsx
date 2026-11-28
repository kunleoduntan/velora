import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import ControlsCheck from "../components/ControlsCheck";
import * as apiMod from "../api";

const result = {
  from_date: "2026-01-01", to_date: "2026-11-18", scope: "Both", stale_days: 90,
  summary: { checks: 3, with_findings: 2, errors: 1, warnings: 1 },
  findings: [
    { code: "AR-DUP", scope: "Receivables", severity: "Warning", title: "Possible duplicate sales invoices", why: "Same party and amount.", count: 1, amount: 1000, truncated: false, rows: [{ party: "C001", first: "SI-1", second: "SI-2", amount: 1000 }] },
    { code: "CX-CUSTOMER-TIEOUT", scope: "Control accounts", severity: "Error", title: "Customer control account does not agree to party balances", why: "They should be equal.", count: 1, amount: 250, truncated: false, rows: [{ account: "1100", difference: 250 }] },
    { code: "AP-DUP", scope: "Payables", severity: "Warning", title: "Possible duplicate supplier bills", why: "", count: 0, amount: 0, truncated: false, rows: [] },
  ],
};

describe("ControlsCheck", () => {
  it("runs with the chosen filters, puts errors first and opens them", async () => {
    const run = vi.spyOn(apiMod.controlsCheck, "run").mockResolvedValue(result as never);
    render(<ControlsCheck />);
    fireEvent.change(screen.getByLabelText("Old balance after (days)"), { target: { value: "60" } });
    fireEvent.click(screen.getByText("Run check"));
    await waitFor(() => expect(run).toHaveBeenCalledWith(expect.stringMatching(/^\d{4}-01-01$/), expect.any(String), "Both", 60));
    const titles = (await screen.findAllByRole("button", { expanded: undefined })).map(b => b.textContent ?? "").filter(t => /duplicate|control account/i.test(t));
    expect(titles[0]).toContain("control account");
    expect(await screen.findByText("They should be equal.")).toBeTruthy();                       // the error opens by itself
    expect(screen.queryByText("Same party and amount.")).toBeNull();                              // the warning stays closed until clicked
    fireEvent.click(screen.getByText("Possible duplicate sales invoices"));
    expect(await screen.findByText("Same party and amount.")).toBeTruthy();
    expect(screen.getByText("All clear")).toBeTruthy();
  });
  it("shows the server's message when the check cannot run", async () => {
    vi.spyOn(apiMod.controlsCheck, "run").mockRejectedValue(new Error("From date cannot be after To date."));
    render(<ControlsCheck />);
    fireEvent.click(screen.getByText("Run check"));
    expect((await screen.findByRole("alert")).textContent).toContain("From date cannot be after To date.");
  });
});
