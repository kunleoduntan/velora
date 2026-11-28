import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, clearCaches, errorMessage, setAuthMode, setProfile, setSession } from "../api";
import FormView from "../components/FormView";
import WarningToasts from "../components/WarningToasts";
import { resetScripts } from "../clientScripts";
import so from "./fixtures/sales_order.meta.json";
import { mockServer } from "./helpers";

beforeEach(() => { clearCaches(); resetScripts(); sessionStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "sam", roles: "Sales User" }); window.location.hash = ""; });

describe("errors that help", () => {
  it("every screen's error text carries the hint", () => {
    const e = new ApiError(417, "ValidationError", "Period P1 is closed.", { hint: "Post in the current period." });
    expect(errorMessage(e)).toBe("Period P1 is closed. How to fix it: Post in the current period.");
    expect(errorMessage(new ApiError(417, "ValidationError", "Plain."))).toBe("Plain.");
  });

  it("a missing field is advised before anything is sent", async () => {
    mockServer({ "GET /api/meta/Sales Order": () => so });
    render(<FormView doctype="Sales Order" name="new" />);
    await screen.findByRole("heading", { name: "New Sales Order" });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const box = await screen.findByRole("alert");
    expect(box.textContent).toContain("Missing required");
    expect(box.textContent).toContain("How to fix it: The fields marked in red");
    expect(screen.getByRole("button", { name: "Go to the field" })).toBeTruthy();
  });

  it("a server refusal shows the hint and the buttons that fix it", async () => {
    const DOC = { doctype: "Sales Order", name: "SO-0001", docstatus: 0, customer: "Acme Ltd", order_date: "2026-03-02", total: 200, items: [{ name: "r1", description: "Widget", qty: 2, rate: 100 }] };
    mockServer({
      "GET /api/meta/Sales Order": () => so,
      "GET /api/resource/Sales Order/SO-0001": () => DOC,
      "PUT /api/resource/Sales Order/SO-0001": () => new Response(JSON.stringify({ error: "ValidationError", message: "Finance Settings have not been configured.",
        advice: { hint: "Complete them once.", actions: [{ label: "Open Finance Settings", href: "#/app/Finance%20Settings" }] } }), { status: 417 }),
    });
    render(<FormView doctype="Sales Order" name="SO-0001" />);
    await screen.findByRole("heading", { name: /SO-0001/ });
    fireEvent.change(screen.getByLabelText(/^Order Date/), { target: { value: "2026-03-03" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const box = await screen.findByRole("alert");
    expect(box.textContent).toContain("Finance Settings have not been configured.");
    expect(box.textContent).toContain("How to fix it: Complete them once.");
    expect(screen.getByRole("link", { name: "Open Finance Settings" }).getAttribute("href")).toBe("#/app/Finance%20Settings");
  });

  it("warnings arrive as notes that do not block anything", async () => {
    render(<WarningToasts />);
    window.dispatchEvent(new CustomEvent("velora:warnings", { detail: [{ message: "Rate is 30 days old.", hint: "Update it soon.", actions: [{ label: "Rates", href: "#/app/Currency%20Exchange%20Rate" }] }] }));
    expect(await screen.findByText(/Rate is 30 days old/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Rates" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.queryByText(/Rate is 30 days old/)).toBeNull());
  });
});
