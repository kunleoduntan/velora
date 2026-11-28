import { describe, expect, it } from "vitest";
import { parseRecipients } from "../components/EmailDialog";
import { batchTitle } from "../components/FieldControl";
import { buildHash } from "../router";

describe("email recipients", () => {
  it("splits on commas and semicolons, trims and drops duplicates", () => {
    expect(parseRecipients(" a@x.com, b@x.com;a@x.com ,, c@x.com ")).toEqual(["a@x.com", "b@x.com", "c@x.com"]);
    expect(parseRecipients("")).toEqual([]);
  });
});

describe("batch choices", () => {
  it("describes stock, expiry and the batch to use first", () => {
    expect(batchTitle({ quantity: 5, expiry_date: "2027-01-31", expired: false, suggested: true }, true)).toBe("5 in stock · exp 2027-01-31 · use first");
    expect(batchTitle({ quantity: 0, expiry_date: "2026-01-01", expired: true, suggested: false }, false)).toBe("EXPIRED 2026-01-01");
  });
});

describe("new record in a new tab", () => {
  it("builds the address of a blank form for any DocType", () => {
    expect(buildHash("Sales Invoice", "new")).toBe("#/app/Sales%20Invoice/new");
  });
});
