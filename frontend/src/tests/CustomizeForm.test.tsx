import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import CustomizeForm from "../components/CustomizeForm";
import { api } from "../api";

const meta = { name: "Customer", fields: [
  { fieldname: "customer_name", label: "Customer Name", fieldtype: "Data", required: true },
  { fieldname: "territory", label: "Territory", fieldtype: "Link", options: "Territory" },
  { fieldname: "x_note", label: "Note", fieldtype: "Data" },
] } as never;

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "doctypes").mockResolvedValue([{ name: "Customer", module: "Selling" }, { name: "Item", module: "Stock" }] as never);
  vi.spyOn(api, "meta").mockResolvedValue(meta);
  vi.spyOn(api, "customFields").mockResolvedValue([{ fieldname: "x_note" }] as never);
});

describe("CustomizeForm", () => {
  it("lists fields, marks custom ones, and saves property changes", async () => {
    const save = vi.spyOn(api, "savePropertySetter").mockResolvedValue({} as never);
    render(<CustomizeForm initial="Customer" />);
    await screen.findByText("territory");
    expect(screen.getByText("Custom")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Hidden for territory"));
    fireEvent.click(screen.getByRole("button", { name: /Update \(1\)/ }));
    await waitFor(() => expect(save).toHaveBeenCalledWith("Customer", { fieldname: "territory", property: "hidden", value: true }));
  });

  it("adds a field after a chosen field", async () => {
    const add = vi.spyOn(api, "addCustomField").mockResolvedValue({} as never);
    render(<CustomizeForm initial="Customer" />);
    await screen.findByText("territory");
    fireEvent.change(screen.getByLabelText("New field label"), { target: { value: "Credit Note" } });
    fireEvent.change(screen.getByLabelText("Insert after"), { target: { value: "customer_name" } });
    fireEvent.click(screen.getByRole("button", { name: "Add field" }));
    await waitFor(() => expect(add).toHaveBeenCalledWith("Customer", expect.objectContaining({ fieldname: "credit_note", insert_after: "customer_name", fieldtype: "Data" })));
  });
});
