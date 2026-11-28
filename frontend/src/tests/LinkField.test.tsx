import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LinkField from "../components/LinkField";
import { api } from "../api";

vi.mock("../router", () => ({ navigate: vi.fn(), openInNewTab: vi.fn(), CREATED_CHANNEL: "velora-record-created" }));

describe("LinkField", () => {
  it("searches permission-checked records and supports keyboard selection", async () => {
    vi.spyOn(api, "meta").mockResolvedValue({ name: "Customer", title_field: "customer_name", fields: [{ fieldname: "customer_name", fieldtype: "Data" }] } as any);
    vi.spyOn(api, "searchLink").mockResolvedValue([
      { name: "CUST-001", title: "Acme Foods", description: "Acme Foods" },
      { name: "CUST-002", title: "Acme Stores", description: "Acme Stores" },
    ] as any);
    const onChange = vi.fn();
    render(<LinkField doctype="Customer" value="" onChange={onChange} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "Acme" } });
    expect(await screen.findByText("CUST-001")).toBeTruthy();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("CUST-002");
  });

  it("ignores stale search results when a newer query has been entered", async () => {
    let resolveOld!: (value: any) => void;
    const old = new Promise<any>((resolve) => { resolveOld = resolve; });
    vi.spyOn(api, "meta").mockResolvedValue({ name: "Customer", title_field: "customer_name", fields: [{ fieldname: "customer_name", fieldtype: "Data" }] } as any);
    const list = vi.spyOn(api, "searchLink").mockReturnValueOnce(old).mockResolvedValueOnce([{ name: "CUST-NEW", title: "New Result", description: "" }] as any);
    render(<LinkField doctype="Customer" value="" onChange={() => {}} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "old" } });
    await waitFor(() => expect(list).toHaveBeenCalled());
    fireEvent.change(input, { target: { value: "new" } });
    expect(await screen.findByText("CUST-NEW")).toBeTruthy();
    resolveOld([{ name: "CUST-OLD", title: "Old Result", description: "" }]);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByText("CUST-OLD")).toBeNull();
  });
});


describe("LinkField + button", () => {
  it("opens the new record in a new tab instead of leaving the form being edited", async () => {
    const router = await import("../router");
    const { render, screen, fireEvent } = await import("@testing-library/react");
    render(<LinkField doctype="Customer" value="" onChange={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /create new customer/i }));
    expect(router.openInNewTab).toHaveBeenCalledWith("Customer", "new");
    expect(router.navigate).not.toHaveBeenCalled();
  });
});
