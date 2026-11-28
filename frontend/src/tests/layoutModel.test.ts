import { describe, expect, it } from "vitest";
import * as L from "../layoutModel";
import type { Field, GridLayout } from "../types";

const F = (n: string, t: Field["fieldtype"] = "Data"): Field => ({ fieldname: n, fieldtype: t, label: n });
const FIELDS = [F("a"), F("b"), F("c"), F("d"), F("e"), F("memo", "Text"), F("items", "Table")];
const lay = (...rows: [string, number][][]): GridLayout => ({ tabs: [{ label: "Main", sections: [{ label: "S", rows: rows.map((r) => r.map(([field, span]) => ({ field, span }))) }] }] });
const rows = (l: GridLayout, t = 0, s = 0) => l.tabs[t].sections[s].rows.map((r) => r.map((c) => `${c.field}:${c.span}`).join(" "));
const AT = { tab: 0, section: 0 };

describe("finding and placing", () => {
  it("finds fields, lists placed and unplaced ones", () => {
    const l = lay([["a", 6], ["b", 6]], [["c", 12]]);
    expect(L.find(l, "b")).toEqual({ tab: 0, section: 0, row: 0, index: 1 });
    expect(L.find(l, "zzz")).toBeNull();
    expect(L.placedFields(l)).toEqual(["a", "b", "c"]);
    expect(L.unplaced(l, FIELDS).map((f) => f.fieldname)).toEqual(["d", "e", "memo", "items"]);
  });

  it("a new row gets a sensible default width: wide types fill the row, small fields take half", () => {
    let l = lay([["a", 12]]);
    l = L.placeField(l, F("memo", "Text"), { ...AT, row: null });
    l = L.placeField(l, F("items", "Table"), { ...AT, row: null });
    l = L.placeField(l, F("b"), { ...AT, row: null, rowAt: 0 });
    expect(rows(l)).toEqual(["b:6", "a:12", "memo:12", "items:12"]);
    expect(rows(L.placeField(l, F("c"), { ...AT, row: null }, 4))[4]).toBe("c:4");
    expect(L.defaultSpan(F("x", "Int"))).toBe(6);
  });

  it("drops into a row with free space, at the chosen position", () => {
    const l = L.placeField(lay([["a", 4], ["b", 4]]), F("c"), { ...AT, row: 0, index: 1 }, 4);
    expect(rows(l)).toEqual(["a:4 c:4 b:4"]);
  });

  it("a cell that does not fit shrinks to the free space; a FULL row is shared out evenly; a 12-cell row refuses", () => {
    expect(rows(L.placeField(lay([["a", 8]]), F("b"), { ...AT, row: 0 }, 6))).toEqual(["a:8 b:4"]);
    expect(rows(L.placeField(lay([["a", 8], ["b", 4]]), F("c"), { ...AT, row: 0 }, 6))).toEqual(["a:4 b:4 c:4"]);
    expect(rows(L.placeField(lay([["a", 12]]), F("b"), { ...AT, row: 0 }))).toEqual(["a:6 b:6"]);
    const full = lay(Array.from({ length: 12 }, (_, i) => [`f${i}`, 1] as [string, number]));
    expect(() => L.placeField(full, F("x"), { ...AT, row: 0 })).toThrow(L.LayoutError);
    expect(() => L.placeField(lay([["a", 6]]), F("x"), { ...AT, row: 7 })).toThrow("That row does not exist");
    expect(() => L.placeField(lay([["a", 6]]), F("x"), { tab: 3, section: 0, row: null })).toThrow("That section does not exist");
  });

  it("placing a field that is already on the form moves it - it can never appear twice", () => {
    const l = L.placeField(lay([["a", 6], ["b", 6]], [["c", 12]]), "a", { ...AT, row: 1 }, 6);
    expect(rows(l)).toEqual(["b:6", "c:6 a:6"]);
    expect(L.placedFields(l).sort()).toEqual(["a", "b", "c"]);
  });

  it("never mutates its input", () => {
    const l = lay([["a", 6], ["b", 6]]);
    const before = JSON.stringify(l);
    L.placeField(l, F("c"), { ...AT, row: null });
    L.moveField(l, "a", { ...AT, row: null });
    L.resizeField(l, "a", 9);
    L.unplaceField(l, "a");
    expect(JSON.stringify(l)).toBe(before);
  });
});

