import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import TaxCentre from "../components/TaxCentre";
import * as apiMod from "../api";

beforeEach(() => { vi.restoreAllMocks(); });

describe("Tax Centre", () => {
  it("shows the position, the adviser's findings and shortcuts to documents and reports", async () => {
    vi.spyOn(apiMod.api, "taxDashboard").mockResolvedValue({ vat_output: "75", vat_input: "120", vat_net: "-45", wht_payable: "200", wht_credit: "50", open_obligations: 2, overdue_obligations: 1,
      next_due: null, findings: { critical: 1, warning: 1, info: 0 }, months: [{ month: "2026-11", output: 75, input: 120 }] });
    vi.spyOn(apiMod.api, "taxAdviser").mockResolvedValue({ findings: [
      { severity: "critical", area: "Compliance", title: "VAT return overdue", detail: "Due 2026-10-21", route: "Tax Obligation" },
      { severity: "warning", area: "WHT", title: "2 customer withholding tax row(s) without a certificate", detail: "Obtain it.", route: "WHT Register" }] });
    render(<TaxCentre />);
    await waitFor(() => expect(screen.getByText("VAT return overdue")).toBeTruthy());
    expect(screen.getByText("Withholding tax payable")).toBeTruthy();
    expect(screen.getByText("1 overdue")).toBeTruthy();
    expect(screen.getByText("Tax Journal (withholding tax)").getAttribute("href")).toBe("#/app/Tax%20Journal");
    expect(screen.getByText("WHT Register", { selector: "a.btn" }).getAttribute("href")).toBe("#/report/WHT%20Register");
    const open = screen.getAllByText("Open");
    expect(open[1].getAttribute("href")).toBe("#/report/WHT%20Register");
  });

  it("lists only the reports that run, opening library reports with the report chosen", async () => {
    vi.spyOn(apiMod.api, "taxDashboard").mockResolvedValue({ vat_output: "0", vat_input: "0", vat_net: "0", wht_payable: "0", wht_credit: "0", open_obligations: 0, overdue_obligations: 0, next_due: null, findings: { critical: 0, warning: 0, info: 0 }, months: [] });
    vi.spyOn(apiMod.api, "taxAdviser").mockResolvedValue({ findings: [] });
    vi.spyOn(apiMod.api, "taxCatalogue").mockResolvedValue({ total: 2, executable: 2, domains: [{ domain: "VAT & GST", reports: 2, executable: 2 }], reports: [
      { id: "a", domain: "VAT & GST", report_name: "VAT by Tax Rate", status: "Tax Report Library" }, { id: "b", domain: "VAT & GST", report_name: "VAT Transaction Register", status: "Tax Ledger" },
] });
    render(<TaxCentre />);
    await waitFor(() => expect(screen.getByText("VAT by Tax Rate")).toBeTruthy());
    expect(screen.getByText("VAT by Tax Rate").getAttribute("href")).toBe("#/report/Tax Report Library?report=VAT%20by%20Tax%20Rate");
    expect(screen.getByText("VAT Transaction Register").getAttribute("href")).toBe("#/report/Tax%20Ledger");
    expect(screen.getByText(/2 tax reports run on your books/)).toBeTruthy();
  });
});
