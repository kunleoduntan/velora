import { describe, expect, it } from "vitest";
import corpus from "../../../tests/fixtures/conditions_corpus.json";
import { ConditionError, evaluateCondition, validateCondition } from "../conditions";

type Case = { id: number; expr: string; doc: Record<string, unknown>; ctx: Record<string, unknown>; expect: boolean; valid: boolean };

describe("conditions: shared corpus (expected values produced by real JavaScript)", () => {
  for (const c of corpus as Case[]) {
    it(`#${c.id} ${c.expr}`, () => {
      if (!c.valid) { expect(() => validateCondition(c.expr)).toThrow(ConditionError); expect(evaluateCondition(c.expr, c.doc, c.ctx)).toBe(false); return; }
      expect(() => validateCondition(c.expr)).not.toThrow();
      expect(evaluateCondition(c.expr, c.doc, c.ctx)).toBe(c.expect);
    });
  }
  it("is substantial", () => { expect((corpus as Case[]).length).toBeGreaterThan(150); });
  it("never calls eval or Function", async () => {
    const src = await import("../conditions?raw");
    expect(/\beval\s*\(|new Function|\bFunction\(/.test((src as { default: string }).default)).toBe(false);
  });
});