describe("moving", () => {
  const base = () => lay([["a", 4], ["b", 4], ["c", 4]], [["d", 12]], [["e", 6]]);
  it("reorders within a row - the index is where the user SEES it, before the move", () => {
    expect(rows(L.moveField(base(), "a", { ...AT, row: 0, index: 3 }), 0)[0]).toBe("b:4 c:4 a:4");     // drop after c
    expect(rows(L.moveField(base(), "c", { ...AT, row: 0, index: 0 }))[0]).toBe("c:4 a:4 b:4");
    expect(rows(L.moveField(base(), "a", { ...AT, row: 0, index: 1 }))[0]).toBe("a:4 b:4 c:4");           // dropping where it already is: no change
    expect(rows(L.moveField(base(), "a", { ...AT, row: 0, index: 0 }))[0]).toBe("a:4 b:4 c:4");
  });
  it("moves into another row and out to a new row", () => {
    expect(rows(L.moveField(base(), "a", { ...AT, row: 2, index: 1 }))).toEqual(["b:4 c:4", "d:12", "e:6 a:4"]);          // it keeps its own width when it fits
    expect(rows(L.moveField(base(), "b", { ...AT, row: null, rowAt: 0 }))).toEqual(["b:4", "a:4 c:4", "d:12", "e:6"]);
  });
  it("a row emptied by the move disappears, and 'new row at the end' still means the end", () => {
    expect(rows(L.moveField(base(), "d", { ...AT, row: null, rowAt: 3 }))).toEqual(["a:4 b:4 c:4", "e:6", "d:12"]);
    expect(rows(L.moveField(base(), "d", { ...AT, row: null, rowAt: 0 }))).toEqual(["d:12", "a:4 b:4 c:4", "e:6"]);
    expect(rows(L.moveField(base(), "d", { ...AT, row: null, rowAt: 1 }))).toEqual(["a:4 b:4 c:4", "d:12", "e:6"]);       // dropped where it already was
    expect(rows(L.moveField(base(), "d", { ...AT, row: 2, index: 0 }))).toEqual(["a:4 b:4 c:4", "d:6 e:6"]);                // into a row BELOW its own, which then closes up
    expect(rows(L.moveField(base(), "e", { ...AT, row: 1, index: 0 }))).toEqual(["a:4 b:4 c:4", "e:6 d:6"]);                // into a row ABOVE
  });
  it("moves across sections and tabs", () => {
    let l = L.addSection(base(), 0, "Two");
    l = L.moveField(l, "a", { tab: 0, section: 1, row: null });
    expect(rows(l, 0, 0)[0]).toBe("b:4 c:4");
    expect(rows(l, 0, 1)).toEqual(["a:4"]);
    l = L.moveField(L.addTab(l, "T2"), "d", { tab: 1, section: 0, row: null });
    expect(rows(l, 1, 0)).toEqual(["d:12"]);
  });
  it("refuses to move something that is not there", () => {
    expect(() => L.moveField(base(), "zzz", { ...AT, row: null })).toThrow("zzz is not on the form");
  });
});

