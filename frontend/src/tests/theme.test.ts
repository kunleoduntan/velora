import { beforeEach, describe, expect, it } from "vitest";
import { setAuthMode, setProfile, setSession } from "../api";
import { applyTheme, applyThemeCss, loadAppearance, resolveAppearance, saveAppearance } from "../theme";
import { themeState } from "./helpers";

beforeEach(() => {
  document.head.innerHTML = ""; document.documentElement.removeAttribute("data-theme"); document.documentElement.removeAttribute("data-density");
  localStorage.clear(); sessionStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "sam", roles: "Sales User" });
});

describe("theme runtime", () => {
  it("injects one <style> and updates it in place (no duplicates, no flicker on identical css)", () => {
    applyThemeCss(":root{--brand:#111}");
    applyThemeCss(":root{--brand:#222}");
    const tags = document.querySelectorAll("style#velora-theme");
    expect(tags).toHaveLength(1);
    expect(tags[0].textContent).toBe(":root{--brand:#222}");
  });

  it("sets data-theme and data-density from the company theme", () => {
    applyTheme(themeState({ default_mode: "dark", spec: { density: "compact" } }), {});
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.documentElement.getAttribute("data-density")).toBe("compact");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    applyTheme(themeState({ default_mode: "light", spec: { density: "comfortable" } }), {});
    expect(document.documentElement.style.colorScheme).toBe("light");
  });

  it("a user's own mode/density wins - but only when the company allows overrides", () => {
    const allow = themeState({ default_mode: "light", spec: { density: "comfortable", allow_user_override: true } });
    const deny = themeState({ default_mode: "light", spec: { density: "comfortable", allow_user_override: false } });
    expect(resolveAppearance(allow, { mode: "dark", density: "spacious" })).toEqual({ mode: "dark", density: "spacious" });
    expect(resolveAppearance(deny, { mode: "dark", density: "spacious" })).toEqual({ mode: "light", density: "comfortable" });
    expect(resolveAppearance(allow, { mode: null, density: null })).toEqual({ mode: "light", density: "comfortable" });   // null = company default
  });

  it("remembers the personal choice per user (and per company)", () => {
    saveAppearance({ mode: "dark" });
    expect(loadAppearance()).toEqual({ mode: "dark" });
    setSession({ user: "someone-else", roles: "" });
    expect(loadAppearance()).toEqual({});
    localStorage.setItem("velora.appearance.sam", "{bad json");
    setSession({ user: "sam", roles: "" });
    expect(loadAppearance()).toEqual({});                                                  // corrupt storage never breaks the app
  });
});
