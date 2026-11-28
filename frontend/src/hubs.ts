/** App Hub: one page per application area (Finance, HR & People, Projects ...) built from what the signed-in person may open. */
import type { IconName } from "./ui/Icon";
import type { DocTypeInfo } from "./types";
import type { ReportInfo } from "./api";

export interface HubCentre { label: string; href: string; words?: string; needs?: string }
export interface HubSection { name: string; test: RegExp }
export interface Hub {
  id: string; title: string; blurb: string; icon: IconName; color: string;
  /** The application's how-to guide (served by the framework) and a warm line of welcome shown on the hub page. */
  guide?: string; guideTitle?: string; intro?: string;
  owns: (t: DocTypeInfo) => boolean;
  reports?: (r: ReportInfo, mine: DocTypeInfo[]) => boolean;
  centres: HubCentre[];
  sections?: HubSection[];          // split a big hub into named sections (first match wins; the rest go under "Setup & Other")
}

/** HR, payroll and employee-finance documents sit in the Finance module but belong with people. */
export const isHrType = (t: { name: string; module?: string }) => t.module === "HR" || (t.module === "Finance" && /^(Employee|Salary|Payroll)\b/.test(t.name));

const FINANCE_SECTIONS: HubSection[] = [
  { name: "Receipts & Payments", test: /^(Payment|Receipt|Payment Terms|Expense Batch)$/ },
  { name: "Sales & Receivables", test: /^(Customer|Sales |Delivery Note|Waybill|Party Adjustment)/ },
  { name: "Purchasing & Payables", test: /^(Supplier|Purchase |Request for Quotation|Material Request|Landed Cost)/ },
  { name: "Inventory", test: /^(Inventory|Item Group|Stock |Warehouse|Batch$|Serial Number|Cycle Count|Unit of Measure|Quality Inspection|Opening Stock)/ },
  { name: "Fixed Assets", test: /^Fixed Asset/ },
  { name: "Banking", test: /^(Bank|Batch Bank)/ },
  { name: "Tax", test: /Tax/ },
  { name: "Budgets & Cost Control", test: /^(Financial Budget|Budget|Cost |Intercompany|Business Unit)/ },
  { name: "Requests & Settings", test: /^(Finance (Request|Service|Settings)|Portal Account)/ },
  { name: "Group Consolidation", test: /^Consolidation / },
  { name: "Ledger & Accounting", test: /^(Account|Journal|Financial|Year End|Opening Balance|Accrual|Foreign Currency Revaluation|Expected Credit Loss|Provision Entry|Recognition|Schedule Recognition|Posting|Transaction Type|Currency|Dimension|Accounting Dimension|Naming Series)/ },
];

const FAREPOINT_SECTIONS: HubSection[] = [
  { name: "Corporate Travel", test: /^(Corporate Travel Account|Customer Trip Request|Travel Policy)/ },
  { name: "Sales & Enquiries", test: /^Travel (Lead|Enquiry|Quotation|Follow Up|Referral|Communication Log|Customer Profile)/ },
  { name: "Bookings & Trips", test: /^(Travel Booking|Customer Trip|Flight Booking|Hotel Booking|Tour Booking|Car Rental Booking|Travel Group|Travel Itinerary|Travel Insurance)/ },
  { name: "Visas & Documents", test: /^(Visa|Travel Document|Traveller$)/ },
  { name: "Money & Customers", test: /^(Travel Cancellation|Travel Refund|Travel Payment Schedule|Travel Loyalty Ledger|Travel Feedback|Travel Portal Message)/ },
  { name: "Suppliers", test: /^Travel Supplier/ },
  { name: "Rates, Targets & Settings", test: /^(Travel (Commission|FX|Country)|Farepoint Settings)/ },
  { name: "Products & Packages", test: /^(Tour Package|Travel Package|Travel Destination|Travel Hotel|Hotel Room Type|Car Rental Vehicle|Travel Transfer|Travel Activity|Travel Service)/ },
];