describe("resizing", () => {
  it("uses free space first, then takes from the right neighbours, then the left; never below one column each", () => {
    expect(rows(L.resizeField(lay([["a", 4], ["b", 4]]), "a", 8))).toEqual(["a:8 b:4"]);                 // 4 free
    expect(rows(L.resizeField(lay([["a", 4], ["b", 4], ["c", 4]]), "a", 8))).toEqual(["a:8 b:1 c:3"]);   // b gives 3, c gives 1 ... nearest first
    expect(rows(L.resizeField(lay([["a", 4], ["b", 4], ["c", 4]]), "c", 8))).toEqual(["a:3 b:1 c:8"]);   // nothing on the right: the left gives, nearest first (b before a)
    expect(rows(L.resizeField(lay([["a", 6], ["b", 6]]), "a", 12))).toEqual(["a:11 b:1"]);                // the other cell keeps a column
    expect(rows(L.resizeField(lay([["a", 6], ["b", 6]]), "a", 0))).toEqual(["a:1 b:6"]);
    expect(rows(L.resizeField(lay([["a", 6]]), "a", 12))).toEqual(["a:12"]);
    expect(rows(L.resizeField(lay([["a", 6]]), "a", 99))).toEqual(["a:12"]);
    expect(rows(L.resizeField(lay([["a", 6]]), "a", 4.6))).toEqual(["a:5"]);
    expect(() => L.resizeField(lay([["a", 6]]), "zzz", 3)).toThrow(L.LayoutError);
  });
  it("equalises a row, spreading any remainder from the left", () => {
    expect(rows(L.equalizeRow(lay([["a", 1], ["b", 9]]), { ...AT, row: 0 }))).toEqual(["a:6 b:6"]);
    expect(rows(L.equalizeRow(lay([["a", 1], ["b", 1], ["c", 1], ["d", 1], ["e", 1]]), { ...AT, row: 0 }))).toEqual(["a:3 b:3 c:2 d:2 e:2"]);
    expect(() => L.equalizeRow(lay([["a", 6]]), { ...AT, row: 4 })).toThrow("That row does not exist");
  });
});

describe("rows, sections and tabs", () => {
  it("unplacing a field removes only that cell (and an emptied row), and moves rows up and down", () => {
    const l = lay([["a", 6], ["b", 6]], [["c", 12]]);
    expect(rows(L.unplaceField(l, "c"))).toEqual(["a:6 b:6"]);
    expect(rows(L.unplaceField(l, "a"))).toEqual(["b:6", "c:12"]);
    expect(rows(L.moveRow(l, { ...AT, row: 1 }, -1))).toEqual(["c:12", "a:6 b:6"]);
    expect(rows(L.moveRow(l, { ...AT, row: 0 }, -1))).toEqual(rows(l));                                     // already first: unchanged
    expect(rows(L.moveRow(l, { ...AT, row: 1 }, 1))).toEqual(rows(l));
  });
  it("adds, renames, reorders and removes sections - a removed section's fields become unplaced, never deleted", () => {
    let l = L.addSection(lay([["a", 12]]), 0, "Notes");
    expect(l.tabs[0].sections.map((s) => s.label)).toEqual(["S", "Notes"]);
    l = L.updateSection(l, { tab: 0, section: 1 }, { label: "Remarks", collapsible: true });
    expect(l.tabs[0].sections[1]).toMatchObject({ label: "Remarks", collapsible: true });
    l = L.moveSection(l, { tab: 0, section: 1 }, -1);
    expect(l.tabs[0].sections.map((s) => s.label)).toEqual(["Remarks", "S"]);
    const removed = L.removeSection(l, { tab: 0, section: 1 });
    expect(L.unplaced(removed, FIELDS).map((f) => f.fieldname)).toContain("a");
    expect(() => L.removeSection(l, { tab: 0, section: 9 })).toThrow(L.LayoutError);
    expect(() => L.addSection(l, 5)).toThrow("That tab does not exist");
    expect(L.moveSection(l, { tab: 0, section: 0 }, -1)).toEqual(l);
  });
  it("adds, renames, reorders and removes tabs, but never the last one", () => {
    let l = L.addTab(lay([["a", 12]]), "Extra");
    l = L.renameTab(l, 1, "Notes");
    expect(l.tabs.map((t) => t.label)).toEqual(["Main", "Notes"]);
    expect(L.moveTab(l, 1, -1).tabs.map((t) => t.label)).toEqual(["Notes", "Main"]);
    expect(L.removeTab(l, 0).tabs.map((t) => t.label)).toEqual(["Notes"]);
    expect(() => L.removeTab(L.removeTab(l, 0), 0)).toThrow("at least one tab");
    expect(() => L.renameTab(l, 9, "x")).toThrow(L.LayoutError);
  });
});

