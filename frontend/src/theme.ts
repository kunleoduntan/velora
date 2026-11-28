/** Theme runtime. The SERVER compiles the design tokens (accessible by construction); the client only applies them:
 *  an injected <style> with CSS variables, plus two attributes on <html>: data-theme (light|dark|system) and data-density. */
import { userKey, type ThemeState } from "./api";

const STYLE_ID = "velora-theme";
export type Mode = "light" | "dark" | "system";
export type Density = "compact" | "comfortable" | "spacious";
export type Palette = "azure" | "teal" | "emerald" | "indigo" | "crimson" | "amber" | "slate";
export const PALETTES: { value: Palette | null; label: string; swatch: string }[] = [
  { value: null, label: "Company default", swatch: "var(--brand)" }, { value: "azure", label: "Azure", swatch: "#0f6cbd" }, { value: "teal", label: "Teal", swatch: "#0f766e" },
  { value: "emerald", label: "Emerald", swatch: "#15803d" }, { value: "indigo", label: "Indigo", swatch: "#4f46e5" }, { value: "crimson", label: "Crimson", swatch: "#be123c" },
  { value: "amber", label: "Amber", swatch: "#b45309" }, { value: "slate", label: "Slate", swatch: "#334155" },
];
export interface Appearance { mode?: Mode | null; density?: Density | null; palette?: Palette | null }

export function applyThemeCss(css: string) {
  let el = document.getElementById(STYLE_ID) as HTMLStyleElement | null;
  if (!el) { el = document.createElement("style"); el.id = STYLE_ID; document.head.appendChild(el); }
  if (el.textContent !== css) el.textContent = css;
}

const key = () => `velora.appearance.${userKey()}`;
export function loadAppearance(): Appearance {
  try { return JSON.parse(localStorage.getItem(key()) || "{}"); } catch { return {}; }
}
export function saveAppearance(a: Appearance) {
  try { localStorage.setItem(key(), JSON.stringify(a)); } catch { /* storage blocked: preference just won't persist */ }
}

/** The organisation's defaults, unless it allows personal overrides and this user chose one. */
export function resolveAppearance(t: Pick<ThemeState, "default_mode" | "spec">, a: Appearance): { mode: Mode; density: Density } {
  const allow = t.spec.allow_user_override;
  return { mode: ((allow && a.mode) || t.default_mode) as Mode, density: ((allow && a.density) || t.spec.density) as Density };
}

export function applyTheme(t: ThemeState, a: Appearance = loadAppearance()) {
  applyThemeCss(t.css);
  const { mode, density } = resolveAppearance(t, a);
  const root = document.documentElement;
  root.setAttribute("data-theme", mode);
  root.setAttribute("data-density", density);
  const palette = t.spec.allow_user_override ? a.palette : null;
  if (palette) root.setAttribute("data-palette", palette); else root.removeAttribute("data-palette");
  // Keep native controls (date pickers, selects, scrollbars) in sync with the
  // selected appearance instead of leaving them in the browser's old scheme.
  root.style.colorScheme = mode === "system" ? "light dark" : mode;
}