const HR_SECTIONS: HubSection[] = [
  { name: "Employees", test: /^(Employee( HR Profile| Document| Qualification| Status History| Change Request| Classification| Asset| Relations| Separation| Rent| Competency)|Employee$|Employment Contract|Employee Separation|Reporting Assignment|Probation Review|Handover Management)/ },
  { name: "Organisation", test: /^(Department|Branch|Designation|Job (Band|Grade|Position)|Work Location|Critical Position|Succession Candidate|Competency)/ },
  { name: "Recruitment & Onboarding", test: /^(Job (Requisition|Posting|Application|Offer)|Candidate|Interview|Onboarding|Recruitment)/ },
  { name: "Attendance & Shifts", test: /^(Attendance|External Attendance|Shift|Overtime|Holiday List)/ },
  { name: "Leave", test: /^Leave / },
  { name: "Payroll", test: /^(Payroll|Salary|Employee Rent)/ },
  { name: "Performance & Development", test: /^(Performance|Career Development|Employee Competency|Competency Framework)/ },
  { name: "Training", test: /^Training / },
  { name: "Policies & Services", test: /^(HR Policy|HR Service|Department Staff Budget)/ },
];

const PROJECT_SECTIONS: HubSection[] = [
  { name: "Projects", test: /^Project$/ },
  { name: "Portfolio & Programmes", test: /^Project (Portfolio|Programme|Type|Business Case|Charter)/ },
  { name: "Planning & Schedule", test: /^(Project (WBS|Milestone|Baseline|Stage Gate|Deliverable|Task|Epic)|Task Dependency)/ },
  { name: "Execution & Agile", test: /^Project (Sprint|User Story|Work Log|Meeting|Decision|Change Request|Issue|Stakeholder|Document Register|Request Key)/ },
  { name: "Risks & Quality", test: /^Project (Risk|Corrective|Quality|Audit)/ },
  { name: "Budget & Cost", test: /^Project (Budget|Cost|Commitment|Financial|Revenue|Performance Obligation|Benefit)/ },
  { name: "Resources & Time", test: /^(Resource |Project (Resource|Timesheet))/ },
  { name: "Closure", test: /^Project Closure/ },
];

const ADMIN_SECTIONS: HubSection[] = [
  { name: "Requests & Services", test: /^(Service|Request |Maintenance Request|Fulfilment|Checklist|Person Checklist|Knowledge Article)/ },
  { name: "Facilities & Assets", test: /^(Facility|Office |Supply Item|Stock Transaction|Business Calendar)/ },
  { name: "Fleet & Travel", test: /^(Vehicle|Administrative (Vehicle|Travel)|Travel Request|Trip)/ },
  { name: "Visitors & Security", test: /^(Visitor|Administrative Visitor|Access Card|Security Incident)/ },
  { name: "Vendors & Contracts", test: /^(Vendor|Contract|Renewal)/ },
  { name: "Documents & Correspondence", test: /^(Document |Correspondence|Administrative Correspondence)/ },
  { name: "People & Organisation", test: /^(Person$|Organisation Unit|Reporting Line)/ },
  { name: "Approvals & Automation", test: /^(Approval|Automation Rule)/ },
  { name: "Risk & Compliance", test: /^(Risk Register|Compliance Requirement)/ },
  { name: "Events", test: /^(Administrative Event|Event$|Task$)/ },
  { name: "Settings", test: /^Administration Settings$/ },
];

const SUPPORT_SECTIONS: HubSection[] = [
  { name: "Tickets", test: /^(Support Ticket|Canned Reply)$/ },
  { name: "Service Levels & Teams", test: /^(Service Level Agreement|Support Team|Support Category)$/ },
  { name: "Settings", test: /^Support Settings$/ },
];

const NOTIFY_SECTIONS: HubSection[] = [
  { name: "Sending", test: /^(Broadcast|Message Template)$/ },
  { name: "Delivery History", test: /^(Notification Log|Notification Delivery)$/ },
  { name: "Rules & Preferences", test: /^(Notification Rule|Notification Preference|Communication Opt-Out)$/ },
];

