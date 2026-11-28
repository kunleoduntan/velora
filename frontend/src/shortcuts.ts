/** Shortcut Hub data: a catalogue of everywhere a person can go, plus their own pins and recent places (kept in this browser only). */
export interface Shortcut { label: string; href: string; group: string; words?: string }

export const CENTRES: Shortcut[] = [
  { label: "Application Workspace", href: "#/workspaces", group: "Centres", words: "home workspace areas" },
  { label: "Operational Centre", href: "#/operational-centre", group: "Centres", words: "operations overview" },
  { label: "Investment Portfolio", href: "#/investments", group: "Centres", words: "investment treasury bonds shares property fixed deposit" },
  { label: "Support Desk", href: "#/support", group: "Centres", words: "tickets helpdesk sla customer service" },
  { label: "Broadcast Centre", href: "#/broadcasts", group: "Centres", words: "email sms whatsapp campaign newsletter communication" },
  { label: "Bank Reconciliation", href: "#/bank-reconciliation", group: "Finance", words: "bank statement match" },
  { label: "Budget Workbench", href: "#/budgets", group: "Finance", words: "budget plan forecast" },
  { label: "Receivables & Payables Check", href: "#/controls-check", group: "Finance", words: "audit duplicates control" },
  { label: "General Ledger Review", href: "#/gl-review", group: "Finance", words: "analytical review isa 520 audit variance journals" },
  { label: "Financial reporting centre", href: "#/financial-centre", group: "Finance", words: "balance sheet profit loss statements" },
  { label: "Finance eRequest Review", href: "#/finance/requests", group: "Finance", words: "requests approve" },
  { label: "Employee 360°", href: "#/hr/employee", group: "People", words: "hr staff" },
  { label: "Leave Management Centre", href: "#/hr/leave", group: "People", words: "leave holiday" },
  { label: "Recruitment Centre", href: "#/recruitment", group: "People", words: "hiring jobs candidates" },
  { label: "My Performance", href: "#/hr/performance", group: "People", words: "appraisal goals" },
  { label: "Portal Access", href: "#/portal-access", group: "Administration", words: "customers suppliers portal invite" },
  { label: "Notification Centre", href: "#/settings/notifications", group: "Administration", words: "alerts rules email" },
  { label: "Rule Studio", href: "#/rules", group: "Administration", words: "business rules" },
  { label: "Theme", href: "#/settings/theme", group: "Administration", words: "colour appearance look" },
  { label: "Data Migration", href: "#/migration", group: "Administration", words: "import export excel" },
  { label: "Activity Centre", href: "#/activity", group: "Administration", words: "audit trail history" },
];

const PIN_KEY = "velora.shortcuts.pins", RECENT_KEY = "velora.shortcuts.recent";
const read = (k: string): string[] => { try { const v = JSON.parse(localStorage.getItem(k) ?? "[]"); return Array.isArray(v) ? v.filter(x => typeof x === "string") : []; } catch { return []; } };
const write = (k: string, v: string[]) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage blocked: shortcuts simply are not remembered */ } };

export const getPins = () => read(PIN_KEY);
export function togglePin(href: string): string[] {
  const pins = getPins(), next = pins.includes(href) ? pins.filter(p => p !== href) : [...pins, href].slice(-24);
  write(PIN_KEY, next); return next;
}
export const getRecents = () => read(RECENT_KEY);
/** Remember a place the person visited (most recent first, no repeats, at most 12; the hub itself is not remembered). */
export function recordVisit(hash: string) {
  if (!hash.startsWith("#/") || hash.startsWith("#/shortcuts") || hash === "#/") return;
  const base = hash.split("?")[0];
  write(RECENT_KEY, [base, ...getRecents().filter(r => r !== base)].slice(0, 12));
}

export function labelFor(href: string, catalogue: Shortcut[]): string {
  const hit = catalogue.find(s => s.href === href);
  if (hit) return hit.label;
  const parts = href.replace(/^#\//, "").split("/").map(decodeURIComponent);
  if (parts[0] === "app" && parts[1]) return parts[2] && parts[2] !== "new" ? `${parts[1]} ${parts[2]}` : parts[2] === "new" ? `New ${parts[1]}` : parts[1];
  if (parts[0] === "report" && parts[1]) return `Report: ${parts[1]}`;
  return parts.join(" / ") || href;
}

export function search(catalogue: Shortcut[], term: string): Shortcut[] {
  const words = term.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return catalogue;
  return catalogue.filter(s => { const hay = `${s.label} ${s.group} ${s.words ?? ""}`.toLowerCase(); return words.every(w => hay.includes(w)); });
}
