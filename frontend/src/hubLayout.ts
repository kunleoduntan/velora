/** A person's own arrangement of a hub: section order, where each shortcut sits, hidden shortcuts and shortcuts they added. Kept per user, per company, per browser. */
import { userKey } from "./api";
import type { HubItem } from "./hubs";

export interface CustomShortcut { key: string; label: string; href: string; section: string }
export interface HubLayout {
  sections: string[];                       // section order (names not listed keep their natural place after these)
  placed: Record<string, string>;           // item key -> section it was dragged to
  order: Record<string, string[]>;          // section -> item keys in the person's order
  hidden: string[];                         // item keys the person removed from the page
  custom: CustomShortcut[];                 // shortcuts the person added
  extra: string[];                          // sections the person created
}
export const EMPTY_LAYOUT: HubLayout = { sections: [], placed: {}, order: {}, hidden: [], custom: [], extra: [] };

const KEY = (hubId: string) => `${userKey()}.hub.layout.${hubId}`;
const strs = (v: unknown): string[] => Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
const rec = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {};

/** A shortcut may only lead to a place inside this desk (never a script or another site). */
export const SAFE_ROUTE = /^#\/[A-Za-z0-9_\-./%?=&,+ ]*$/;
export const validRoute = (href: string) => SAFE_ROUTE.test(href.trim());

export function readLayout(hubId: string): HubLayout {
  try {
    const raw = rec(JSON.parse(localStorage.getItem(KEY(hubId)) ?? "null"));
    const placed: Record<string, string> = {}; for (const [k, v] of Object.entries(rec(raw.placed))) if (typeof v === "string") placed[k] = v;
    const order: Record<string, string[]> = {}; for (const [k, v] of Object.entries(rec(raw.order))) order[k] = strs(v);
    const custom = (Array.isArray(raw.custom) ? raw.custom : []).map(rec).filter(c => typeof c.key === "string" && typeof c.label === "string" && typeof c.href === "string" && typeof c.section === "string" && validRoute(c.href as string)) as unknown as CustomShortcut[];
    return { sections: strs(raw.sections), placed, order, hidden: strs(raw.hidden), custom, extra: strs(raw.extra) };
  } catch { return { ...EMPTY_LAYOUT, placed: {}, order: {}, hidden: [], custom: [], extra: [] }; }
}
export function writeLayout(hubId: string, l: HubLayout): void {
  try { localStorage.setItem(KEY(hubId), JSON.stringify(l)); } catch { /* storage blocked: the arrangement lasts until the page closes */ }
}
export function resetLayout(hubId: string): void { try { localStorage.removeItem(KEY(hubId)); } catch { /* nothing kept */ } }
export const isCustomised = (l: HubLayout) => l.sections.length > 0 || l.hidden.length > 0 || l.custom.length > 0 || l.extra.length > 0 || Object.keys(l.placed).length > 0 || Object.keys(l.order).length > 0;

export interface Placed { name: string; items: HubItem[] }

/** The page the person sees: natural sections and items, then their moves, additions and removals applied on top. */
export function arrange(items: HubItem[], natural: string[], layout: HubLayout): Placed[] {
  const hidden = new Set(layout.hidden);
  const all: HubItem[] = [...items.filter(i => !hidden.has(i.key)), ...layout.custom.filter(c => !hidden.has(c.key)).map(c => ({ kind: "centre" as const, label: c.label, href: c.href, section: c.section, key: c.key }))];
  const secOf = (i: HubItem) => layout.placed[i.key] ?? i.section;
  const names = new Set<string>([...natural, ...layout.extra, ...all.map(secOf)]);
  const base = [...names].sort((a, b) => (natural.indexOf(a) < 0 ? 99 : natural.indexOf(a)) - (natural.indexOf(b) < 0 ? 99 : natural.indexOf(b)) || a.localeCompare(b));
  const chosen = layout.sections.filter(s => names.has(s));
  const sectionNames = [...chosen, ...base.filter(s => !chosen.includes(s))];
  return sectionNames.map(name => {
    const list = all.filter(i => secOf(i) === name);
    const pos = layout.order[name] ?? [];
    list.sort((a, b) => (pos.indexOf(a.key) < 0 ? 9999 : pos.indexOf(a.key)) - (pos.indexOf(b.key) < 0 ? 9999 : pos.indexOf(b.key)));
    return { name, items: list };
  });
}