const GOVERNANCE_SECTIONS: HubSection[] = [
  { name: "Boards & Committees", test: /^(Board$|Board (?!Action|Meeting|Resolution|Paper|Pack|Evaluation|Skills|Succession)|Board Committee|Board Appointment|Board Member|Board Type|Director)/ },
  { name: "Meetings, Papers & Resolutions", test: /^(Board (Meeting|Resolution|Paper|Pack|Agenda)|Meeting Decision|Governance Meeting)/ },
  { name: "Board Actions", test: /^Board Action/ },
  { name: "Board Effectiveness", test: /^(Board (Evaluation|Skills|Succession)|Governance Skill|Conflict of Interest|Related Party)/ },
  { name: "Entities & Registers", test: /^(Governance Entity|Statutory Register|Shareholder|Share Class|Corporate Event|Governance Event|Governance Calendar)/ },
  { name: "Compliance & Regulatory", test: /^(Regulatory|Compliance|Governance (Obligation|Control|Policy|Code)|Code Compliance|Filing Requirement|Corporate Filing|Annual Return|Disclosure Applicability)/ },
  { name: "Risk & Exceptions", test: /^(Governance (Risk|Exception)|Stakeholder)/ },
  { name: "Automation & Settings", test: /^(Governance (Automation|Settings))/ },
  { name: "Sustainability: Reports", test: /^Sustainability (Report|Disclosure|Assurance)/ },
  { name: "Sustainability: Data & Metrics", test: /^Sustainability (Data|Metric|Unit|Topic|Reporting|Standard|Framework|Settings)|^(Emission|GHG|GWP|Spend Emission|Activity Feed|XBRL|Taxonomy Concept|SASB)/ },
  { name: "Sustainability: Strategy", test: /^Sustainability (Initiative|Opportunity|Risk|Target)|^(Materiality|Climate Scenario)/ },
];

const TAX_SECTIONS: { name: string; test: RegExp }[] = [
  { name: "Setup", test: /^(Tax Jurisdiction|Tax Category|Tax Settings)/ },
  { name: "Rates & Rules", test: /^Tax Rule/ },
  { name: "Withholding Tax", test: /^Tax Journal/ },
  { name: "Company Income Tax", test: /^Income Tax Computation/ },
  { name: "Returns & Obligations", test: /^Tax (Return|Obligation)/ },
];

const TREASURY_SECTIONS: { name: string; test: RegExp }[] = [
  { name: "Lenders & Facilities", test: /^(Financial Institution|Financing Facility|Facility Amendment)/ },
  { name: "Loans & Drawdowns", test: /^Financing Drawdown/ },
  { name: "Repayments & Interest", test: /^(Financing Repayment|Interest Accrual)/ },
  { name: "Covenants & Risk", test: /^Covenant Test/ },
  { name: "Setup", test: /^Treasury Settings/ },
];

