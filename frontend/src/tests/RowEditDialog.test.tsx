import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RowEditDialog from "../components/RowEditDialog";
import { api, clearCaches } from "../api";
import type { Meta } from "../types";

const meta = {
  name: "Sales Invoice Line",
  fields: [
    { fieldname: "item_code", fieldtype: "Link", label: "Item Code", options: "Inventory Item" },
    { fieldname: "item_name", fieldtype: "Data", label: "Item Name", fetch_from: "item_code.item_name", read_only: true },
  ],
} as unknown as Meta;

beforeEach(() => { clearCaches(); vi.restoreAllMocks(); });

describe("RowEditDialog fetch-from behaviour", () => {
  it("fills dependent values after selecting a linked item in the full-row editor", async () => {
    vi.spyOn(api, "meta").mockResolvedValue({ name: "Inventory Item", title_field: "item_name", fields: [{ fieldname: "item_name", fieldtype: "Data" }] } as any);
    vi.spyOn(api, "searchLink").mockResolvedValue([{ name: "ITM-00135", title: "Nazaclox Ampiclox", description: "Nazaclox Ampiclox" }] as any);
    const get = vi.spyOn(api, "get").mockResolvedValue({ name: "ITM-00135", item_name: "Nazaclox Ampiclox" } as any);
    render(<RowEditDialog meta={meta} row={{ item_code: null, item_name: null }} index={0} onSave={() => {}} onClose={() => {}} />);
    const item = screen.getByLabelText("Item Code");
    fireEvent.focus(item);
    fireEvent.change(item, { target: { value: "ITM-00135" } });
    fireEvent.mouseDown(await screen.findByText("ITM-00135"));
    await waitFor(() => expect((screen.getByLabelText("Item Name") as HTMLInputElement).value).toBe("Nazaclox Ampiclox"));
    expect(get).toHaveBeenCalledWith("Inventory Item", "ITM-00135");
  });
});
