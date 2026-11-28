import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setSession } from "../api";
import CancelDialog from "../components/CancelDialog";
import { mockServer } from "./helpers";

beforeEach(() => { setSession({ user: "fin", roles: "Finance Manager" }); });

describe("Cancel dialog", () => {
  it("asks for a reason and cancels a document nothing depends on", async () => {
    const onDone = vi.fn();
    const calls = mockServer({
      "GET /api/linked-documents/Sales Invoice/SI-1": () => ({ doctype: "Sales Invoice", name: "SI-1", dependents: [] }),
      "POST /api/resource/Sales Invoice/SI-1/cancel": () => ({ name: "SI-1", docstatus: 2 }),
    });
    render(<CancelDialog doctype="Sales Invoice" name="SI-1" onDone={onDone} onClose={() => {}} />);
    const go = await screen.findByRole("button", { name: "Cancel Document" });
    fireEvent.click(go);
    expect((await screen.findByRole("alert")).textContent).toMatch(/reason is required/);
    fireEvent.change(screen.getByLabelText("Reason for cancelling"), { target: { value: "Wrong customer" } });
    fireEvent.click(go);
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(calls.find((c) => c.key === "POST /api/resource/Sales Invoice/SI-1/cancel")?.body).toEqual({ reason: "Wrong customer" });
  });

  it("lists the documents that depend on it and offers Cancel All", async () => {
    const onDone = vi.fn();
    const calls = mockServer({
      "GET /api/linked-documents/Sales Order/SO-1": () => ({ doctype: "Sales Order", name: "SO-1", dependents: [{ doctype: "Delivery Note", name: "DN-1" }, { doctype: "Sales Invoice", name: "SI-9" }] }),
      "POST /api/cancel-all/Sales Order/SO-1": () => ({ cancelled: [] }),
    });
    render(<CancelDialog doctype="Sales Order" name="SO-1" onDone={onDone} onClose={() => {}} />);
    expect(await screen.findByText("DN-1")).toBeTruthy();
    expect(screen.getByText("SI-9")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Reason for cancelling"), { target: { value: "Customer withdrew" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel All (3 documents)" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(calls.some((c) => c.key === "POST /api/cancel-all/Sales Order/SO-1" && (c.body as { reason: string }).reason === "Customer withdrew")).toBe(true);
  });

  it("shows the server's reason when the cancel is refused and stays open", async () => {
    const onDone = vi.fn();
    mockServer({
      "GET /api/linked-documents/Receipt/R-1": () => ({ doctype: "Receipt", name: "R-1", dependents: [] }),
      "POST /api/resource/Receipt/R-1/cancel": () => new Response(JSON.stringify({ error: "ValidationError", message: "Financial Period P1 is closed" }), { status: 422 }),
    });
    render(<CancelDialog doctype="Receipt" name="R-1" onDone={onDone} onClose={() => {}} />);
    fireEvent.change(await screen.findByLabelText("Reason for cancelling"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel Document" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/is closed/);
    expect(onDone).not.toHaveBeenCalled();
  });
});
