import { describe, expect, it, beforeEach } from "vitest";
import { FREEZE_COLUMNS, frozenFits, loadFreeze, saveFreeze } from "../gridConfig";

describe("freeze panes", () => {
  beforeEach(() => localStorage.clear());
  it("freezes five columns by default", () => { expect(FREEZE_COLUMNS).toBe(5); expect(loadFreeze("Pack Line")).toBe(5); });
  it("remembers a personal choice, including none", () => {
    saveFreeze("Pack Line", 2); expect(loadFreeze("Pack Line")).toBe(2);
    saveFreeze("Pack Line", 0); expect(loadFreeze("Pack Line")).toBe(0);
    saveFreeze("Pack Line", null); expect(loadFreeze("Pack Line")).toBe(5);
  });
  it("keeps all five when they fit and leaves room to scroll", () => { expect(frozenFits([100, 100, 100, 100, 100, 100], 5, 1200)).toBe(5); });
  it("freezes fewer on a narrow screen but never fewer than one", () => {
    expect(frozenFits([200, 200, 200, 200, 200, 200], 5, 800)).toBe(2);
    expect(frozenFits([900, 200], 5, 800)).toBe(1);
  });
  it("does nothing when turned off", () => { expect(frozenFits([100, 100], 0, 1200)).toBe(0); });
});
