import { describe, expect, it } from "vitest";
import { parseHash } from "../router";

describe("Employee 360° route", () => {
  it("opens the employee 360 list", () => {
    expect(parseHash("#/hr/employee")).toMatchObject({ kind: "hr-employee" });
  });
  it("resolves a selected employee identifier", () => {
    expect(parseHash("#/hr/employee/EMP-0001")).toMatchObject({ kind: "hr-employee", name: "EMP-0001" });
  });
});
