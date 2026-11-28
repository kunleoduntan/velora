import { describe, expect, it } from "vitest";

// Every source file except the tests, as text (Vite reads them at build time: no Node file APIs needed).
const sources = import.meta.glob(["../**/*.ts", "../**/*.tsx", "!../tests/**", "!../**/*.test.ts", "!../**/*.test.tsx"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

describe("what the browser has to download", () => {
  it("sees the application's source files (so the checks below cannot pass by finding nothing)", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(30);
    expect(Object.keys(sources).some((f) => f.endsWith("components/ScriptManager.tsx"))).toBe(true);
    expect(Object.keys(sources).some((f) => f.includes("/tests/") || f.endsWith(".test.tsx"))).toBe(false);
  });

  it("never imports a development-only compiler statically (it once added 3 MB to every page of the Desk)", () => {
    for (const [file, text] of Object.entries(sources)) {
      expect(text, file).not.toMatch(/^\s*import[^;\n]*from\s+['"]typescript['"]/m);              // a static import is bundled for everyone
    }
  });

  it("loads the TypeScript compiler on demand, only on the screen that compiles scripts", () => {
    const text = sources["../components/ScriptManager.tsx"];
    expect(text).toMatch(/await import\(['"]typescript['"]\)/);
    expect(text.match(/import\(['"]typescript['"]\)/g)).toHaveLength(1);
  });
});