export const HUBS: Hub[] = [
  { id: "finance", title: "Finance", blurb: "Ledger, receivables, payables, banking, stock, assets and financial reporting.", icon: "bank", color: "#0f6cbd",
    guide: "/guide/velora_erp", guideTitle: "VeloraERP guide", intro: "Everything the business earns, owes, holds and pays meets here, on one ledger, with every figure traceable to the document behind it.",
    owns: t => t.app === "velora_erp" && t.module === "Finance" && !isHrType(t),
    reports: (r, mine) => /finance|account/i.test(r.module || "") || mine.some(t => t.name === r.ref_doctype),
    sections: FINANCE_SECTIONS,
    centres: [
      { label: "Financial Reporting Centre", href: "#/financial-centre", words: "balance sheet profit loss statements" },
      { label: "Consolidation Centre", href: "#/consolidation", words: "group consolidated subsidiaries eliminate intercompany combine companies translate currency", needs: "Consolidation Group" },
      { label: "Financial Report Designer", href: "#/financial-reports", words: "layouts" },
      { label: "Bank Reconciliation", href: "#/bank-reconciliation", words: "bank statement match" },
      { label: "Budget Workbench", href: "#/budgets", words: "budget plan forecast" },
      { label: "General Ledger Review", href: "#/gl-review", words: "analytical review audit variance", needs: "Account Ledger Record" },
      { label: "Receivables & Payables Check", href: "#/controls-check", words: "audit duplicates control" },
      { label: "Finance eRequest Review", href: "#/finance/requests", words: "requests approve" },
      { label: "My Finance Requests", href: "#/finance/me", words: "requests mine" },
      { label: "Dashboards", href: "#/dashboards" },
    ] },
  { id: "hr", title: "HR & People", blurb: "Employees, leave, recruitment, payroll, performance and policy.", icon: "users", color: "#7a3fb0",
    guide: "/guide/velora_erp", guideTitle: "VeloraERP guide", intro: "The people behind the business: from joining to pay day, with leave, performance and payroll that prepares itself.",
    owns: isHrType,
    sections: HR_SECTIONS,
    reports: (r, mine) => /^hr/i.test(r.module || "") || mine.some(t => t.name === r.ref_doctype),
    centres: [
      { label: "Employee 360°", href: "#/hr/employee", words: "staff profile", needs: "Employee" },
      { label: "Leave Management Centre", href: "#/hr/leave", words: "holiday", needs: "Employee" },
      { label: "Handover & Policy Governance", href: "#/hr/governance", words: "policy handover", needs: "Employee" },
      { label: "Recruitment Centre", href: "#/recruitment", words: "hiring jobs candidates" },
      { label: "My HR Services", href: "#/hr/me", words: "self service" },
      { label: "My Performance", href: "#/hr/performance", words: "appraisal goals" },
      { label: "Team Performance", href: "#/hr/team-performance", words: "appraisal team" },
      { label: "Training Centre", href: "#/hr/training", words: "learning courses" },
    ] },
  { id: "projects", title: "Projects", blurb: "Projects, programmes, schedules, risks, budgets, resources and closure.", icon: "folder", color: "#1b8a5a",
    guide: "/guide/velora_projectone", guideTitle: "ProjectOne guide", intro: "From the first business case to the closing report, with plans, resources, risks and budgets that tell the same truth as the ledger.",
    owns: t => t.app === "velora_projectone",
    sections: PROJECT_SECTIONS,
    reports: (r, mine) => /project/i.test(`${r.module} ${r.name}`) || mine.some(t => t.name === r.ref_doctype),
    centres: [{ label: "Dashboards", href: "#/dashboards" }] },
  { id: "administration", title: "Administration", blurb: "Requests, services, facilities, fleet, vendors, contracts, visitors and records.", icon: "layers", color: "#c2570c",
    guide: "/guide/velora_admin", guideTitle: "Velora Admin guide", intro: "The quiet work that keeps an organisation running, requests, facilities, vehicles, visitors, contracts and renewals, given a proper home.",
    owns: t => t.app === "velora_admin",
    sections: ADMIN_SECTIONS,
    reports: (r, mine) => mine.some(t => t.name === r.ref_doctype),
    centres: [] },
  { id: "farepoint", title: "Farepoint", blurb: "Travel agency: enquiries, quotations, bookings, visas, suppliers and corporate travel.", icon: "bag", color: "#0a7ea4",
    guide: "/guide/farepoint", guideTitle: "Farepoint guide", intro: "From the first enquiry to the safe return home: quotations that follow up on themselves, bookings that bill through the ledger, and visas that never lose a document.",
    owns: t => t.app === "farepoint",
    reports: (r, mine) => /farepoint/i.test(r.module || "") || /^(Travel|Customer Trip|Passport|Traveller)/.test(r.name) || mine.some(t => t.name === r.ref_doctype),
    sections: FAREPOINT_SECTIONS,
    centres: [
      { label: "Farepoint Dashboard", href: "#/dashboards", words: "kpi charts management overview" },
      { label: "Travel Executive Summary", href: "#/report/Travel%20Executive%20Summary", words: "director summary sales cash margin nps", needs: "Travel Booking" },
      { label: "Travel Workspace", href: "#/workspaces", words: "shortcuts desk" },
      { label: "Customers", href: "#/app/Customer", words: "traveller client account", needs: "Customer" },
      { label: "Sales Invoices", href: "#/app/Sales%20Invoice", words: "billing invoice bookings", needs: "Sales Invoice" },
      { label: "Receipts", href: "#/app/Receipt", words: "payments collected cash", needs: "Receipt" },
      { label: "Supplier Payments", href: "#/app/Travel%20Supplier%20Payment", words: "payables airline hotel", needs: "Travel Supplier Payment" },
    ] },
  { id: "insights", title: "Business Insights", blurb: "Decision reports: concentration, cash outlook, collections, customer segments, data quality, access and activity.", icon: "chart", color: "#0b7a75",
    intro: "Plain-language reports that point at what to do next: who to call, where you depend too much on one customer or supplier, who can do what, and how healthy your data is.",
    owns: () => false,
    reports: r => r.module === "Administration",
    centres: [] },
  { id: "engagement", title: "Engagement", blurb: "Birthdays, festive greetings, anniversaries and win-back messages for customers, suppliers and staff.", icon: "mail", color: "#c2185b",
    guide: "/guide/velora_erp", guideTitle: "VeloraERP guide", intro: "The small kindnesses that keep relationships warm: a birthday wish, a festive greeting, a thank-you, a gentle hello to someone you have not seen for a while.",
    owns: t => t.app === "velora_erp" && t.module === "Engagement",
    reports: (r, mine) => r.module === "Engagement" || mine.some(t => t.name === r.ref_doctype && r.module === "Engagement"),
    sections: [
      { name: "Messages Sent", test: /^Engagement Log$/ },
      { name: "Calendar & Dates", test: /^(Occasion|Party Important Date)$/ },
      { name: "Templates & Brand", test: /^(Moment Template|Engagement Settings)$/ },
    ],
    centres: [
      { label: "Customers", href: "#/app/Customer", words: "clients birthdays", needs: "Customer" },
      { label: "Suppliers", href: "#/app/Supplier", words: "vendors birthdays", needs: "Supplier" },
      { label: "Employees", href: "#/app/Employee", words: "staff birthdays anniversaries", needs: "Employee" },
      { label: "People & Access", href: "#/people", words: "users add person roles permissions access staff sign in" },
      { label: "Portal Access", href: "#/portal-access", words: "invite customers suppliers employees portal" },
    ] },
  { id: "support", title: "Customer Support", blurb: "Tickets, SLAs and customer service.", icon: "mail", color: "#00798c",
    guide: "/guide/velora_erp", guideTitle: "VeloraERP guide", intro: "Every customer question answered on time, with deadlines the team can see before the customer has to ask.",
    owns: t => t.app === "velora_erp" && t.module === "Support",
    sections: SUPPORT_SECTIONS,
    centres: [{ label: "Support Desk", href: "#/support", words: "tickets helpdesk sla", needs: "Support Ticket" }] },
  { id: "notify", title: "Notify", blurb: "Messages, templates, rules, preferences and delivery history.", icon: "mail", color: "#6a4bc4",
    intro: "One place to see what was sent, to whom, and why, with the rules and opt-outs that keep messages welcome.",
    owns: t => t.app === "velora_notify", sections: NOTIFY_SECTIONS, centres: [] },
  { id: "governance", title: "Governance", blurb: "Boards, meetings, resolutions, compliance, registers, exceptions and sustainability reporting.", icon: "book", color: "#254e70",
    intro: "Boards and committees, the decisions they take, the obligations the entity carries and the sustainability story it tells, with every exception raised, owned and closed.",
    owns: t => t.app === "velora_governance", reports: (r, mine) => mine.some(t => t.name === r.ref_doctype), sections: GOVERNANCE_SECTIONS,
    centres: [
      { label: "Governance Reports", href: "#/governance/reports", words: "board compliance excel export catalogue", needs: "Board" },
      { label: "Exception Centre", href: "#/governance/exceptions", words: "breach overdue escalation", needs: "Governance Exception" },
      { label: "Automation Monitor", href: "#/governance/automation", words: "scheduled runs retry history", needs: "Governance Automation Execution" },
      { label: "Sustainability Dashboard", href: "#/governance/sustainability", words: "esg emissions disclosure", needs: "Sustainability Report" },
      { label: "IFRS S1/S2 Readiness", href: "#/governance/issb", words: "issb checklist ixbrl climate disclosure", needs: "Sustainability Disclosure Assessment" },
      { label: "Code Assessment", href: "#/governance/code", words: "nccg apply explain principles practices", needs: "Code Compliance Assessment" },
      { label: "SASB Metrics", href: "#/governance/sasb", words: "industry metrics import excel", needs: "SASB Metric" },
    ] },
  { id: "tax", title: "Tax Management", blurb: "Tax rates, withholding tax, company income tax, the tax ledger, returns, filing deadlines and an adviser that checks the books.", icon: "bank", color: "#7a3e00",
    guide: "/guide/velora_erp", guideTitle: "VeloraERP guide", intro: "Approved rates drive every invoice line, the ledger shows every posted tax line, and each return is built from it, approved, filed and tracked to acceptance. Payroll tax stays in Payroll.",
    owns: t => t.app === "velora_erp" && t.module === "Tax Management", reports: (r, mine) => r.module === "Tax Management" || r.name === "VAT Return" || mine.some(t => t.name === r.ref_doctype), sections: TAX_SECTIONS,
    centres: [
      { label: "Tax Centre", href: "#/tax-centre", words: "tax dashboard adviser consultant health check vat wht withholding income tax deadlines", needs: "Tax Rule" },
      { label: "New Tax Journal (withholding tax)", href: "#/app/Tax%20Journal/new", words: "wht withholding customer supplier certificate", needs: "Tax Journal" },
      { label: "New Income Tax Computation", href: "#/app/Income%20Tax%20Computation/new", words: "cit company income tax computation", needs: "Income Tax Computation" },
      { label: "Dashboards", href: "#/dashboards" },
    ] },
  { id: "debt-treasury", title: "Debt & Treasury", blurb: "Lenders, facilities, loans, repayments, interest, covenants, liquidity and currency risk, with an adviser that watches them.", icon: "bank", color: "#00577a",
    guide: "/guide/velora_erp", guideTitle: "VeloraERP guide", intro: "Borrow, repay and accrue interest with every entry posted for you, withholding tax on interest handled, and a clear view of what falls due, what headroom is left and which covenant is close to its limit.",
    owns: t => t.app === "velora_erp" && t.module === "Debt and Treasury", reports: (r, mine) => r.module === "Debt and Treasury" || mine.some(t => t.name === r.ref_doctype), sections: TREASURY_SECTIONS,
    centres: [
      { label: "Treasury Centre", href: "#/treasury-centre", words: "debt loans facilities liquidity covenants maturity fx adviser dashboard cash forecast", needs: "Financing Facility" },
      { label: "New Financing Drawdown", href: "#/app/Financing%20Drawdown/new", words: "borrow loan draw", needs: "Financing Drawdown" },
      { label: "New Financing Repayment", href: "#/app/Financing%20Repayment/new", words: "repay instalment pay loan", needs: "Financing Repayment" },
      { label: "New Interest Accrual", href: "#/app/Interest%20Accrual/new", words: "accrue interest month end", needs: "Interest Accrual" },
      { label: "Dashboards", href: "#/dashboards" },
    ] },
  { id: "investments", title: "Investments", blurb: "Treasury, bonds, shares, property and fixed deposits.", icon: "chart", color: "#8a6d00",
    guide: "/guide/velora_erp", guideTitle: "VeloraERP guide", intro: "Treasury, bonds, shares, property and fixed deposits, kept in step with the accounts.",
    owns: t => t.app === "velora_erp" && t.module === "Investments",
    centres: [{ label: "Investment Portfolio", href: "#/investments", words: "treasury bonds shares", needs: "Investment" }] },
];

