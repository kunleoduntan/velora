import { useEffect, useState } from "react";

export interface Route { kind: "home" | "app" | "report" | "settings" | "builder" | "notifications" | "activity" | "welcome" | "import" | "platform" | "files" | "publish" | "migration" | "dashboards" | "corrections" | "workspaces" | "financial-centre" | "financial-layouts" | "financial-run" | "financial-detail" | "rules" | "company-setup" | "ai-studio" | "hr-employee" | "hr-leave" | "hr-performance" | "hr-team-performance" | "hr-training" | "hr-self-service" | "hr-governance" | "applications" | "operational-centre" | "finance-requests" | "finance-me" | "recruitment" | "bank-reconciliation" | "updates" | "budgets" | "portal-access" | "controls-check" | "investments" | "support" | "broadcasts" | "shortcuts" | "gl-review" | "hub" | "governance" | "consolidation" | "tax-centre" | "treasury-centre" | "people"; doctype?: string; name?: string; query: Record<string, string> }

export function parseHash(hash: string): Route {
  const [path, qs = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent); // ["app", doctype, name]
  const query: Record<string, string> = {};
  new URLSearchParams(qs).forEach((v, k) => { query[k] = v; });
  if (parts[0] === "hr" && parts[1] === "governance") return { kind: "hr-governance", query };
  if (parts[0] === "bank-reconciliation") return { kind: "bank-reconciliation", query };
  if (parts[0] === "controls-check") return { kind: "controls-check", query };
  if (parts[0] === "investments") return { kind: "investments", query };
  if (parts[0] === "support") return { kind: "support", query };
  if (parts[0] === "consolidation") return { kind: "consolidation", query };
  if (parts[0] === "governance") return { kind: "governance", name: parts[1] || "reports", query };
  if (parts[0] === "broadcasts") return { kind: "broadcasts", query };
  if (parts[0] === "hub") return { kind: "hub", name: parts[1], query };
  if (parts[0] === "shortcuts") return { kind: "shortcuts", query };
  if (parts[0] === "gl-review") return { kind: "gl-review", query };
  if (parts[0] === "portal-access") return { kind: "portal-access", query };
  if (parts[0] === "people") return { kind: "people", query };
  if (parts[0] === "budgets") return { kind: "budgets", name: parts[1], query };
  if (parts[0] === "recruitment") return { kind: "recruitment", query };
  if (parts[0] === "applications") return { kind: "applications", query };
  if (parts[0] === "operational-centre") return { kind: "operational-centre", query };
  if (parts[0] === "tax-centre") return { kind: "tax-centre", query };
  if (parts[0] === "treasury-centre") return { kind: "treasury-centre", query };
  if (parts[0] === "finance" && parts[1] === "me") return { kind: "finance-me", query };
  if (parts[0] === "finance" && parts[1] === "requests") return { kind: "finance-requests", query };
  if (parts[0] === "hr" && parts[1] === "me") return { kind: "hr-self-service", query };
  if (parts[0] === "hr" && parts[1] === "employee") return { kind: "hr-employee", name: parts[2], query };
  if (parts[0] === "hr" && parts[1] === "leave") return { kind: "hr-leave", query };
  if (parts[0] === "hr" && parts[1] === "performance") return { kind: "hr-performance", query };
  if (parts[0] === "hr" && parts[1] === "team-performance") return { kind: "hr-team-performance", query };
  if (parts[0] === "hr" && parts[1] === "training") return { kind: "hr-training", query };
  if (parts[0] === "app") return { kind: "app", doctype: parts[1], name: parts[2], query };
  if (parts[0] === "report" && parts[1]) return { kind: "report", name: parts[1], query };
  if (parts[0] === "notifications") return { kind: "notifications", query };
  if (parts[0] === "activity") return { kind: "activity", query };
  if (parts[0] === "welcome") return { kind: "welcome", query };
  if (parts[0] === "platform") return { kind: "platform", query };
  if (parts[0] === "files") return { kind: "files", query };
  if (parts[0] === "updates") return { kind: "updates", query };
  if (parts[0] === "publish") return { kind: "publish", query };
  if (parts[0] === "migration") return { kind: "migration", query };
  if (parts[0] === "dashboards") return { kind: "dashboards", query };
  if (parts[0] === "corrections") return { kind: "corrections", query };
  if (parts[0] === "workspaces") return { kind: "workspaces", query };
  if (parts[0] === "financial-centre") return { kind: "financial-centre", query };
  if (parts[0] === "financial-reports") return { kind: "financial-layouts", query };
  if (parts[0] === "financial-report-run") return { kind: "financial-run", query };
  if (parts[0] === "financial-report-detail") return { kind: "financial-detail", query };
  if (parts[0] === "rules") return { kind: "rules", query };
  if (parts[0] === "settings" && parts[1] === "ai-studio") return { kind: "ai-studio", query };
  if (parts[0] === "settings" && parts[1] === "company-setup") return { kind: "company-setup", query };
  if (parts[0] === "import" && parts[1]) return { kind: "import", doctype: parts[1], query };
  if (parts[0] === "builder") return { kind: "builder", name: parts[1], query };
  if (parts[0] === "settings" && parts[1]) return { kind: "settings", name: parts[1], doctype: parts[2], query };
  return { kind: "home", query };
}

export function buildHash(doctype?: string | null, name?: string | null, query?: Record<string, string>): string {
  let h = "#/app";
  if (doctype) h += `/${encodeURIComponent(doctype)}`;
  if (doctype && name) h += `/${encodeURIComponent(name)}`;
  const qs = query && Object.keys(query).length ? `?${new URLSearchParams(query)}` : "";
  return h + qs;
}

export const builderHash = (id?: string | null) => (id ? `#/builder/${encodeURIComponent(id)}` : "#/builder");
export const goTo = (hash: string) => { window.location.hash = hash; };
export const importHash = (doctype: string) => `#/import/${encodeURIComponent(doctype)}`;
export const reportHash = (name: string) => `#/report/${encodeURIComponent(name)}`;

export function navigate(doctype?: string | null, name?: string | null, query?: Record<string, string>) {
  window.location.hash = buildHash(doctype, name, query);
}

/** Open a record (or a blank form) in a NEW browser tab, so whatever is being typed in this one is never lost. */
export function openInNewTab(doctype: string, name = "new"): void {
  const url = `${window.location.pathname}${window.location.search}${buildHash(doctype, name)}`;
  const w = window.open(url, "_blank", "noopener");
  if (!w) window.location.assign(url);   // pop-up blocked: fall back to opening here rather than doing nothing
}

/** Tell other tabs that a record was just created, so a link field waiting for it can pick it up. */
export const CREATED_CHANNEL = "velora-record-created";
export function announceCreated(doctype: string, name: string): void {
  try { if (typeof BroadcastChannel !== "undefined") { const c = new BroadcastChannel(CREATED_CHANNEL); c.postMessage({ doctype, name }); c.close(); } } catch { /* optional nicety */ }
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
