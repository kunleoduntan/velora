import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CompanySwitcher from "../components/CompanySwitcher";

const companies = [
  { id: "A", name: "Alpha", tenant: "G", status: "active", roles: ["System Manager"] },
  { id: "B", name: "Beta", tenant: "G", status: "active", roles: ["System Manager"] },
  { id: "C", name: "Gamma", tenant: "G", status: "suspended", roles: [] },
];
afterEach(cleanup);

describe("Company switcher", () => {
  it("sets and clears a default company without switching", () => {
    const onDefault = vi.fn(), onSwitch = vi.fn();
    const { rerender } = render(<CompanySwitcher companies={companies as any} activeId="A" onSwitch={onSwitch} onDefault={onDefault} />);
    fireEvent.click(screen.getByText("Alpha"));
    fireEvent.click(screen.getByLabelText("Make Beta the default company"));
    expect(onDefault).toHaveBeenCalledWith("B");
    expect(onSwitch).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Make Gamma the default company")).toBeNull();       // a suspended company cannot be the default
    rerender(<CompanySwitcher companies={companies as any} activeId="A" defaultId="B" onSwitch={onSwitch} onDefault={onDefault} />);
    fireEvent.click(screen.getByLabelText("Clear default company Beta"));
    expect(onDefault).toHaveBeenLastCalledWith(null);
  });
});
