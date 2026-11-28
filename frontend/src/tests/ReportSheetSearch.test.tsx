import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ReportSheet from "../components/ReportSheet";

const result: any = {
  title: "T", subtitle: "", company: "", currency: "", filters: [], summary: [], generated_at: "now",
  columns: [{ fieldname: "name", label: "Name", fieldtype: "Data" }, { fieldname: "on", label: "Date", fieldtype: "Date" }],
  rows: [{ type: "data", indent: 0, values: { name: "Alpha", on: "2026-03-09" } }, { type: "data", indent: 0, values: { name: "Beta", on: "2026-04-01" } }],
};

describe("ReportSheet", () => {
  it("shows dd/mm/yyyy and filters rows by what is typed", () => {
    render(<ReportSheet result={result} />);
    expect(screen.getByText("09/03/2026")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search report rows"), { target: { value: "bet" } });
    expect(screen.queryByText("Alpha")).toBeNull();
    expect(screen.getByText("Beta")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search report rows"), { target: { value: "01/04" } });
    expect(screen.getByText("Beta")).toBeTruthy();
  });
});
