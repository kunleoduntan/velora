import { describe, expect, it } from "vitest";
import { visibleHubs } from "../hubs";
import type { DocTypeInfo } from "../types";
import fixture from "./fixtures/doctypes.json";

/** Every parent document type of every installed application, as the desk lists them. */
const types: DocTypeInfo[] = (fixture as { name: string; module: string; app: string }[]).map(x => ({ name: x.name, app: x.app, module: x.module, is_submittable: false, can_create: true }));

describe("hub coverage", () => {
  const hubs = visibleHubs(types, []);
  const docItems = hubs.flatMap(h => h.items.filter(i => i.kind === "doctype").map(i => ({ hub: h.hub.id, ...i })));

  it("puts every parent document type on exactly one hub", () => {
    const seen = new Map<string, string>();
    for (const i of docItems) { expect(seen.has(i.label), `${i.label} appears on two hubs`).toBe(false); seen.set(i.label, i.hub); }
    const missing = types.filter(t => !seen.has(t.name)).map(t => t.name);
    expect(missing).toEqual([]);
  });

  it("groups every document into a named section (nothing is left in the catch-all)", () => {
    for (const { hub, items } of hubs) {
      const docs = items.filter(i => i.kind === "doctype");
      if (!hub.sections) continue;
      const other = docs.filter(i => i.section === "Setup & Other").map(i => i.label);
      expect(other, hub.id).toEqual([]);
    }
  });

  it("gives every hub with more than 12 documents sections", () => {
    for (const { hub, items } of hubs) if (items.filter(i => i.kind === "doctype").length > 12) expect(hub.sections?.length ?? 0, hub.id).toBeGreaterThan(1);
  });
});
