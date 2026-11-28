import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import NumberInput from "../components/NumberInput";

describe("NumberInput", () => {
  it("shows money as money and edits as a plain number", () => {
    const onChange = vi.fn();
    render(<NumberInput kind="Currency" value={1250000} onChange={onChange} id="amt" />);
    const box = document.getElementById("amt") as HTMLInputElement;
    expect(box.value).toBe((1250000).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
    fireEvent.focus(box);
    expect(box.value).toBe("1250000");
    fireEvent.change(box, { target: { value: "1,500.5" } });
    expect(onChange).toHaveBeenLastCalledWith(1500.5);
    fireEvent.change(box, { target: { value: "12ab" } });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("clears to null and keeps whole numbers whole", () => {
    const onChange = vi.fn();
    render(<NumberInput kind="Int" value={7} onChange={onChange} id="qty" />);
    const box = document.getElementById("qty") as HTMLInputElement;
    expect(box.value).toBe("7");
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
