import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import BankReconciliationCentre from "../components/BankReconciliationCentre";
import * as apiMod from "../api";

const wb = {
  bank_account: "MAIN", gl_account: "1000", currency: "NGN", ledger_balance: "1000", matched_total: 0,
  settings: { auto_accept_threshold: 90, date_tolerance_days: 4, auto_reconcile: true, auto_post_coded: false },
  unmatched_lines: [{ id: "L1", date: "2026-03-01", direction: "Receipt", amount: "600", description: "Lodgement", status: "Unmatched" }],
  ignored_lines: [],
  unmatched_records: [{ id: "R1", date: "2026-03-01", signed: "250" }, { id: "R2", date: "2026-03-01", signed: "350" }],
  suggestions: [{ group: "G1", method: "Scored", confidence: 72, reason: "close", status: "Suggested", locked: false, lines: [], records: [] }], matched: [],
};

describe("BankReconciliationCentre", () => {
  beforeEach(() => {
    vi.spyOn(apiMod.api, "list").mockResolvedValue([{ name: "MAIN" }] as never);
    vi.spyOn(apiMod.bankRec, "workbench").mockResolvedValue(wb as never);
  });
  it("loads the only account, shows review suggestions and accepts one", async () => {
    const confirm = vi.spyOn(apiMod.bankRec, "confirm").mockResolvedValue({ confirmed: 1 });
    render(<BankReconciliationCentre />);
    await screen.findByText("Scored");
    fireEvent.click(screen.getByText("Accept"));
    await waitFor(() => expect(confirm).toHaveBeenCalledWith(["G1"]));
  });
  it("only enables Match selected when the statement and ledger selections agree", async () => {
    const match = vi.spyOn(apiMod.bankRec, "match").mockResolvedValue({} as never);
    render(<BankReconciliationCentre />);
    await screen.findByText("Scored");
    fireEvent.click(screen.getByText("Unmatched"));
    const boxes = await screen.findAllByRole("checkbox");
    const btn = screen.getByText("Match selected") as HTMLButtonElement;
    fireEvent.click(boxes[0]); fireEvent.click(boxes[1]);
    expect(btn.disabled).toBe(true);
    fireEvent.click(boxes[2]);
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    await waitFor(() => expect(match).toHaveBeenCalledWith("MAIN", ["L1"], ["R1", "R2"]));
  });
});
