import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { api, auth, getCompany, getSession, loadAuthConfig, setCompany, setProfile, setSession, type AuthMode, type Profile, type ReportInfo, type SavedReportInfo, type ThemeState, type BrandingState } from "./api";
import { resetScripts } from "./clientScripts";
import { recordVisit } from "./shortcuts";
import AppearanceMenu from "./components/AppearanceMenu";
import CompanySwitcher from "./components/CompanySwitcher";
import FormView from "./components/FormView";
import ListView from "./components/ListView";
import Login from "./components/Login";
import NotificationBell from "./components/NotificationBell";
import SearchBox from "./components/SearchBox";
import WelcomePage, { WelcomeGate } from "./components/WelcomePage";
import DataImportPage from "./components/DataImportPage";
import Icon, { type IconName } from "./ui/Icon";
import NotificationsPage from "./components/NotificationsPage";
import ActivityCentre from "./components/ActivityCentre";
import MaintenanceScreen, { type MaintenanceInfo } from "./components/MaintenanceScreen";
import DocTypeCreator from "./components/DocTypeCreator";
import ObjectManager from "./components/ObjectManager";
import CustomizeForm from "./components/CustomizeForm";
import ReportBuilder from "./components/ReportBuilder";
import { FinancialReportRun, FinancialReportDetail } from "./components/FinancialReportPages";
import ReportView from "./components/ReportView";
import ThemeSettings from "./components/ThemeSettings";
import BrandingSettings from "./components/BrandingSettings";
import PlatformCompanies from "./components/PlatformCompanies";
import FileExplorer from "./components/FileExplorer";
import PublishPanel from "./components/PublishPanel";
import PublicWebsite from "./components/PublicWebsite";
const PortalApp = lazy(() => import("./portal/PortalApp"));
const ControlsCheck = lazy(() => import("./components/ControlsCheck"));
const InvestmentPortfolio = lazy(() => import("./components/InvestmentPortfolio"));
const SupportDesk = lazy(() => import("./components/SupportDesk"));
const BroadcastCentre = lazy(() => import("./components/BroadcastCentre"));
const GlReview = lazy(() => import("./components/GlReview"));
const ShortcutHub = lazy(() => import("./components/ShortcutHub"));
const PortalAccess = lazy(() => import("./components/PortalAccess"));
const BudgetWorkbench = lazy(() => import("./components/BudgetWorkbench"));
import DataMigrationPackage from "./components/DataMigrationPackage";
import DashboardPage from "./components/DashboardPage";
import DocumentCorrectionsInbox from "./components/DocumentCorrectionsInbox";
import WorkspaceLanding from "./components/WorkspaceLanding";
import WorkflowPage from "./components/WorkflowPage";
import SetupCopyPage from "./components/SetupCopyPage";
import PrintWebsitePage from "./components/PrintWebsitePage";
import SecuritySettings from "./components/SecuritySettings";
import Employee360 from "./components/Employee360";
import PerformancePortal from "./components/PerformancePortal";
import EmployeeSelfService from "./components/EmployeeSelfService";
import ApplicationAreas from "./components/ApplicationAreas";
import CompanySetupPage from "./components/CompanySetupPage";
import { navigate, useRoute } from "./router";
import { applyTheme } from "./theme";
import { loadInstalledAppExtensions } from "./appExtensions";
import type { DocTypeInfo } from "./types";

// Rarely-used admin and studio screens load on demand so the first paint ships less JavaScript.
const DeveloperStudio = lazy(() => import("./components/DeveloperStudio"));
const AIStudio = lazy(() => import("./components/AIStudio"));
const LayoutDesigner = lazy(() => import("./components/LayoutDesigner"));
const FinancialReportDesigner = lazy(() => import("./components/FinancialReportDesigner"));
const FinancialReportingCentre = lazy(() => import("./components/FinancialReportingCentre"));
const OperationalCentre = lazy(() => import("./components/OperationalCentre"));
const FinanceRequestsCentre = lazy(() => import("./components/FinanceRequestsCentre"));
const RecruitmentCentre = lazy(() => import("./components/RecruitmentCentre"));
const UpdateCentre = lazy(() => import("./components/UpdateCentre"));
const BankReconciliationCentre = lazy(() => import("./components/BankReconciliationCentre"));
const WorkspaceDesigner = lazy(() => import("./components/WorkspaceDesigner"));
const NotificationAutomationCentre = lazy(() => import("./components/NotificationAutomationCentre"));
const RuleStudio = lazy(() => import("./components/RuleStudio"));
const LeaveManagementCentre = lazy(() => import("./components/LeaveManagementCentre"));
const TrainingCentre = lazy(() => import("./components/TrainingCentre"));
const HRGovernanceCentre = lazy(() => import("./components/HRGovernanceCentre"));