describe("validation mirrors the server", () => {
  it("flags overfull rows, duplicates and bad widths", () => {
    expect(L.validate(lay([["a", 6], ["b", 6]], [["c", 12]]))).toEqual([]);
    expect(L.validate(lay([["a", 8], ["b", 8]]))[0]).toContain("widths add up to 16");
    expect(L.validate(lay([["a", 6]], [["a", 6]]))[0]).toContain("a is placed twice");
    expect(L.validate(lay([["a", 0]]))[0]).toContain("invalid width");
    expect(L.validate({ tabs: [] })).toEqual(["The form needs at least one tab"]);
  });
});

describe("whatever you do, the layout stays valid and no field is ever lost or duplicated", () => {
  it("survives 2000 random operations", () => {
    let seed = 7;
    const rnd = (n: number) => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed % n; };
    const names = ["a", "b", "c", "d", "e", "memo", "items"];
    let l = lay([["a", 6], ["b", 6]], [["c", 4], ["d", 4], ["e", 4]], [["memo", 12]]);
    const universe = new Set([...L.placedFields(l)]);
    for (let i = 0; i < 2000; i++) {
      const before = new Set(L.placedFields(l));
      const f = names[rnd(names.length)];
      const t = l.tabs.length, s = l.tabs[0].sections.length;
      const pick = () => ({ tab: rnd(t), section: rnd(l.tabs[rnd(t)] ? l.tabs[0].sections.length : 1) });
      try {
        switch (rnd(8)) {
          case 0: l = L.resizeField(l, f, rnd(14)); break;
          case 1: if (before.has(f)) l = L.moveField(l, f, { tab: 0, section: rnd(s), row: null, rowAt: rnd(4) }); break;
          case 2: if (before.has(f)) { const sc = rnd(s); const nrows = l.tabs[0].sections[sc].rows.length; if (nrows) l = L.moveField(l, f, { tab: 0, section: sc, row: rnd(nrows), index: rnd(5) }); } break;
          case 3: l = L.unplaceField(l, f); break;
          case 4: l = L.placeField(l, FIELDS.find((x) => x.fieldname === f)!, { tab: 0, section: rnd(s), row: null, rowAt: rnd(4) }); break;
          case 5: l = L.addSection(l, 0, "x"); break;
          case 6: { const sc = rnd(s); const nr = l.tabs[0].sections[sc].rows.length; if (nr) l = L.equalizeRow(l, { tab: 0, section: sc, row: rnd(nr) }); break; }
          default: { const sc = rnd(s); if (l.tabs[0].sections.length > 1) l = L.moveSection(l, { tab: 0, section: sc }, rnd(2) ? 1 : -1); void pick; }
        }
      } catch (e) {
        expect(e).toBeInstanceOf(L.LayoutError);                                    // the only allowed failure is a clean refusal
      }
      expect(L.validate(l)).toEqual([]);                                             // spans 1..12, rows <= 12, nothing placed twice
      const placed = L.placedFields(l);
      expect(new Set(placed).size).toBe(placed.length);
      expect(placed.every((p) => universe.has(p) || names.includes(p))).toBe(true);
    }
  });
  it("moving never changes WHICH fields are on the form", () => {
    let l = lay([["a", 4], ["b", 4], ["c", 4]], [["d", 6], ["e", 6]]);
    const set = [...L.placedFields(l)].sort();
    for (const [f, to] of [["a", { ...AT, row: 1, index: 1 }], ["d", { ...AT, row: null, rowAt: 0 }], ["c", { ...AT, row: 0, index: 0 }], ["e", { ...AT, row: null, rowAt: 9 }]] as const) {
      l = L.moveField(l, f, to);
      expect([...L.placedFields(l)].sort()).toEqual(set);
    }
  });
});
