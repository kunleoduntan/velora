import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setSession } from "../api";
import ApplyInvoicesDialog from "../components/ApplyInvoicesDialog";
import SettlementDialog from "../components/SettlementDialog";
import { mockServer } from "./helpers";

beforeEach(() => { setSession({ user: "sam", roles: "Accountant" }); });

const invoices = [
  { invoice: "SI-1", invoice_date: "2026-01-01", due_date: "2026-02-01", currency: "NGN", invoice_total: 300, amount_settled: 0, outstanding: 300, payment_status: "Unpaid" },
  { invoice: "SI-2", invoice_date: "2026-01-05", due_date: "2026-02-05", currency: "NGN", invoice_total: 500, amount_settled: 0, outstanding: 500, payment_status: "Unpaid" },
];

describe("Apply to Invoices dialog", () => {
  it("fetches outstanding invoices, auto-allocates, and returns the lines built by the server", async () => {
    const onApply = vi.fn();
    mockServer({
      "POST /api/settlement/outstanding": () => ({ invoices, methods: ["FIFO", "Best Match"] }),
      "POST /api/settlement/allocate": (req: { body?: Record<string, unknown> }) => req.body?.allocations
        ? { allocations: [], allocated: 500, unapplied: 0, method: "Manual", explanation: "", lines: [{ account: "1100", amount: 500, invoice_reference: "SI-2", allocation_amount: 500 }] }
        : { allocations: [{ ...invoices[1], allocate: 500 }], allocated: 500, unapplied: 0, method: "Best Match", explanation: "These 1 invoice(s) add up exactly to the amount.", lines: [] },
    });
    render(<ApplyInvoicesDialog kind="Receipt" partyType="Customer" initialParty="C001" initialAmount={500} onCancel={() => {}} onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "Get Outstanding Invoices" }));
    expect(await screen.findByText("SI-2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Auto Allocate" }));
    await waitFor(() => expect((screen.getByLabelText("Allocate to SI-2") as HTMLInputElement).value).toBe("500"));
    expect(screen.getByText(/add up exactly/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Apply to Invoices" }));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    expect(onApply.mock.calls[0][0][0].invoice_reference).toBe("SI-2");
  });

  it("never lets a row be allocated more than its outstanding balance", async () => {
    mockServer({ "POST /api/settlement/outstanding": () => ({ invoices, methods: ["FIFO"] }) });
    render(<ApplyInvoicesDialog kind="Receipt" partyType="Customer" initialParty="C001" initialAmount={900} onCancel={() => {}} onApply={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Get Outstanding Invoices" }));
    const input = (await screen.findByLabelText("Allocate to SI-1")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "999" } });
    expect(input.value).toBe("300");
  });
});

describe("Create Receipt/Payment dialog", () => {
  it("asks for a Bank Account and an amount within the invoice total", () => {
    const onConfirm = vi.fn();
    mockServer({ "GET /api/link/Bank Account": () => [] });
    render(<SettlementDialog kind="Payment" invoiceTotal={1000} onCancel={() => {}} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Create Payment" }));
    expect(screen.getByRole("alert").textContent).toMatch(/Bank Account/);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