export interface HubItem { kind: "doctype" | "report" | "centre"; label: string; href: string; section: string; key: string; canCreate?: boolean; words?: string }

export function sectionOf(hub: Hub, t: DocTypeInfo): string {
  if (hub.sections) return hub.sections.find(s => s.test.test(t.name))?.name ?? "Setup & Other";
  return t.module || "Other";
}

/** Everything a hub offers this person: their forms, the reports on them and the centres whose records they can open. */
export function hubItems(hub: Hub, types: DocTypeInfo[], reports: ReportInfo[]): HubItem[] {
  const mine = types.filter(hub.owns);
  const have = new Set(types.map(t => t.name));
  const out: HubItem[] = [];
  for (const c of hub.centres) if (!c.needs || have.has(c.needs)) out.push({ kind: "centre", label: c.label, href: c.href, section: "Centres", key: `centre|${c.href}`, words: c.words });
  for (const t of mine) out.push({ kind: "doctype", label: t.name, href: `#/app/${encodeURIComponent(t.name)}`, section: sectionOf(hub, t), key: `doctype|${t.name}`, canCreate: t.can_create });
  for (const r of reports) if (hub.reports?.(r, mine)) out.push({ kind: "report", label: r.name, href: `#/report/${encodeURIComponent(r.name)}`, section: "Reports", key: `report|${r.name}`, words: r.description });
  return out;
}

/** Hubs the person can use, plus a catch-all for any other application's forms. */
export function visibleHubs(types: DocTypeInfo[], reports: ReportInfo[]): { hub: Hub; items: HubItem[] }[] {
  const hubs: Hub[] = [...HUBS];
  const claimed = new Set(types.filter(t => HUBS.some(h => h.owns(t))).map(t => t.name));
  const rest = types.filter(t => !claimed.has(t.name));
  const byApp = new Map<string, DocTypeInfo[]>();
  for (const t of rest) (byApp.get(t.app || "other") ?? byApp.set(t.app || "other", []).get(t.app || "other")!).push(t);
  for (const [app, list] of byApp) {
    const title = app === "other" ? "Other" : app.replace(/^velora_/, "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    hubs.push({ id: `app-${app}`, title, blurb: `Forms from ${title}.`, icon: "grid", color: "#5c6b80", owns: t => (t.app || "other") === app, centres: [] });
  }
  return hubs.map(hub => ({ hub, items: hubItems(hub, types, reports) })).filter(x => x.items.some(i => i.kind !== "report" || true) && x.items.length > 0);
}
