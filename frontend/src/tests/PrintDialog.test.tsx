import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PrintDialog, { printUrl } from "../components/PrintDialog";

const ok = (data: unknown) => Promise.resolve(new Response(JSON.stringify({ data }), { status: 200, headers: { "Content-Type": "application/json" } }));
let opened: string[] = [];
beforeEach(() => {
  opened = [];
  vi.stubGlobal("fetch", vi.fn(() => ok([{ id: "pf-1", name: "Waybill (company style)" }, { id: "standard", name: "Standard page", builtin: true }])));
  vi.stubGlobal("open", (u: string) => { opened.push(u); return null; });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("PrintDialog", () => {
  it("builds one-document and batch addresses, with and without PDF", () => {
    expect(printUrl("pf-1", "Waybill", ["WB-1"])).toBe("/api/print/pf-1/Waybill/WB-1");
    expect(printUrl("pf-1", "Waybill", ["WB-1"], true)).toBe("/api/print/pf-1/Waybill/WB-1/pdf");
    expect(printUrl("standard", "Sales Invoice", ["A", "B"])).toBe("/api/print-batch/standard/Sales%20Invoice?names=A%2CB");
    expect(printUrl("standard", "Sales Invoice", ["A", "B"], true)).toBe("/api/print-batch/standard/Sales%20Invoice/pdf?names=A%2CB");
  });
  it("offers the designed format first and prints the chosen one from the form", async () => {
    const onClose = vi.fn();
    render(<PrintDialog doctype="Waybill" names={["WB-1"]} onClose={onClose} />);
    expect(await screen.findByText(/Waybill \(company style\)/)).toBeTruthy();
    expect(screen.getByText(/Standard page \(built-in\)/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    expect(opened).toEqual(["/api/print/pf-1/Waybill/WB-1"]); expect(onClose).toHaveBeenCalled();
  });
  it("prints several documents from a list as one batch, as PDF when asked", async () => {
    render(<PrintDialog doctype="Waybill" names={["WB-1", "WB-2", "WB-3"]} onClose={() => {}} />);
    await screen.findByText(/Print 3 Waybill documents/);
    await waitFor(() => expect((screen.getByRole("button", { name: "PDF" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByLabelText(/Standard page/));
    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    expect(opened).toEqual(["/api/print-batch/standard/Waybill/pdf?names=WB-1%2CWB-2%2CWB-3"]);
  });
});