interface Toast { id: number; message: string; indicator: string }

export default function App() {
  const route = useRoute();
  useEffect(() => { recordVisit(window.location.hash); }, [route]);
  const [mode, setMode] = useState<AuthMode | null>(null);
  const [signedIn, setSignedIn] = useState(false);
  const [profile, setProfileState] = useState<Profile | null>(null);
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [types, setTypes] = useState<DocTypeInfo[]>([]);
  const [epoch, setEpoch] = useState(0);              // bumped when the company changes: remounts every view
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [theme, setTheme] = useState<ThemeState | null>(null);
  const [branding, setBranding] = useState<BrandingState | null>(null);
  const [reports, setReports] = useState<ReportInfo[]>([]);
  const [maintenance, setMaintenance] = useState<MaintenanceInfo | null>(null);
  const [devtools, setDevtools] = useState(false);
  const [savedReports, setSavedReports] = useState<SavedReportInfo[]>([]);
  const [extensionRevision, setExtensionRevision] = useState(0);

  const applyProfile = useCallback((p: Profile | null) => {
    setProfile(p); setProfileState(p);
    if (!p) { setSignedIn(false); setCompany(null); setCompanyId(null); return; }
    const usable = p.companies.filter((c) => c.status === "active");
    const stored = getCompany();
    const pick = (stored && usable.some((c) => c.id === stored) && stored) || (p.default_company && usable.some((c) => c.id === p.default_company) && p.default_company) || (p.active_company && usable.some((c) => c.id === p.active_company) && p.active_company)
      || (usable.length === 1 ? usable[0].id : null);
    setCompany(pick || null); setCompanyId(pick || null); setSignedIn(true);
  }, []);

  useEffect(() => {
    api.themePublic().then((t) => applyTheme(t, {})).catch(() => { /* the built-in fallback tokens apply */ });
  }, []);

  useEffect(() => {
    (async () => {
      const m = await loadAuthConfig();
      setMode(m);
      if (m === "password") { try { applyProfile(await auth.me()); } catch { /* not signed in: the login form appears */ } }
      else setSignedIn(!!getSession());
    })();
  }, [applyProfile]);

  useEffect(() => {
    const on = () => { resetScripts(); setTypes([]); applyProfile(null); };
    const refresh = () => { auth.me().then(applyProfile).catch(() => { /* not signed in */ }); };
    window.addEventListener("velora:profile-changed", refresh);
    window.addEventListener("velora:unauthorized", on);
    return () => { window.removeEventListener("velora:unauthorized", on); window.removeEventListener("velora:profile-changed", refresh); };
  }, [applyProfile]);

  const ready = signedIn && (mode === "developer" || !!companyId);
  useEffect(() => {
    if (!ready) return;
    let dispose: (() => void) | undefined;
    let cancelled = false;
    loadInstalledAppExtensions().then((cleanup) => {
      if (cancelled) cleanup();
      else { dispose = cleanup; setExtensionRevision((value) => value + 1); }
    }).catch((error) => console.error("Velora app extensions could not be loaded", error));
    return () => { cancelled = true; dispose?.(); };
  }, [ready, companyId, epoch]);

  useEffect(() => {
    if (!ready) { setTheme(null); setBranding(null); setReports([]); setSavedReports([]); setDevtools(false); return; }
    api.savedReports().then(setSavedReports).catch(() => setSavedReports([]));
    api.devtoolsStatus().then((d) => setDevtools(d.available)).catch(() => setDevtools(false));
    api.doctypes().then(setTypes).catch(() => setTypes([]));
    api.reports().then(setReports).catch(() => setReports([]));
    api.theme().then((t) => { setTheme(t); applyTheme(t); }).catch(() => setTheme(null));   // the company's own theme
    api.applicationBranding().then(setBranding).catch(() => setBranding(null));
  }, [ready, companyId, epoch]);

  useEffect(() => {
    const aside = document.querySelector(".shell > aside");
    if (!aside) return;
    const toggleHeading = (heading: HTMLElement | null) => {
      if (!heading || !aside.contains(heading)) return;
      const group = heading.parentElement;
      if (!group) return;
      const collapsed = group.getAttribute("data-nav-collapsed") === "true";
      group.setAttribute("data-nav-collapsed", collapsed ? "false" : "true");
      heading.setAttribute("aria-expanded", collapsed ? "true" : "false");
    };
    const onClick = (event: Event) => toggleHeading((event.target as HTMLElement).closest("h3"));
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const heading = (event.target as HTMLElement).closest("h3");
      if (!heading) return;
      event.preventDefault(); toggleHeading(heading);
    };
    aside.addEventListener("click", onClick);
    aside.addEventListener("keydown", onKeyDown as EventListener);
    aside.querySelectorAll("h3").forEach((h) => { h.setAttribute("role", "button"); h.setAttribute("tabindex", "0"); h.setAttribute("aria-expanded", h.parentElement?.getAttribute("data-nav-collapsed") === "true" ? "false" : "true"); });
    aside.querySelectorAll(":scope > div").forEach((g) => { const open = !!g.querySelector("a.active"); g.setAttribute("data-nav-collapsed", open ? "false" : "true"); g.querySelector("h3")?.setAttribute("aria-expanded", open ? "true" : "false"); });
    return () => { aside.removeEventListener("click", onClick); aside.removeEventListener("keydown", onKeyDown as EventListener); };
  }, [types, reports, savedReports, branding, theme, devtools, route.kind, route.name, route.doctype]);

  useEffect(() => {
    const on = (e: Event) => {
      const { message, indicator } = (e as CustomEvent).detail;
      const id = Date.now() + Math.random();
      setToasts((t) => [...t, { id, message, indicator }]);
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
    };
    window.addEventListener("velora:msg", on);
    return () => window.removeEventListener("velora:msg", on);
  }, []);

  useEffect(() => {                                      // the builder tells the shell when a saved report is added/renamed/deleted
    const on = () => { api.savedReports().then(setSavedReports).catch(() => undefined); };
    window.addEventListener("velora:saved-reports-changed", on);
    return () => window.removeEventListener("velora:saved-reports-changed", on);
  }, []);

  useEffect(() => {
    const on = (e: Event) => setMaintenance((e as CustomEvent<MaintenanceInfo>).detail);
    window.addEventListener("velora:maintenance", on);
    return () => window.removeEventListener("velora:maintenance", on);
  }, []);
  useEffect(() => {
    const on = () => { api.applicationBranding().then(setBranding).catch(() => undefined); };
    window.addEventListener("velora:branding-changed", on);
    return () => window.removeEventListener("velora:branding-changed", on);
  }, []);
  useEffect(() => {
    const href = branding?.branding.favicon_url;
    if (!href) return;
    let link = document.querySelector('link[rel="icon"]') as HTMLLinkElement | null;
    if (!link) { link = document.createElement("link"); link.rel = "icon"; document.head.appendChild(link); }
    link.href = href;
  }, [branding?.branding.favicon_url]);

  async function chooseCompany(id: string) {
    await auth.switchCompany(id);                    // validates access server-side; no new sign-in
    setCompany(id); resetScripts(); setTypes([]); setCompanyId(id); setEpoch((e) => e + 1); navigate();
  }
  async function makeDefault(id: string | null) {
    await auth.setDefaultCompany(id);
    applyProfile(await auth.me());
  }
  async function signOut() {
    if (mode === "password") { try { await auth.logout(); } catch { /* already signed out */ } applyProfile(null); }
    else { setSession(null); setSignedIn(false); }
    resetScripts(); setTypes([]); navigate();
    api.themePublic().then((t) => applyTheme(t, {})).catch(() => undefined);
  }

  if (window.location.pathname.startsWith("/site/")) return <PublicWebsite />;
  if (window.location.pathname === "/portal" || window.location.pathname.startsWith("/portal/")) return <Suspense fallback={null}><PortalApp /></Suspense>;
  if (maintenance) return <MaintenanceScreen info={maintenance} />;
  if (mode === null) return <div className="panel">Loading…</div>;
  if (!signedIn) return <Login mode={mode} onDone={async () => { if (mode === "password") { applyProfile(await auth.me()); } else setSignedIn(true); }} />;

  if (mode === "password" && !companyId) {
    const list = profile?.companies ?? [];
    return (
      <div className="login panel chooser">
        <h1>Choose a company</h1>
        <p className="muted">{list.length ? "Each company has its own separate database. You can switch at any time." : "You have not been given access to any company yet. Ask your administrator."}</p>
        <ul>{list.map((c) => (
          <li key={c.id}><button type="button" className="company-card" disabled={c.status !== "active"} onClick={() => chooseCompany(c.id)}>
            <strong>{c.name}</strong><small>{c.tenant} · {c.roles.join(", ")}{c.status !== "active" ? ` · ${c.status}` : ""}</small></button></li>
        ))}</ul>
        <div className="actions"><button type="button" className="rbtn" onClick={signOut}>Sign out</button></div>
      </div>
    );
  }

  const modules = [...new Set(types.map((t) => t.module || "Other"))];
  const identity = mode === "password" ? profile?.user.email : getSession()?.user;
  const activeCompanyRoles = profile?.companies.find((c) => c.id === companyId)?.roles ?? [];
  const developerRoles = (getSession()?.roles ?? "").split(",").map((r) => r.trim());
  const canUseHr360 = mode === "developer"
    ? developerRoles.some((r) => ["System Manager", "HR Manager", "HR Officer"].includes(r))
    : activeCompanyRoles.some((r) => ["System Manager", "HR Manager", "HR Officer"].includes(r));
  const canUseHrSelfService = mode === "developer"
    ? developerRoles.some((r) => ["Employee", "HR Manager", "HR Officer", "System Manager"].includes(r))
    : activeCompanyRoles.some((r) => ["Employee", "HR Manager", "HR Officer", "System Manager"].includes(r));
  const canSubmitHrLeave = mode === "developer"
    ? developerRoles.some((r) => ["System Manager", "HR Manager"].includes(r))
    : activeCompanyRoles.some((r) => ["System Manager", "HR Manager"].includes(r));
  return (
    <div className="shell">
      <aside>
        <div className="brand app-brand">{branding?.branding.logo_url ? <img src={branding.branding.logo_url} alt="" /> : null}<span>{branding?.branding.app_name || "Velora"}</span></div>
        {branding?.branding.tagline && <div className="app-tagline">{branding.branding.tagline}</div>}
        <div><h3><Icon name="grid" size={18} /><span>Applications</span></h3><a href="#/applications" className={route.kind === "applications" ? "active" : ""}>Application Areas</a><a href="#/workspaces" className={route.kind === "workspaces" ? "active" : ""}>Workspace Designer</a></div>
        {mode === "password" && profile?.user.is_platform_admin && <div><h3><Icon name="cog" size={18} /><span>Platform</span></h3><a href="#/platform" className={route.kind === "platform" ? "active" : ""}>Company Administration</a><a href="#/files" className={route.kind === "files" ? "active" : ""}>File Explorer</a><a href="/platform/users/manage">Users, Roles & Access</a><a href="#/updates" className={route.kind === "updates" ? "active" : ""}>Update Centre</a><a href="#/publish" className={route.kind === "publish" ? "active" : ""}>Publish to GitHub</a></div>}
        {canUseHr360 && types.some((t) => t.name === "Employee") && <div><h3><Icon name="users" size={18} /><span>HR & People</span></h3><a href="#/hr/employee" className={route.kind === "hr-employee" ? "active" : ""}>Employee 360°</a><a href="#/hr/leave" className={route.kind === "hr-leave" ? "active" : ""}>Leave Management Centre</a><a href="#/hr/governance" className={route.kind === "hr-governance" ? "active" : ""}>Handover & Policy Governance</a><a href="#/app/Employee" className={route.kind === "app" && route.doctype === "Employee" ? "active" : ""}>Employee Register</a></div>}
        {canUseHrSelfService && <div><h3><Icon name="person" size={18} /><span>Employee Services</span></h3><a href="#/hr/me" className={route.kind === "hr-self-service" ? "active" : ""}>My HR Services</a></div>}
        <div><h3><Icon name="chart" size={18} /><span>Performance</span></h3><a href="#/hr/performance" className={route.kind === "hr-performance" ? "active" : ""}>My Performance</a><a href="#/hr/team-performance" className={route.kind === "hr-team-performance" ? "active" : ""}>Team Performance</a></div>
        {(reports.length > 0 || types.length > 0) && (
          <div><h3><Icon name="chart" size={18} /><span>Reports</span></h3>
            <a href="#/builder" className={route.kind === "builder" && !route.name ? "active" : ""}>＋ New report</a>
            <a href="#/financial-centre" className={route.kind === "financial-centre" ? "active" : ""}>Financial reporting centre</a>
            {reports.map((r) => <a key={r.name} href={`#/report/${encodeURIComponent(r.name)}`} className={route.kind === "report" && route.name === r.name ? "active" : ""}>{r.name}</a>)}</div>
        )}
        {savedReports.length > 0 && (
          <div><h3><Icon name="bookmark" size={18} /><span>My reports</span></h3>
            {savedReports.map((r) => <a key={r.id} href={`#/builder/${encodeURIComponent(r.id)}`} className={route.kind === "builder" && route.name === r.id ? "active" : ""}>{r.name}{r.shared ? " ·" : ""}</a>)}</div>
        )}
        {mode === "password" && <div><h3><Icon name="sliders" size={18} /><span>Tools</span></h3>
          <a href="#/workspaces" className={route.kind === "workspaces" ? "active" : ""}>Application Workspace</a>
          <a href="#/operational-centre" className={route.kind === "operational-centre" ? "active" : ""}>Operational Centre</a>
          <a href="#/bank-reconciliation" className={route.kind === "bank-reconciliation" ? "active" : ""}>Bank Reconciliation</a>
          <a href="#/budgets" className={route.kind === "budgets" ? "active" : ""}>Budget Workbench</a>
          <a href="#/portal-access" className={route.kind === "portal-access" ? "active" : ""}>Portal Access</a>
          <a href="#/shortcuts" className={route.kind === "shortcuts" ? "active" : ""}>Shortcuts</a>
          {types.some(t => t.name === "Investment") && <a href="#/investments" className={route.kind === "investments" ? "active" : ""}>Investment Portfolio</a>}
          {types.some(t => t.name === "Support Ticket") && <a href="#/support" className={route.kind === "support" ? "active" : ""}>Support Desk</a>}
          {types.some(t => t.name === "Broadcast") && <a href="#/broadcasts" className={route.kind === "broadcasts" ? "active" : ""}>Broadcast Centre</a>}
          <a href="#/controls-check" className={route.kind === "controls-check" ? "active" : ""}>Receivables &amp; Payables Check</a>
          {types.some(t => t.name === "Account Ledger Record") && <a href="#/gl-review" className={route.kind === "gl-review" ? "active" : ""}>General Ledger Review</a>}
          <a href="#/finance/requests" className={route.kind === "finance-requests" ? "active" : ""}>Finance eRequest Review</a>
          <a href="#/finance/me" className={route.kind === "finance-me" ? "active" : ""}>My Finance Requests</a>
          <a href="#/dashboards" className={route.kind === "dashboards" ? "active" : ""}>Dashboards</a>
          <a href="#/corrections" className={route.kind === "corrections" ? "active" : ""}>Document Corrections Inbox</a>
          <a href="#/financial-reports" className={route.kind === "financial-layouts" ? "active" : ""}>Financial Report Designer</a>
          <a href="#/rules" className={route.kind === "rules" ? "active" : ""}>Rule Studio</a>
          <a href="#/settings/workflows" className={route.kind === "settings" && route.name === "workflows" ? "active" : ""}>Workflows</a>
          <a href="#/settings/setup-copy" className={route.kind === "settings" && route.name === "setup-copy" ? "active" : ""}>Setup Copy</a>
          <a href="#/settings/notifications" className={route.kind === "settings" && route.name === "notifications" ? "active" : ""}>Notification Centre</a>
          <a href="#/settings/ai-studio" className={route.kind === "ai-studio" ? "active" : ""}>AI & Advisors Studio</a>
          <a href="#/activity" className={route.kind === "activity" ? "active" : ""}>Activity Centre</a>
          <a href="#/settings/print-website" className={route.kind === "settings" && route.name === "print-website" ? "active" : ""}>Print & Website</a>
          <a href="#/migration" className={route.kind === "migration" ? "active" : ""}>Data Migration</a>
          <a href="#/settings/security" className={route.kind === "settings" && route.name === "security" ? "active" : ""}>Sign-in security</a>
        </div>}
        {(theme?.can_edit || devtools) && <div><h3><Icon name="cog" size={18} /><span>Settings</span></h3>
          {theme?.can_edit && <a href="#/settings/theme" className={route.kind === "settings" && route.name === "theme" ? "active" : ""}>Theme</a>}
          {branding?.can_edit && <a href="#/settings/branding" className={route.kind === "settings" && route.name === "branding" ? "active" : ""}>Application Branding</a>}
          {devtools && <a href="#/settings/developer-studio" className={route.kind === "settings" && route.name === "developer-studio" ? "active" : ""}>Developer Studio</a>}
          {(theme?.can_edit || devtools) && <a href="#/settings/customize-form" className={route.kind === "settings" && route.name === "customize-form" ? "active" : ""}>Customize Form</a>}
          {(theme?.can_edit || devtools) && <a href="#/settings/object-manager" className={route.kind === "settings" && route.name === "object-manager" ? "active" : ""}>Object Manager</a>}
          {devtools && <a href="#/settings/doctype-creator" className={route.kind === "settings" && route.name === "doctype-creator" ? "active" : ""}>DocType Creator</a>}
        </div>}
        {branding?.branding.navigation.length ? branding.branding.navigation.map((group, gi) => (
          <div key={`${group.label}-${gi}`}>
            <h3><Icon name="layers" size={18} /><span>{group.label}</span></h3>
            {group.items.filter(item => types.some(t => t.name === item.doctype)).map(item => (
              <a key={item.doctype} href={`#/app/${encodeURIComponent(item.doctype)}`} className={route.doctype === item.doctype ? "active" : ""}>{item.icon ? <Icon name={item.icon as IconName} size={14} /> : null}{item.label || item.doctype}</a>
            ))}
          </div>
        )) : modules.map((m) => (
          <div key={m}>
            <h3><Icon name="layers" size={18} /><span>{m}</span></h3>
            {types.filter((t) => (t.module || "Other") === m).map((t) => (
              <a key={t.name} href={`#/app/${encodeURIComponent(t.name)}`} className={route.doctype === t.name ? "active" : ""}>{t.name}</a>
            ))}
          </div>
        ))}
        <a href="#/applications" className="nav-configure">Configure Features <Icon name="right" size={14} /></a>
      </aside>
      <main>
        <div className="topbar">
          {mode === "password" && profile && <CompanySwitcher companies={profile.companies} activeId={companyId} defaultId={profile.default_company ?? null} onSwitch={chooseCompany} onDefault={makeDefault} />}
          <span className="grow" />
          <SearchBox />
          <a className="icon-btn guide-btn" href="#/welcome" aria-label="Welcome and guide" title="Welcome and guide"><Icon name="book" /></a>
          <NotificationBell />
          <WelcomeGate />
          {theme && <AppearanceMenu theme={theme} />}
          <span>{identity}{mode === "developer" && <span className="muted"> ({getSession()?.roles})</span>}</span>
          <button className="link" type="button" onClick={signOut}>Sign out</button>
        </div>
        <Suspense fallback={<div className="panel">Loading…</div>}>
        {toasts.map((t) => <div key={t.id} className={`toast toast-${t.indicator}`} role="status">{t.message}</div>)}
        <div key={`${companyId}-${epoch}`}>
          {route.kind === "platform" && profile?.user.is_platform_admin && <PlatformCompanies />}
          {route.kind === "hr-employee" && canUseHr360 && <Employee360 employeeName={route.name} />}
          {route.kind === "hr-leave" && canUseHr360 && <LeaveManagementCentre canSubmit={canSubmitHrLeave} />}
          {route.kind === "applications" && <ApplicationAreas />}
          {route.kind === "recruitment" && <RecruitmentCentre />}
          {route.kind === "bank-reconciliation" && <BankReconciliationCentre />}
          {route.kind === "budgets" && <BudgetWorkbench name={route.name} />}
          {route.kind === "portal-access" && <PortalAccess />}
          {route.kind === "controls-check" && <ControlsCheck />}
          {route.kind === "investments" && <InvestmentPortfolio />}
          {route.kind === "support" && <SupportDesk />}
          {route.kind === "broadcasts" && <BroadcastCentre />}
          {route.kind === "gl-review" && <GlReview />}
          {route.kind === "shortcuts" && <ShortcutHub types={types} />}
          {route.kind === "operational-centre" && <OperationalCentre />}
          {route.kind === "finance-requests" && <FinanceRequestsCentre mode="finance" />}
          {route.kind === "finance-me" && <FinanceRequestsCentre mode="employee" />}
          {route.kind === "hr-governance" && canUseHr360 && <HRGovernanceCentre />}
          {route.kind === "hr-governance" && !canUseHr360 && <div className="panel error" role="alert">You do not have permission to access HR Governance.</div>}
          {route.kind === "hr-leave" && !canUseHr360 && <div className="panel error" role="alert">You do not have permission to access Leave Management.</div>}
          {route.kind === "hr-performance" && <PerformancePortal />}
          {route.kind === "hr-team-performance" && <PerformancePortal manager />}
          {route.kind === "hr-training" && <TrainingCentre />}
          {route.kind === "hr-self-service" && canUseHrSelfService && <EmployeeSelfService />}
          {route.kind === "hr-self-service" && !canUseHrSelfService && <div className="panel error" role="alert">You do not have permission to access Employee Self-Service.</div>}
          {route.kind === "hr-employee" && !canUseHr360 && <div className="panel error" role="alert">You do not have permission to access the HR Employee 360° workspace.</div>}
          {route.kind === "files" && profile?.user.is_platform_admin && <FileExplorer initialPath={route.query.path ?? ""} />}
          {route.kind === "publish" && profile?.user.is_platform_admin && <PublishPanel />}
          {route.kind === "updates" && profile?.user.is_platform_admin && <UpdateCentre />}
          {route.kind === "migration" && <DataMigrationPackage />}
          {route.kind === "dashboards" && <DashboardPage />}
          {route.kind === "corrections" && <DocumentCorrectionsInbox />}
          {route.kind === "workspaces" && <WorkspaceDesigner />}
          {route.kind === "financial-centre" && <FinancialReportingCentre />}
          {route.kind === "financial-layouts" && <FinancialReportDesigner />}
          {route.kind === "rules" && <RuleStudio />}
          {route.kind === "company-setup" && <CompanySetupPage />}
          {route.kind === "financial-run" && <FinancialReportRun layoutId={route.query.id ?? ""} />}
          {route.kind === "financial-detail" && <FinancialReportDetail query={route.query} />}
          {route.kind === "settings" && route.name === "workflows" && <WorkflowPage />}
          {route.kind === "settings" && route.name === "setup-copy" && <SetupCopyPage />}
          {route.kind === "settings" && route.name === "notifications" && <NotificationAutomationCentre />}
          {route.kind === "ai-studio" && <AIStudio />}
          {route.kind === "settings" && route.name === "print-website" && <PrintWebsitePage />}
          {route.kind === "settings" && route.name === "security" && <SecuritySettings />}
          {route.kind === "settings" && route.name === "branding" && <BrandingSettings />}
          {route.kind === "home" && <WorkspaceLanding />}
          {route.kind === "app" && route.doctype && !route.name && <ListView doctype={route.doctype} query={route.query} />}
          {route.kind === "app" && route.doctype && route.name && <FormView key={`${extensionRevision}-${route.doctype}-${route.name}`} doctype={route.doctype} name={route.name} />}
          {route.kind === "app" && !route.doctype && <div className="panel muted">Choose a DocType or a report from the sidebar.</div>}
          {route.kind === "report" && route.name && <ReportView name={route.name} />}
          {route.kind === "builder" && <ReportBuilder key={route.name ?? "new"} id={route.name} />}
          {route.kind === "settings" && route.name === "theme" && <ThemeSettings />}
          {route.kind === "settings" && route.name === "layout" && route.doctype && <LayoutDesigner key={route.doctype} doctype={route.doctype} />}
          {route.kind === "settings" && route.name === "doctype-creator" && <DocTypeCreator />}
          {route.kind === "settings" && route.name === "object-manager" && <ObjectManager />}
          {route.kind === "settings" && route.name === "customize-form" && <CustomizeForm />}
          {route.kind === "settings" && route.name === "developer-studio" && <DeveloperStudio />}
          {route.kind === "notifications" && <NotificationsPage />}
          {route.kind === "activity" && <ActivityCentre />}
          {route.kind === "welcome" && <WelcomePage />}
          {route.kind === "import" && route.doctype && <DataImportPage key={route.doctype} doctype={route.doctype} />}
        </div>
        </Suspense>
      </main>
    </div>
  );
}
