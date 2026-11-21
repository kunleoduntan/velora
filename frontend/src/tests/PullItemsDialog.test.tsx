import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PullItemsDialog from "../components/PullItemsDialog";
import { api } from "../api";

const rows = [
  { name: "PO-1", party: "S1", party_name: "Acme Supplies", date: "2026-11-01", currency: "NGN", open_lines: 2, open_quantity: "15" },
  { name: "PO-2", party: "S2", party_name: "Other Ltd", date: "2026-11-02", currency: "NGN", open_lines: 1, open_quantity: "4" },
  { name: "PO-3", party: "S1", party_name: "Acme Supplies", date: "2026-11-03", currency: "NGN", open_lines: 1, open_quantity: "6" },
];

beforeEach(() => { vi.restoreAllMocks(); vi.spyOn(api, "pullCandidates").mockResolvedValue(rows); });

describe("PullItemsDialog (Get Items From)", () => {
  it("merges several orders of one supplier and refuses to mix in another supplier", async () => {
    const lines = vi.spyOn(api, "pullLines").mockResolvedValue({ header: { party: "S1" }, lines: [{ item_code: "A", quantity: "15" }] });
    const onPull = vi.fn();
    render(<PullItemsDialog target="Purchase Receipt" source="Purchase Order" party="" onCancel={() => {}} onPull={onPull} />);
    await screen.findByText("PO-1");
    fireEvent.click(screen.getByLabelText("Select PO-1"));
    expect((screen.getByLabelText("Select PO-2") as HTMLInputElement).disabled).toBe(true);          // another supplier
    fireEvent.click(screen.getByLabelText("Select PO-3"));
    fireEvent.click(screen.getByRole("button", { name: /Get items \(2\)/ }));
    await waitFor(() => expect(onPull).toHaveBeenCalled());
    expect(lines).toHaveBeenCalledWith(expect.objectContaining({ target_doctype: "Purchase Receipt", source_doctype: "Purchase Order", names: ["PO-1", "PO-3"] }));
  });

  it("limits the list to the party already on the form", async () => {
    const list = vi.spyOn(api, "pullCandidates").mockResolvedValue([rows[0]]);
    render(<PullItemsDialog target="Purchase Invoice" source="Purchase Receipt" party="S1" onCancel={() => {}} onPull={() => {}} />);
    await screen.findByText("PO-1");
    expect(list).toHaveBeenCalledWith(expect.objectContaining({ party: "S1", source_doctype: "Purchase Receipt" }));
  });
});
