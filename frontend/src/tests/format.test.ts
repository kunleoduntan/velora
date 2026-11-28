import { afterEach, describe, expect, it } from "vitest";
import { formatCell, setDisplayFormat } from "../format";

afterEach(() => setDisplayFormat(null));

describe("company display format", () => {
  it("defaults to ISO dates and 1,234.56", () => {
    expect(formatCell("2026-12-31", "Date")).toBe("2026-12-31");
    expect(formatCell(1250000.5, "Currency")).toBe("1,250,000.50");
  });
  it("shows dates the way the company chose", () => {
    setDisplayFormat({ date: "DD/MM/YYYY" }); expect(formatCell("2026-12-31", "Date")).toBe("31/12/2026");
    setDisplayFormat({ date: "MM/DD/YYYY" }); expect(formatCell("2026-12-31", "Date")).toBe("12/31/2026");
    setDisplayFormat({ date: "DD-MMM-YYYY" }); expect(formatCell("2026-12-31", "Date")).toBe("31-Dec-2026");
    setDisplayFormat({ date: "DD MMM YYYY" }); expect(formatCell("2026-12-31T09:30:00", "Datetime")).toBe("31 Dec 2026 09:30");
  });
  it("shows numbers with the chosen separators", () => {
    setDisplayFormat({ number: "1.234,56" }); expect(formatCell(1250000.5, "Currency")).toBe("1.250.000,50");
    setDisplayFormat({ number: "1'234.56" }); expect(formatCell(1250000, "Int")).toBe("1'250'000");
    setDisplayFormat({ number: "1 234,56" }); expect(formatCell(1234.5, "Float")).toBe("1 234,5");
  });
  it("leaves a value that is not a date alone", () => {
    setDisplayFormat({ date: "DD/MM/YYYY" }); expect(formatCell("soon", "Date")).toBe("soon");
  });
});
