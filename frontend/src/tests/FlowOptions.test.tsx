import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FlowOptionsDialog, { FLOW_OPTIONS } from "../components/FlowOptionsDialog";
import SettlementDialog from "../components/SettlementDialog";

describe("Create From options", () => {
  it("asks for the account and warehouse when invoicing a quotation or purchase order directly", () => {
    expect(Object.keys(FLOW_OPTIONS).sort()).toEqual(["Material Request:Purchase Order", "Material Request:Request for Quotation", "Purchase Order:Purchase Invoice", "Request for Quotation:Supplier Quotation", "Sales Quotation:Sales Invoice"]);
    const onConfirm = vi.fn();
    render(<FlowOptionsDialog title="Create Sales Invoice" options={FLOW_OPTIONS["Sales Quotation:Sales Invoice"]} onCancel={() => {}} onConfirm={onConfirm} />);
    expect(screen.getByLabelText("Revenue Account")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Create Sales Invoice" }));
    expect(onConfirm).toHaveBeenCalledWith({});
  });
  it("titles the settlement dialog after the button and caps the amount at the outstanding balance", () => {
    render(<SettlementDialog kind="Receipt" title="Receive Advance" invoiceTotal={700} onCancel={() => {}} onConfirm={() => {}} />);
    expect(screen.getByRole("dialog", { name: "Receive Advance" })).toBeTruthy();
    expect(screen.getByText(/maximum 700/)).toBeTruthy();
  });
});