const clone = (l: HubLayout): HubLayout => ({ sections: [...l.sections], placed: { ...l.placed }, order: Object.fromEntries(Object.entries(l.order).map(([k, v]) => [k, [...v]])), hidden: [...l.hidden], custom: l.custom.map(c => ({ ...c })), extra: [...l.extra] });

/** Move one shortcut to a section, before another shortcut (or at the end). `view` is the page as it is now. */
export function moveItem(layout: HubLayout, view: Placed[], key: string, toSection: string, beforeKey?: string): HubLayout {
  const l = clone(layout);
  for (const s of view) l.order[s.name] = s.items.map(i => i.key);          // freeze what is on screen, then change it
  for (const k of Object.keys(l.order)) l.order[k] = l.order[k].filter(x => x !== key);
  const target = l.order[toSection] ?? (l.order[toSection] = []);
  const at = beforeKey ? target.indexOf(beforeKey) : -1;
  if (at < 0) target.push(key); else target.splice(at, 0, key);
  l.placed[key] = toSection;
  const c = l.custom.find(x => x.key === key); if (c) c.section = toSection;
  l.sections = view.map(s => s.name);
  return l;
}
/** Move a whole section to sit before another (or last). */
export function moveSection(layout: HubLayout, view: Placed[], name: string, beforeName?: string): HubLayout {
  const l = clone(layout);
  const names = view.map(s => s.name).filter(n => n !== name);
  const at = beforeName ? names.indexOf(beforeName) : -1;
  if (at < 0) names.push(name); else names.splice(at, 0, name);
  l.sections = names; return l;
}
/** Move one step up or down (the keyboard route to the same thing dragging does). */
export function nudgeItem(layout: HubLayout, view: Placed[], key: string, dir: -1 | 1): HubLayout {
  const s = view.find(x => x.items.some(i => i.key === key)); if (!s) return layout;
  const idx = s.items.findIndex(i => i.key === key), to = idx + dir;
  if (to < 0 || to >= s.items.length) return layout;
  return moveItem(layout, view, key, s.name, dir < 0 ? s.items[to].key : s.items[to + 1]?.key);
}
export function addShortcut(layout: HubLayout, label: string, href: string, section: string): { layout: HubLayout; error?: string } {
  const text = label.trim(), to = href.trim();
  if (!text) return { layout, error: "Give the shortcut a name." };
  if (!validRoute(to)) return { layout, error: "Use a place inside Velora, such as #/app/Customer or #/report/Trial%20Balance." };
  const l = clone(layout); const key = `custom|${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  l.custom.push({ key, label: text.slice(0, 60), href: to, section });
  if (!l.extra.includes(section)) l.extra.push(section);
  return { layout: l };
}
export function editShortcut(layout: HubLayout, key: string, label: string, href: string): { layout: HubLayout; error?: string } {
  if (!label.trim()) return { layout, error: "Give the shortcut a name." };
  if (!validRoute(href)) return { layout, error: "Use a place inside Velora, such as #/app/Customer." };
  const l = clone(layout); const c = l.custom.find(x => x.key === key); if (!c) return { layout, error: "Only shortcuts you added can be edited; hide or move the others." };
  c.label = label.trim().slice(0, 60); c.href = href.trim(); return { layout: l };
}
/** Remove a shortcut: ones the person added are deleted, built-in ones are hidden (and come back with Reset). */
export function removeItem(layout: HubLayout, key: string): HubLayout {
  const l = clone(layout);
  if (l.custom.some(c => c.key === key)) { l.custom = l.custom.filter(c => c.key !== key); } else if (!l.hidden.includes(key)) l.hidden.push(key);
  for (const k of Object.keys(l.order)) l.order[k] = l.order[k].filter(x => x !== key);
  delete l.placed[key]; return l;
}
export function restoreItem(layout: HubLayout, key: string): HubLayout { const l = clone(layout); l.hidden = l.hidden.filter(x => x !== key); return l; }
export function addSection(layout: HubLayout, view: Placed[], name: string): { layout: HubLayout; error?: string } {
  const n = name.trim().slice(0, 40);
  if (!n) return { layout, error: "Give the section a name." };
  if (view.some(s => s.name.toLowerCase() === n.toLowerCase())) return { layout, error: "There is already a section with that name." };
  const l = clone(layout); l.extra.push(n); l.sections = [...view.map(s => s.name), n]; return { layout: l };
}
/** An empty section the person made can be removed again. */
export function removeSection(layout: HubLayout, name: string): HubLayout {
  const l = clone(layout); l.extra = l.extra.filter(x => x !== name); l.sections = l.sections.filter(x => x !== name); delete l.order[name]; return l;
}
