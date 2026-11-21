import type { Doc, DocTypeInfo, Field, FieldAppearance, GridColumn, GridLayout, Meta } from "./types";

const KEY = "velora.session";
export interface SessionInfo { user: string; roles: string }

export class ApiError extends Error {
  constructor(public status: number, public kind: string, message: string) {
    super(message);
  }
}

// ---- authentication mode ----------------------------------------------------------------------
// "developer": legacy header sign-in.  "password": real sign-in (HttpOnly cookie) + per-tab company selection.
export type AuthMode = "developer" | "password";
let authMode: AuthMode = "developer";
export const getAuthMode = () => authMode;
export const setAuthMode = (m: AuthMode) => { authMode = m; };

export interface CompanyEntry { id: string; name: string; tenant: string; status: string; roles: string[] }
export interface Profile {
  user: { email: string; full_name: string; is_platform_admin: boolean };
  companies: CompanyEntry[];
  active_company: string | null;
  default_company?: string | null;
}
let profile: Profile | null = null;
export const getProfile = () => profile;
export const setProfile = (p: Profile | null) => { profile = p; };

// The company is chosen PER BROWSER TAB (sessionStorage) and sent with every request, so two tabs can work in two companies at once.
const COMPANY_KEY = "velora.company";
export const getCompany = (): string | null => { try { return sessionStorage.getItem(COMPANY_KEY); } catch { return null; } };
export function setCompany(id: string | null) {
  try { if (id) sessionStorage.setItem(COMPANY_KEY, id); else sessionStorage.removeItem(COMPANY_KEY); } catch { /* storage blocked */ }
  metaCache.clear();
}
export const clearCaches = () => metaCache.clear();

/** Key for per-user, per-company UI preferences (list columns, saved views...). */
export const userKey = (): string =>
  authMode === "password" ? `${profile?.user.email ?? "anonymous"}@${getCompany() ?? "-"}` : (getSession()?.user ?? "anonymous");

export const getSession = (): SessionInfo | null => {
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; }
};
export function setSession(s: SessionInfo | null) {
  if (s) localStorage.setItem(KEY, JSON.stringify(s)); else localStorage.removeItem(KEY);
  metaCache.clear();
}

const metaCache = new Map<string, Promise<Meta>>();

export interface FmEntry { name: string; type: "dir" | "file" | "link"; size: number | null; modified: string | null; editable: boolean; can_delete: boolean; exists?: boolean }
export interface FmListing { path: string; entries: FmEntry[]; can_write: boolean }
export interface FmFile { path: string; content: string; modified: number; editable: boolean }
export interface PublishProfile { id: string; label: string; source: "app" | "upload"; app: string | null; company_id: string; company_name: string; repo_url: string; branch: string;
  author_name: string; author_email: string; has_token: boolean; workdir: string; last_push: { at: string; by: string; commit: string; message: string | null } | null }
export interface PublishCatalog { profiles: PublishProfile[]; apps: string[]; git: boolean; companies: { id: string; name: string; status: string }[] }
export interface Upload { data: Blob; filename: string }

export async function raw(method: string, path: string, body?: unknown, signal?: AbortSignal, upload?: Upload): Promise<Response> {
  const headers: Record<string, string> = {};
  if (authMode === "password") {
    headers["X-Velora-Request"] = "1";                       // required with cookie sessions (CSRF protection)
    const co = getCompany();
    if (co) headers["X-Velora-Company"] = co;
  } else {
    const s = getSession();                                  // developer mode only
    if (s) { headers["X-Velora-User"] = s.user; headers["X-Velora-Roles"] = s.roles; }
  }
  if (upload) {                                                  // a file: sent as it is, its name in a header (no multipart needed)
    headers["Content-Type"] = "application/octet-stream";
    headers["X-Filename"] = encodeURIComponent(upload.filename);
    return fetch(path, { method, headers, credentials: "same-origin", signal, body: upload.data });
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return fetch(path, { method, headers, credentials: "same-origin", signal, body: body === undefined ? undefined : JSON.stringify(body) });
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal, upload?: Upload): Promise<T> {
  const res = await raw(method, path, body, signal, upload);
  let json: { data?: T; error?: string; message?: string } = {};
  try { json = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok) {
    if (res.status === 503 && (json.error === "Maintenance" || json.error === "UpgradePending")) {
      window.dispatchEvent(new CustomEvent("velora:maintenance", { detail: { kind: json.error, message: json.message ?? "" } }));
    }
    if (res.status === 401 && authMode === "password" && !path.startsWith("/api/auth/login")) window.dispatchEvent(new Event("velora:unauthorized"));
    throw new ApiError(res.status, json.error ?? "Error", json.message ?? res.statusText);
  }
  return json.data as T;
}

/** Give a lookup a time limit: instead of "Searching..." for ever, the person is told the server did not answer. */
export async function withTimeout<T>(start: (signal: AbortSignal) => Promise<T>, outer?: AbortSignal, ms = 15000): Promise<T> {
  const ctl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctl.abort(); }, ms);
  const forward = () => ctl.abort();
  outer?.addEventListener("abort", forward);
  try { return await start(ctl.signal); }
  catch (e) { if (timedOut) throw new ApiError(0, "Timeout", "The server did not answer in time. Try again in a moment."); throw e; }
  finally { clearTimeout(timer); outer?.removeEventListener("abort", forward); }
}

const enc = encodeURIComponent;
function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue;
    p.set(k, typeof v === "object" ? JSON.stringify(v) : String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export interface ListParams {
  filters?: [string, string, unknown][];
  fields?: string[];
  order_by?: string;
  limit?: number;
  offset?: number;
}

export interface ExportBody {
  filters?: [string, string, unknown][];
  columns?: string[];
  all_fields?: boolean;
  names?: string[];
  order_by?: string;
  header?: "label" | "fieldname";
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface ThemeAudit { mode: "light" | "dark"; pair: string; fg: string; bg: string; ratio: number; required: number; pass: boolean }
export interface ThemePreset { name: string; label: string; description: string; brand: string; default_mode: string; source: string }
export interface ThemeSpec {
  preset: string; brand: string | null; accent: string | null; radius: string; density: string; font: string;
  default_mode: string | null; allow_user_override: boolean; brand_name: string;
}
export interface ThemeState {
  spec: ThemeSpec; css: string; default_mode: string; brand: string; passed?: boolean; audit?: ThemeAudit[];
  excel?: Record<string, string>; tokens?: { light: Record<string, string>; dark: Record<string, string> };
  presets?: ThemePreset[]; can_edit?: boolean;
}

export interface NavigationItem { doctype: string; label: string; icon: string }
export interface NavigationGroup { label: string; items: NavigationItem[] }
export interface ApplicationBranding {
  app_name: string; tagline: string; logo_url: string; favicon_url: string; navigation: NavigationGroup[];
}
export interface BrandingState { branding: ApplicationBranding; available_doctypes: { name: string; module: string }[]; can_edit: boolean }

export interface ReportFilterDef { fieldname: string; label: string; fieldtype: string; options?: string[] | string | null; default?: unknown; required?: boolean }
export interface ReportInfo { name: string; module: string; description: string; ref_doctype: string; type: string; can_export: boolean }
export interface ReportDefinition extends ReportInfo { filters: ReportFilterDef[] }
export interface ReportColumn { fieldname: string; label: string; fieldtype: string; width?: number | null; total?: string }
export interface ReportRow { type: "data" | "header" | "subtotal" | "total" | "spacer"; values: Record<string, unknown>; indent: number; children: number[] | null }
export interface ReportResultData {
  title: string; subtitle: string; columns: ReportColumn[]; rows: ReportRow[]; filters: [string, string][];
  summary: { label: string; value: unknown; fieldtype?: string }[]; notes: string[]; currency: string; company: string; report_name: string; generated_at: string;
}

export interface AdhocMeasure { fn: string; field?: string | null; label?: string }
export interface AdhocSpec {
  doctype: string; group_by: string[]; date_field?: string | null; date_bucket?: string | null;
  measures: AdhocMeasure[]; filters: [string, string, unknown][]; title?: string;
}
export interface SavedReportInfo { id: string; name: string; doctype: string; owner: string; shared: boolean; can_edit: boolean; updated_on: string | null }
export interface SavedReport extends SavedReportInfo { spec: AdhocSpec }
export interface FinancialLayoutRow {
  code: string; description: string; type: string; indent: number; bold: boolean; italic: boolean; show: boolean;
  account_no?: string; from_account?: string; to_account?: string; category?: string; dimension?: string;
  dimension_value?: string; sign?: number; formula?: string; text?: string;
}
export interface FinancialLayoutColumn {
  code: string; caption: string; type: string; date_mode: string; period: string; offset: number; width: number;
  formula?: string; text?: string;
}
export interface FinancialLayoutDefinition { rows: FinancialLayoutRow[]; columns: FinancialLayoutColumn[]; options?: Record<string, unknown> }
export interface FinancialLayoutInfo { id: string; name: string; shared: boolean; can_edit: boolean; definition: FinancialLayoutDefinition }
export interface FinancialStatementColumn { code: string; caption: string; type: string; period_label: string; width: number }
export interface FinancialStatementRow { code: string; description: string; type: string; indent: number; bold: boolean; italic: boolean; values: Record<string, number | null> }
export interface FinancialStatementResult { name: string; base_currency?: string; filters: { from_date: string; to_date: string; as_of_date?: string; budget_name?: string; cost_centre?: string; branch?: string; business_unit?: string; project?: string; department?: string }; columns: FinancialStatementColumn[]; rows: FinancialStatementRow[] }
export interface FinancialDrilldownEntry { name: string; posting_date: string; account: string; voucher_type: string; voucher_no: string; party_type?: string; party?: string; remarks?: string; debit: number; credit: number; amount: number; is_reversal: boolean }
export interface FinancialDrilldownResult { row: string; description: string; column: string; period_label: string; accounts: string[]; entries: FinancialDrilldownEntry[]; truncated: boolean }

async function getForFile(path: string, fallback: string): Promise<{ blob: Blob; filename: string }> {
  const res = await raw("GET", path);
  if (!res.ok) {
    let j: { error?: string; message?: string } = {};
    try { j = await res.json(); } catch { /* not JSON */ }
    throw new ApiError(res.status, j.error ?? "Error", j.message ?? res.statusText);
  }
  const cd = res.headers.get("Content-Disposition") ?? "";
  return { blob: await res.blob(), filename: /filename="?([^"]+)"?/.exec(cd)?.[1] ?? fallback };
}

export interface ImportOptions { mode: "insert" | "update" | "upsert"; submit: boolean; atomic: boolean; keep_names: boolean; date_format: "DMY" | "MDY" | "YMD"; match: string }
export interface ImportError { row: number; field: string; message: string }
export interface FailedRow { row: number; error: string; data: Record<string, unknown> }
export interface ImportReport {
  doctype: string; mode: string; dry_run: boolean; total: number; created: number; updated: number; failed: number; ok: boolean; unknown_columns: string[];
  errors: ImportError[]; errors_truncated: boolean; names: string[]; failed_rows: FailedRow[]; rolled_back: boolean; duration_ms: number;
}

async function postForFile(path: string, body: unknown, fallback: string): Promise<{ blob: Blob; filename: string }> {
  const res = await raw("POST", path, body);
  if (!res.ok) {
    let j: { error?: string; message?: string } = {};
    try { j = await res.json(); } catch { /* not JSON */ }
    throw new ApiError(res.status, j.error ?? "Error", j.message ?? res.statusText);
  }
  const cd = res.headers.get("Content-Disposition") ?? "";
  return { blob: await res.blob(), filename: /filename="?([^"]+)"?/.exec(cd)?.[1] ?? fallback };
}

export interface LayoutInfo { source: "company" | "app" | "auto"; layout: GridLayout; appearance: Record<string, FieldAppearance>; unplaced: Field[]; fields: Field[]; editable: boolean; can_write_app: boolean }
export interface GridInfo { source: "company" | "app" | "auto"; columns: GridColumn[]; fields: Field[]; editable: boolean }
export interface CreatorBody {
  json: string; app: string; module?: string; name?: string; on_conflict?: "error" | "skip";
  is_child?: boolean; is_submittable?: boolean; track_changes?: boolean; is_autoname?: boolean; autoname_field_name?: string;
}
export interface CreatorReport {
  structure: string; ok: boolean; errors: string[]; warnings: string[]; conflicts: string[]; skipped: string[]; order: string[];
  doctypes: { name: string; module: string; fields: number; child: boolean; submittable: boolean; links: string[]; path: string }[];
}
export interface CreatorResult { created: string[]; files: string[]; skipped: string[]; warnings: string[]; migration: string[]; note: string; folders?: string[] }

export interface NotificationItem { name: string; subject: string; message: string | null; ref_doctype: string | null; ref_name: string | null; priority: string; rule: string | null; read: number; read_on: string | null; creation: string }
export interface NotificationList { items: NotificationItem[]; unread: number; total: number }
export interface NotificationPrefs { email_enabled: boolean; quiet_start: string | null; quiet_end: string | null; digest: string; muted_rules: string[] }

export interface SearchHit { doctype: string; name: string; title: string }

export interface LifecycleEvent { id: string; at: string; kind: string; title: string; ok: boolean; version: string; steps: { text: string; ok: boolean }[]; from_version?: string; to_version?: string; app?: string; domain?: string }
export interface WelcomeData {
  product: string; powered_by: string; version: string; user: string; is_admin: boolean; company: { id: string; name: string } | null; latest: LifecycleEvent | null; events: LifecycleEvent[];
  apps: { name: string; title: string; description: string; built_in: boolean }[]; features: { notifications: boolean; search: boolean; accounts: boolean };
  domains: { domain: string; primary: boolean; tls: boolean; locked: boolean }[]; host: string; tutorial_url: string; platform: boolean
}

export interface CopyPayload { doctype: string; mode: "amend" | "duplicate"; source: string; values: Record<string, unknown>; amended_from: string | null; suggested_name: string | null }

export interface AppExtensionAsset { path: string; type: "javascript" | "stylesheet"; size_bytes?: number; sha256?: string }
export interface AppExtensionManifest {
  name: string; version: string; frontend_assets: AppExtensionAsset[];
  lifecycle_hooks: string[]; doc_events: boolean; scheduler_events: string[]; job_handlers: string[];
}

export interface ActivityItem { id:string; at:string; actor:string; event_type:string; title:string; doctype:string|null; document_name:string|null; source:string; changed_fields:string[]; summary:string|null }
export interface ActivityFeed { items:ActivityItem[]; total:number; limit:number; offset:number }
export interface AuditCase {id:string;title:string;description:string|null;status:string;priority:string;doctype:string|null;document_name:string|null;owner:string;assigned_to:string|null;created_on:string;modified_on:string}
export interface AuditCaseNote {id:string;case_id:string;actor:string;body:string;created_on:string}


export interface DocumentFlowAction { source_doctype: string; target_doctype: string; label: string; status: string; available: boolean; cardinality: "one_to_one" | "one_to_many"; description: string }
export interface CreatedFromDocument { doctype: string; name: string; docstatus: number; source_doctype?: string | null; source_document?: string | null }

export interface PullCandidate { name: string; party: string; party_name: string; date: string; currency: string; open_lines: number; open_quantity: string }

export const api = {
  marketplace: () => request<{ repository: string; status: string; path: string; packages: { name?: string; version?: string; file?: string; sha256?: string; status: string; error?: string }[] }[]>("GET", "/api/marketplace"),
  appExtensions: () => request<AppExtensionManifest[]>("GET", "/api/app-extensions"),
  copyDoc: (doctype: string, name: string, mode: "amend" | "duplicate") => request<CopyPayload>("GET", `/api/resource/${enc(doctype)}/${enc(name)}/copy?mode=${mode}`),
  documentFlowActions: (doctype: string, name: string) => request<DocumentFlowAction[]>("GET", `/api/document-flow/${enc(doctype)}/${enc(name)}/actions`),
  createFromDocument: (doctype: string, name: string, target_doctype: string, overrides: Record<string, unknown> = {}) =>
    request<CreatedFromDocument>("POST", `/api/document-flow/${enc(doctype)}/${enc(name)}/create`, { target_doctype, overrides }),
  pullSources: (target: string) => request<string[]>("GET", `/api/pull-items/${enc(target)}/sources`),
  pullCandidates: (body: { target_doctype: string; source_doctype: string; party?: string; txt?: string }) =>
    request<PullCandidate[]>("POST", "/api/pull-items/candidates", body),
  pullLines: (body: { target_doctype: string; source_doctype: string; names: string[]; party?: string }) =>
    request<{ header: Record<string, unknown>; lines: Record<string, unknown>[] }>("POST", "/api/pull-items/lines", body),
  amendedTo: (doctype: string, name: string) => request<{ amended_to: string | null }>("GET", `/api/resource/${enc(doctype)}/${enc(name)}/amended-to`),
  settlementOutstanding: (body: Record<string, unknown>) => request<{ invoices: OutstandingInvoice[]; methods: string[] }>("POST", "/api/settlement/outstanding", body),
  settlementAllocate: (body: Record<string, unknown>) => request<SettlementAllocation>("POST", "/api/settlement/allocate", body),
  welcome: () => request<WelcomeData>("GET", "/api/welcome"),
  hrSelfServiceOverview: () => request<any>("GET", "/api/hr/me/overview"),
  hrSelfServiceRequests: () => request<any>("GET", "/api/hr/me/requests"),
  hrSelfServicePayslips: () => request<any>("GET", "/api/hr/me/payslips"),
  hrSubmitLeaveApplication: (body: {leave_type:string;from_date:string;to_date:string;reason:string;half_day?:boolean;half_day_period?:string}) => request<any>("POST", "/api/hr/me/leave-applications", body),
  hrCreateSelfServiceRequest: (body: {request_type:string;subject:string;details:string;priority?:string}) => request<any>("POST", "/api/hr/me/requests", body),
  performanceMe: () => request<any>("GET", "/api/hr/performance/me"),
  trainingCatalog: (activeOnly = true) => request<any>("GET", `/api/hr/training/catalog?active_only=${activeOnly}`),
  trainingNeedsAnalysis: (employee?: string, department?: string) => request<any>("GET", `/api/hr/training/needs-analysis${employee ? `?employee=${enc(employee)}` : department ? `?department=${enc(department)}` : ""}`),
  trainingPrograms: (status = "Approved") => request<any>("GET", `/api/hr/training/programs?status=${enc(status)}`),
  trainingOperations: (program?: string) => request<any>("GET", `/api/hr/training/operations${program ? `?program=${enc(program)}` : ""}`),
  trainingRecordAttendance: (name: string, body: any) => request<any>("POST", `/api/hr/training/enrollments/${enc(name)}/attendance`, body),
  trainingIssueCertificate: (name: string, body: any) => request<any>("POST", `/api/hr/training/enrollments/${enc(name)}/certificate`, body),
  trainingAnalytics: () => request<any>("GET", "/api/hr/training/analytics"),
  trainingEffectiveness: (program?: string) => request<any>("GET", `/api/hr/training/effectiveness${program ? `?program=${enc(program)}` : ""}`),
  trainingBudgetAnalysis: (program?: string) => request<any>("GET", `/api/hr/training/budget-analysis${program ? `?program=${enc(program)}` : ""}`),
  trainingRecommendations: (employee?: string, department?: string) => request<any>("GET", `/api/hr/training/recommendations${employee ? `?employee=${enc(employee)}` : department ? `?department=${enc(department)}` : ""}`),
  performanceCycleAssignmentPreview: (cycle: string, body: any = {}) => request<any>("POST", `/api/hr/performance/cycles/${enc(cycle)}/assignment-preview`, body),
  performanceCycleAssign: (cycle: string, employees: string[]) => request<any>("POST", `/api/hr/performance/cycles/${enc(cycle)}/assign`, { employees }),
  performanceReminderPreview: () => request<any>("POST", "/api/hr/performance/workflow/reminders/preview", {}),
  performanceReminderQueue: (idempotency_keys: string[] = []) => request<any>("POST", "/api/hr/performance/workflow/reminders/queue", { idempotency_keys }),
  performanceReminderInbox: (status = "Queued") => request<any>("GET", `/api/hr/performance/workflow/reminders?status=${enc(status)}`),
  performanceTrends: (employee?: string, department?: string) => request<any>("GET", `/api/hr/performance/intelligence/trends${employee ? `?employee=${enc(employee)}` : department ? `?department=${enc(department)}` : ""}`),
  successionOverview: () => request<any>("GET", "/api/hr/succession/overview"),
  performanceManagerTeam: (cycle?: string) => request<any>("GET", `/api/hr/performance/manager/team${cycle?`?cycle=${enc(cycle)}`:""}`),
  performanceUpdateGoal: (name: string, body: any) => request<any>("POST", `/api/hr/performance/me/goals/${enc(name)}/progress`, body),
  performanceCreateCheckin: (body: any) => request<any>("POST", "/api/hr/performance/me/check-ins", body),
  performanceManagerCheckin: (employee: string, body: any) => request<any>("POST", `/api/hr/performance/manager/team/${enc(employee)}/check-ins`, body),
  performanceAcknowledge: (name: string, body: any) => request<any>("POST", `/api/hr/performance/me/reviews/${enc(name)}/acknowledge`, body),
  importTemplate: (doctype: string) => getForFile(`/api/data-import/${enc(doctype)}/template?format=xlsx`, `${doctype}_import_template.xlsx`),
  importFile: (doctype: string, file: Blob, filename: string, o: ImportOptions, dryRun: boolean) => {
    const q = new URLSearchParams({ mode: o.mode, dry_run: dryRun ? "1" : "0", submit: o.submit ? "1" : "0", atomic: o.atomic ? "1" : "0", keep_names: o.keep_names ? "1" : "0", date_format: o.date_format });
    if (o.match) q.set("match", o.match);
    return request<ImportReport>("POST", `/api/data-import/${enc(doctype)}?${q}`, undefined, undefined, { data: file, filename });
  },
  importErrorsXlsx: (rows: FailedRow[]) => postForFile("/api/data-import/errors-xlsx", { failed_rows: rows }, "import_errors.xlsx"),
  gridExcelTemplate: (child: string) => getForFile(`/api/grid-excel/${enc(child)}/template`, `${child}_template.xlsx`),
  gridExcelExport: (child: string, rows: Record<string, unknown>[]) => postForFile(`/api/grid-excel/${enc(child)}/export`, { rows }, `${child}_rows.xlsx`),
  gridExcelRead: (child: string, file: Blob, filename: string) =>
    request<{ rows: Record<string, unknown>[]; errors: { row: number; column: string; error: string }[]; unknown: string[] }>("POST", `/api/grid-excel/${enc(child)}/read`, undefined, undefined, { data: file, filename }),
  exportData: (doctype: string) => getForFile(`/api/data-export/${enc(doctype)}?format=xlsx`, `${doctype}.xlsx`),
  searchLink: (doctype: string, txt: string, filters: [string, string, unknown][] = [], limit = 10, signal?: AbortSignal) =>
    withTimeout((sig) => request<{ name: string; title: string; description: string }[]>("GET", `/api/search-link?doctype=${encodeURIComponent(doctype)}&txt=${encodeURIComponent(txt)}&limit=${limit}${filters.length ? `&filters=${encodeURIComponent(JSON.stringify(filters))}` : ""}`, undefined, sig), signal),
  search: (q: string, limit = 12, signal?: AbortSignal) => withTimeout((sig) => request<SearchHit[]>("GET", `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`, undefined, sig), signal),
  aiCapabilities: () => request<{can_manage_providers:boolean}>("GET","/api/ai/capabilities"),
  aiProviders: () => request<{id:string;name:string;provider_type:string;model:string;endpoint:string|null;priority:number;active:boolean;credential_configured:boolean}[]>("GET","/api/ai/providers"),
  saveAIProvider: (body:{name:string;provider_type:string;model:string;endpoint?:string|null;secret_env:string;priority:number;active:boolean}) => request<any>("POST","/api/ai/providers",body),
  deleteAIProvider: (id:string) => request<{deleted:boolean}>("DELETE",`/api/ai/providers/${enc(id)}`),
  aiAdvisors: () => request<{id:string;title:string;description:string;app:string;doctype:string|null}[]>("GET","/api/ai/advisors"),
  aiUsage: (limit=100) => request<{items:{id:string;occurred_on:string;actor:string;advisor_id:string;provider:string;model:string;outcome:string;latency_ms:number;error_code:string|null}[];total:number}>("GET",`/api/ai/usage?limit=${limit}`),
  askAI: (body:{advisor_id:string;question:string;doctype?:string;document_name?:string}) => request<{advisor_id:string;advisor:string;provider:string;model:string;answer:string;advisory_only:boolean}>("POST","/api/ai/ask",body),
  aiDeveloperTools: () => request<{tools:string[];can_develop:boolean}>("GET","/api/ai/developer/tools"),
  aiDeveloperDatabase: () => request<any>("GET","/api/ai/developer/database"),
  aiDeveloperQuery: (doctype:string,fields:string[],filters:any={},limit=100) => request<any>("POST","/api/ai/developer/database/query",{doctype,fields,filters,limit}),
  aiGenerateDocType: (body:{description:string;app:string;module:string;is_submittable?:boolean}) => request<any>("POST","/api/ai/developer/doctype/generate",body),
  aiPublishDocType: (body:{definition:any;app:string;module:string;on_conflict?:string}) => request<any>("POST","/api/ai/developer/doctype/publish",body),
  aiGenerateCode: (body:{task:string;language:string;target:string}) => request<any>("POST","/api/ai/developer/code/generate",body),
  aiPreviewDocumentOperation: (body:{operation:string;doctype:string;values?:Record<string,unknown>;name?:string;reason?:string}) => request<any>("POST","/api/ai/developer/document/preview",body),
  aiExecuteDocumentOperation: (body:{confirmation_token:string;confirm:boolean}) => request<any>("POST","/api/ai/developer/document/execute",body),
  aiSuggestCommands: (task:string) => request<any>("POST","/api/ai/developer/commands/suggest",{task}),
  aiAgents: () => request<any[]>("GET","/api/ai/agents"),
  aiSaveAgent: (body:any) => request<any>("POST","/api/ai/agents",body),
  aiRunAgent: (key:string,question:string) => request<any>("POST",`/api/ai/agents/${enc(key)}/run`,{question}),
  activity: (o: { limit?: number; offset?: number; doctype?: string; event_type?: string; scope?: "company"|"mine"; actor?:string; search?:string; from_date?:string; to_date?:string } = {}) =>
    request<ActivityFeed>("GET", `/api/activity${qs(o)}`),
  exportActivity: (o: {doctype?:string;event_type?:string;scope?:"company"|"mine";actor?:string;search?:string;from_date?:string;to_date?:string} = {}) =>
    request<{filename:string;content:string;exported:number}>("GET", `/api/activity/export${qs(o)}`),
  auditCases: (o:{status?:string;limit?:number;offset?:number}={}) =>
    request<{items:AuditCase[];total:number}>("GET",`/api/audit/cases${qs(o)}`),
  createAuditCase: (body:{title:string;description?:string;priority?:string;doctype?:string|null;document_name?:string|null;assigned_to?:string|null}) =>
    request<{id:string;title:string;status:string;priority:string}>("POST","/api/audit/cases",body),
  getAuditCase: (id:string) => request<{case:AuditCase;notes:AuditCaseNote[]}>("GET",`/api/audit/cases/${enc(id)}`),
  updateAuditCase: (id:string,body:{status?:string;assigned_to?:string|null;note?:string}) =>
    request<{case:AuditCase;notes:AuditCaseNote[]}>("PUT",`/api/audit/cases/${enc(id)}`,body),
  documentActivity: (doctype:string,name:string,o: {limit?:number;offset?:number} = {}) =>
    request<ActivityFeed>("GET", `/api/activity/document/${enc(doctype)}/${enc(name)}${qs(o)}`),
  activitySubscriptions: () => request<{id:string;event_type:string;doctype:string|null;enabled:boolean}[]>("GET","/api/activity/subscriptions"),
  saveActivitySubscriptions: (items:{event_type:string;doctype?:string|null;enabled:boolean}[]) =>
    request<{saved:number}>("PUT","/api/activity/subscriptions",{items}),
  notifications: (o: { unread?: boolean; limit?: number; offset?: number } = {}) =>
    request<NotificationList>("GET", `/api/notifications?unread=${o.unread ? 1 : 0}&limit=${o.limit ?? 20}&offset=${o.offset ?? 0}`),
  notificationRead: (name: string) => request<{ read: string }>("POST", `/api/notifications/${enc(name)}/read`),
  notificationsReadAll: () => request<{ marked: number }>("POST", "/api/notifications/read-all"),
  notificationPrefs: () => request<NotificationPrefs>("GET", "/api/notification-preferences"),
  saveNotificationPrefs: (p: NotificationPrefs) => request<{ saved: boolean }>("PUT", "/api/notification-preferences", p),
  layoutGet: (doctype: string) => request<LayoutInfo>("GET", `/api/layout/${enc(doctype)}`),
  layoutSave: (doctype: string, layout: GridLayout, target: "company" | "app" = "company") => request<{ saved: string; layout: GridLayout; note?: string }>("PUT", `/api/layout/${enc(doctype)}`, { layout, target }),
  layoutReset: (doctype: string) => request<{ reset: string }>("DELETE", `/api/layout/${enc(doctype)}`),
  saveFormAppearance: (doctype: string, appearance: Record<string, FieldAppearance>) =>
    request<{ appearance: Record<string, FieldAppearance> }>("PUT", `/api/form-appearance/${enc(doctype)}`, { appearance }),
  resetFormAppearance: (doctype: string) => request<{ reset: string }>("DELETE", `/api/form-appearance/${enc(doctype)}`),
  gridGet: (doctype: string) => request<GridInfo>("GET", `/api/grid/${enc(doctype)}`),
  gridSave: (doctype: string, columns: GridColumn[], target: "company" | "app" = "company") => request<{ columns: GridColumn[]; saved?: string; note?: string }>("PUT", `/api/grid/${enc(doctype)}`, { columns, target }),
  gridReset: (doctype: string) => request<{ reset: string }>("DELETE", `/api/grid/${enc(doctype)}`),
  devtoolsStatus: () => request<{ available: boolean; apps: string[] }>("GET", "/api/devtools/status"),
  devtoolsCatalog: () => request<any>("GET", "/api/devtools/catalog"),
  devtoolsInspect: (doctype: string) => request<any>("GET", `/api/devtools/doctype/${enc(doctype)}`),
  createApplication: (body: { name: string; module?: string; title?: string }) => request<any>("POST", "/api/devtools/apps", body),
  lifecycleCatalog: () => request<{ site: string; apps: { name: string; version: string; installed: boolean; required_apps: string[]; required_velora: string; path: string }[] }>("GET", "/api/devtools/lifecycle"),
  lifecycleInstall: (name: string) => request<any>("POST", `/api/devtools/lifecycle/${enc(name)}/install`, {}),
  lifecycleUninstall: (name: string) => request<any>("POST", `/api/devtools/lifecycle/${enc(name)}/uninstall`, {}),
  validateApplication: (name: string) => request<any>("GET", `/api/devtools/apps/${enc(name)}/validate`),
  deploymentProfiles: () => request<any[]>("GET", "/api/devtools/deploy/profiles"),
  createDeploymentProfile: (body: {name:string;source:string;target:string;apps:string[]}) => request<any>("POST", "/api/devtools/deploy/profiles", body),
  deploymentPlan: (name:string) => request<any>("GET", `/api/devtools/deploy/profiles/${enc(name)}/plan`),
  promoteDeployment: (name:string,dry_run:boolean,confirm=false) => request<any>("POST", `/api/devtools/deploy/profiles/${enc(name)}/promote`, {dry_run,confirm}),

  companyObjects: () => request<{ company: string; objects: any[]; archived: any[] }>("GET", "/api/devtools/objects"),
  companyObjectCreate: (definition: Record<string, unknown>) => request<any>("POST", "/api/devtools/objects", { definition }),
  companyObjectUpdate: (doctype: string, definition: Record<string, unknown>) => request<any>("PUT", `/api/devtools/objects/${enc(doctype)}`, { definition }),
  companyObjectDelete: (doctype: string) => request<any>("DELETE", `/api/devtools/objects/${enc(doctype)}`),
  companyObjectRestore: (doctype: string) => request<any>("POST", `/api/devtools/objects/${enc(doctype)}/restore`),
  customFields: (doctype: string) => request<any[]>("GET", `/api/custom-fields/${enc(doctype)}`),
  addCustomField: (doctype: string, body: Record<string, unknown>) => request<any>("POST", `/api/custom-fields/${enc(doctype)}`, body),
  removeCustomField: (doctype: string, fieldname: string) => request<any>("DELETE", `/api/custom-fields/${enc(doctype)}/${enc(fieldname)}`),
  propertySetters: (doctype: string) => request<any[]>("GET", `/api/property-setters/${enc(doctype)}`),
  savePropertySetter: (doctype: string, body: Record<string, unknown>) => request<any>("POST", `/api/property-setters/${enc(doctype)}`, body),
  removePropertySetter: (doctype: string, fieldname: string, prop: string) => request<any>("DELETE", `/api/property-setters/${enc(doctype)}/${enc(fieldname)}/${enc(prop)}`),
  exportMetadataExtensions: () => request<any>("GET", "/api/metadata-extensions/export"),
  importMetadataExtensions: (body: Record<string, unknown>) => request<any>("POST", "/api/metadata-extensions/import", body),
  creatorPreview: (b: CreatorBody) => request<CreatorReport>("POST", "/api/devtools/doctype-creator/preview", b),
  creatorCreate: (b: CreatorBody) => request<CreatorResult>("POST", "/api/devtools/doctype-creator/create", b),
  runAdhoc: (spec: AdhocSpec) => request<ReportResultData>("POST", "/api/adhoc-report/run", spec),
  exportAdhoc: (spec: AdhocSpec) => postForFile("/api/adhoc-report/export", spec, "report.xlsx"),
  savedReports: () => request<SavedReportInfo[]>("GET", "/api/saved-reports"),
  savedReport: (id: string) => request<SavedReport>("GET", `/api/saved-report/${enc(id)}`),
  createSavedReport: (b: { name: string; spec: AdhocSpec; shared?: boolean }) => request<SavedReport>("POST", "/api/saved-reports", b),
  updateSavedReport: (id: string, b: { name?: string; spec?: AdhocSpec; shared?: boolean }) => request<SavedReport>("PUT", `/api/saved-report/${enc(id)}`, b),
  deleteSavedReport: (id: string) => request<{ deleted: string }>("DELETE", `/api/saved-report/${enc(id)}`),
  savedReportVersions: (id:string) => request<any[]>("GET", `/api/saved-report/${enc(id)}/versions`),
  restoreSavedReportVersion: (id:string,version:number) => request<any>("POST", `/api/saved-report/${enc(id)}/versions/${version}/restore`, {}),

  financialLayouts: () => request<FinancialLayoutInfo[]>("GET", "/api/financial-report-layouts"),
  financialLayout: (id: string) => request<FinancialLayoutInfo>("GET", `/api/financial-report-layout/${enc(id)}`),
  saveFinancialLayout: (body: { name: string; definition: FinancialLayoutDefinition; shared?: boolean }, id?: string) =>
    request<FinancialLayoutInfo>(id ? "PUT" : "POST", id ? `/api/financial-report-layout/${enc(id)}` : "/api/financial-report-layouts", body),
  deleteFinancialLayout: (id: string) => request<{ deleted: string }>("DELETE", `/api/financial-report-layout/${enc(id)}`),
  validateFinancialLayout: (definition: FinancialLayoutDefinition) =>
    request<FinancialLayoutDefinition>("POST", "/api/financial-report-layout/validate", { definition }),
  runFinancialReport: (id: string, filters: Record<string, string | undefined>) =>
    request<FinancialStatementResult>("POST", `/api/financial-report/${enc(id)}/run`, filters),
  financialReportDrilldown: (id: string, body: { row_code: string; column_code: string; filters: Record<string, string | undefined>; limit?: number; account?: string }) =>
    request<FinancialDrilldownResult>("POST", `/api/financial-report/${enc(id)}/drilldown`, body),
  exportFinancialReport: async (id: string, filters: Record<string, string | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value) qs.set(key, value); });
    const response = await raw("GET", `/api/financial-report/${enc(id)}/export.xlsx?${qs.toString()}`);
    if (!response.ok) {
      let message = "Financial report export failed.";
      try { const body = await response.json(); message = body.message ?? message; } catch { /* ignore */ }
      throw new ApiError(response.status, "ExportError", message);
    }
    return response.blob();
  },
  exportFinancialReportPdf: async (id: string, filters: Record<string, string | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value) qs.set(key, value); });
    const response = await raw("GET", `/api/financial-report/${enc(id)}/export.pdf?${qs.toString()}`);
    if (!response.ok) {
      let message = "Financial report PDF export failed.";
      try { const body = await response.json(); message = body.message ?? message; } catch { /* ignore */ }
      throw new ApiError(response.status, "ExportError", message);
    }
    return response.blob();
  },
  themePublic: () => request<ThemeState>("GET", "/api/theme/public"),
  theme: () => request<ThemeState>("GET", "/api/theme"),
  previewTheme: (spec: Partial<ThemeSpec>) => request<ThemeState>("POST", "/api/theme/preview", spec),
  saveTheme: (spec: Partial<ThemeSpec>) => request<ThemeState>("PUT", "/api/theme", spec),
  applicationBranding: () => request<BrandingState>("GET", "/api/application-branding"),
  saveApplicationBranding: (branding: ApplicationBranding) => request<{ branding: ApplicationBranding; saved: boolean }>("PUT", "/api/application-branding", branding),
  reports: () => request<ReportInfo[]>("GET", "/api/reports"),
  reportDef: (name: string) => request<ReportDefinition>("GET", `/api/report/${enc(name)}`),
  runReport: (name: string, filters: Record<string, unknown>) => request<ReportResultData>("POST", `/api/report/${enc(name)}/run`, { filters }),
  async exportReport(name: string, filters: Record<string, unknown>): Promise<{ blob: Blob; filename: string }> {
    const res = await raw("POST", `/api/report/${enc(name)}/export`, { filters });
    if (!res.ok) {
      let j: { error?: string; message?: string } = {};
      try { j = await res.json(); } catch { /* not JSON */ }
      throw new ApiError(res.status, j.error ?? "Error", j.message ?? res.statusText);
    }
    const cd = res.headers.get("Content-Disposition") ?? "";
    return { blob: await res.blob(), filename: /filename="?([^"]+)"?/.exec(cd)?.[1] ?? `${name}.xlsx` };
  },
  doctypes: () => request<DocTypeInfo[]>("GET", "/api/doctypes"),
  meta(doctype: string): Promise<Meta> {
    if (!metaCache.has(doctype)) {
      const p = request<Meta>("GET", `/api/meta/${enc(doctype)}`);
      p.catch(() => metaCache.delete(doctype));
      metaCache.set(doctype, p);
    }
    return metaCache.get(doctype)!;
  },
  list: (doctype: string, p: ListParams = {}, signal?: AbortSignal) => request<Doc[]>("GET", `/api/resource/${enc(doctype)}${qs({ ...p })}`, undefined, signal),
  hrLeavePolicyPreview: (body: { policy: string; leave_period: string; assignment_date: string; selection_mode: string; selected_employees?: { employee: string }[] }) => request<any>("POST", "/api/hr/leave-policy/preview", body),
  aggregate: (doctype: string, fields: string[], filters?: ListParams["filters"]) =>
    request<Record<string, number | null>>("GET", `/api/aggregate/${enc(doctype)}${qs({ fields, filters })}`),
  count: (doctype: string, filters?: ListParams["filters"]) => request<number>("GET", `/api/count/${enc(doctype)}${qs({ filters })}`),
  get: (doctype: string, name: string) => request<Doc>("GET", `/api/resource/${enc(doctype)}/${enc(name)}`),
  create: (doctype: string, doc: Doc) => request<Doc>("POST", `/api/resource/${enc(doctype)}`, doc),
  update: (doctype: string, name: string, doc: Doc) => request<Doc>("PUT", `/api/resource/${enc(doctype)}/${enc(name)}`, doc),
  remove: (doctype: string, name: string, reason?: string) => request<{ deleted: string }>("DELETE", `/api/resource/${enc(doctype)}/${enc(name)}`, {reason: reason || "No reason supplied"}),
  action: (doctype: string, name: string, action: "submit" | "cancel", reason?: string) =>
    request<Doc>("POST", `/api/resource/${enc(doctype)}/${enc(name)}/${action}`, action === "cancel" ? {reason: reason || "No reason supplied"} : {}),
  linkedDocuments: (doctype: string, name: string) =>
    request<{ doctype: string; name: string; dependents: { doctype: string; name: string; via?: string }[] }>("GET", `/api/linked-documents/${enc(doctype)}/${enc(name)}`),
  cancelAll: (doctype: string, name: string, reason: string) =>
    request<{ cancelled: { doctype: string; name: string }[] }>("POST", `/api/cancel-all/${enc(doctype)}/${enc(name)}`, { reason }),
  groupBy: (doctype: string, field: string, filters?: ListParams["filters"]) =>
    request<{ value: string | number | null; count: number }[]>("GET", `/api/group_by/${enc(doctype)}${qs({ field, filters })}`),
  bulk: (doctype: string, body: { action: "delete" | "submit" | "cancel" | "update"; names: string[]; values?: Doc }) =>
    request<{ name: string; ok: boolean; error?: string }[]>("POST", `/api/bulk/${enc(doctype)}`, body),
  async exportXlsx(doctype: string, body: ExportBody): Promise<{ blob: Blob; filename: string; rows: number }> {
    const res = await raw("POST", `/api/export/${enc(doctype)}`, body);
    if (!res.ok) {
      let j: { error?: string; message?: string } = {};
      try { j = await res.json(); } catch { /* not JSON */ }
      throw new ApiError(res.status, j.error ?? "Error", j.message ?? res.statusText);
    }
    const cd = res.headers.get("Content-Disposition") ?? "";
    const filename = /filename="?([^"]+)"?/.exec(cd)?.[1] ?? `${doctype}.xlsx`;
    return { blob: await res.blob(), filename, rows: Number(res.headers.get("X-Velora-Rows") ?? 0) };
  },
  platformCompanies: () => request<any[]>("GET", "/api/platform/companies"),
  platformTenants: () => request<any[]>("GET", "/api/platform/tenants"),
  platformCreateTenant: (name:string) => request<any>("POST", "/api/platform/tenants", {name}),
  platformTenantStatus: (id:string,status:"active"|"suspended") => request<any>("POST", `/api/platform/tenants/${enc(id)}/status`, {status}),
  platformUsers: () => request<any[]>("GET", "/api/platform/users"),
  platformCreateCompany: (b:Record<string,unknown>) => request<any>("POST", "/api/platform/companies", b),
  platformPgAdmin: () => request<{ configured: boolean; user: string; source: string }>("GET", "/api/platform/pg-admin"),
  platformCompanyStatus: (id: string, status: "active" | "suspended") => request<any>("POST", `/api/platform/companies/${encodeURIComponent(id)}/status`, { status }),
  platformDeveloperMode: () => request<{ enabled: boolean }>("GET", "/api/platform/developer-mode"),
  platformSetDeveloperMode: (enabled: boolean) => request<{ enabled: boolean }>("PUT", "/api/platform/developer-mode", { enabled }),
  platformOpenCompany: (id: string) => request<{ id: string; name: string }>("POST", `/api/platform/companies/${encodeURIComponent(id)}/open`, {}),
  platformDropCompany: (id: string, confirm: string) => request<{ id: string; deleted: boolean; note: string }>("DELETE", `/api/platform/companies/${encodeURIComponent(id)}`, { confirm }),
  fmList: (path: string) => request<FmListing>("GET", `/api/filemanager/list${qs({ path })}`),
  fmRead: (path: string) => request<FmFile>("GET", `/api/filemanager/read${qs({ path })}`),
  fmDownloadUrl: (path: string) => `/api/filemanager/download${qs({ path })}`,
  fmWrite: (path: string, content: string, expected_modified?: number) => request<{ path: string; modified: number; size: number }>("PUT", "/api/filemanager/write", { path, content, expected_modified }),
  fmNewFile: (path: string, content = "") => request<{ path: string }>("POST", "/api/filemanager/new-file", { path, content }),
  fmMkdir: (path: string) => request<{ path: string }>("POST", "/api/filemanager/mkdir", { path }),
  fmRename: (path: string, new_name: string) => request<{ path: string }>("POST", "/api/filemanager/rename", { path, new_name }),
  fmDelete: (path: string, recursive = false) => request<{ deleted: string }>("POST", "/api/filemanager/delete", { path, recursive }),
  fmUpload: (folder: string, file: File, overwrite = false) => request<{ path: string; size: number }>("POST", `/api/filemanager/upload${qs({ path: folder, overwrite: overwrite ? "true" : undefined })}`, undefined, undefined, { data: file, filename: file.name }),
  publishCatalog: () => request<PublishCatalog>("GET", "/api/publish/profiles"),
  publishSave: (b: Record<string, unknown>) => request<PublishProfile>("POST", "/api/publish/profiles", b),
  publishDelete: (id: string) => request<{ deleted: string }>("DELETE", `/api/publish/profiles/${encodeURIComponent(id)}`),
  publishStatus: (id: string) => request<{ profile: PublishProfile; git: boolean; ready: boolean; changes: string[]; last_commit: string | null }>("GET", `/api/publish/profiles/${encodeURIComponent(id)}/status`),
  publishCommands: (id: string) => request<{ commands: string }>("GET", `/api/publish/profiles/${encodeURIComponent(id)}/commands`),
  publishTest: (id: string) => request<{ ok: boolean; branches: string[] }>("POST", `/api/publish/profiles/${encodeURIComponent(id)}/test`, {}),
  publishPush: (id: string, message: string) => request<{ pushed: boolean; commit: string; new_commit: boolean; already_up_to_date: boolean; to: string; company_check: { company: string; checked: boolean; note: string } }>("POST", `/api/publish/profiles/${encodeURIComponent(id)}/push`, { message }),
  publishUpload: (id: string, file: File) => request<{ files: number; skipped_count: number; skipped: string[]; stripped_top_folder: boolean }>("POST", `/api/publish-upload/${encodeURIComponent(id)}`, undefined, undefined, { data: file, filename: file.name }),
  platformCopySetupSections: (company:string) => request<any[]>("GET", `/api/platform/companies/${enc(company)}/copy-setup/sections`),
  platformCopySetup: (target:string,b:Record<string,unknown>) => request<any>("POST", `/api/platform/companies/${enc(target)}/copy-setup`, b),
  setupCopySections: () => request<any[]>("GET", "/api/setup-copy/sections"),
  setupCopyExport: (sections:string[]) => request<any>("POST", "/api/setup-copy/export", {sections}),
  setupCopyPreview: (bundle:any,sections:string[]) => request<any>("POST", "/api/setup-copy/preview", {bundle,sections}),
  setupCopyApply: (bundle:any,sections:string[]) => request<any>("POST", "/api/setup-copy/apply", {bundle,sections}),
  workflowTemplates: () => request<any[]>("GET", "/api/workflow-starters"),
  installWorkflowTemplates: (names:string[]) => request<string[]>("POST", "/api/workflow-starters/install", {names}),
  platformDuplicateCompany: (source:string,b:Record<string,unknown>) => request<any>("POST", `/api/platform/companies/${enc(source)}/duplicate`, b),
  platformGrantAccess: (b:Record<string,unknown>) => request<any>("POST", "/api/platform/access/grant", b),
  notificationDeliveries: (status="") => request<any>("GET", `/api/notification-deliveries${qs({status})}`),
  retryNotificationDelivery: (name:string) => request<any>("POST", `/api/notification-deliveries/${enc(name)}/retry`, {}),
  notificationSettings: () => request<any>("GET", "/api/notification-settings"),
  saveNotificationSettings: (body:Record<string,unknown>) => request<any>("PUT", "/api/notification-settings", body),
  testNotificationEmail: (to:string) => request<any>("POST", "/api/notification-settings/test-email", {to}),
  previewNotificationRule: (rule:string,doctype:string,name:string) => request<any>("POST", "/api/notification-rules/preview", {rule,doctype,name}),
  workflows: () => request<any[]>("GET", "/api/workflows"),
  databaseTunePreview: () => request<{ database: string; size_bytes: number; indexes_to_create: string[] }>("GET", "/api/database/tune"),
  databaseTune: () => request<{ database: string; indexes_created: string[]; size_before: number; size_after: number; seconds: number; notes: string[]; statistics_refreshed: boolean; vacuumed: boolean }>("POST", "/api/database/tune"),
  knownRoles: () => request<string[]>("GET", "/api/roles"),
  workflowVersions: (name:string) => request<any[]>("GET", `/api/workflow-versions/${enc(name)}`),
  restoreWorkflowVersion: (name:string,version:number) => request<any>("POST", `/api/workflow-versions/${enc(name)}/${version}/restore`),
  saveWorkflow: (b:Record<string,unknown>) => request<any>("POST", "/api/workflows", b),
  startWorkflow: (workflow:string,doctype:string,document_name:string) => request<any>("POST", `/api/workflows/${enc(workflow)}/start`, {doctype,document_name}),
  workflowAction: (id:string,action:string,comment:string="",step?:string) => request<any>("POST", `/api/workflow-instances/${enc(id)}/action`, {action,comment,step}),
  documentWorkflow: (doctype:string,name:string) => request<any>("GET", `/api/documents/${enc(doctype)}/${enc(name)}/workflow`),
  startDocumentWorkflow: (doctype:string,name:string) => request<any>("POST", `/api/documents/${enc(doctype)}/${enc(name)}/workflow/start`, {}),
  workflowInstance: (id:string) => request<any>("GET", `/api/workflow-instances/${enc(id)}`),
  createWorkflowDelegation: (b:Record<string,unknown>) => request<any>("POST", "/api/workflow-delegations", b),
  workflowInbox: () => request<any[]>("GET", "/api/workflow-inbox"),
  operationalCentre: () => request<any>("GET", "/api/operational-centre"),
  financeRequestPolicy: () => request<any>("GET", "/api/finance/request-policy"),
  financeRequests: (params:Record<string,string>={}) => request<any>("GET", `/api/finance/requests${qs(params)}`),
  financeMyRequests: () => request<any>("GET", "/api/finance/me/requests"),
  financeCreateRequest: (body:Record<string,unknown>) => request<any>("POST", "/api/finance/me/requests", body),
  financeRequestAction: (name:string,body:Record<string,unknown>) => request<any>("POST", `/api/finance/requests/${enc(name)}/action`, body),
  financeRequestAnalytics: () => request<any>("GET", "/api/finance/requests/analytics"),

  workflowTasks: (status?:string) => request<any[]>("GET", `/api/workflow-tasks${status?`?status=${enc(status)}`:""}`),
  createWorkflowTask: (id:string,b:Record<string,unknown>) => request<any>("POST", `/api/workflow-instances/${enc(id)}/tasks`, b),
  completeWorkflowTask: (id:string,result:Record<string,unknown>={}) => request<any>("POST", `/api/workflow-tasks/${enc(id)}/complete`, {result}),
  startChildWorkflow: (id:string,workflow:string,resume_state:string) => request<any>("POST", `/api/workflow-instances/${enc(id)}/children`, {workflow,resume_state}),
  subscribeWorkflowEvent: (id:string,event_name:string,action:string,filters:Record<string,unknown>={}) => request<any>("POST", `/api/workflow-instances/${enc(id)}/event-subscriptions`, {event_name,action,filters}),
  publishWorkflowEvent: (name:string,payload:Record<string,unknown>={}) => request<any>("POST", `/api/workflow-events/${enc(name)}/publish`, {payload}),
  workflowAnalytics: () => request<any>("GET", "/api/workflow-analytics"),
  simulateWorkflow: (name:string,document:Record<string,unknown>,state?:string) => request<any>("POST", `/api/workflows/${enc(name)}/simulate`, {document,state}),
  setWorkflowSla: (id:string,minutes:number,escalation_levels:any[]=[]) => request<any>("POST", `/api/workflow-instances/${enc(id)}/sla`, {minutes,escalation_levels}),
  saveWorkflowAutomation: (b:Record<string,unknown>) => request<any>("POST", "/api/workflow-automations", b),
  rules: (scope_name?: string, doctype?: string) => request<any[]>("GET", `/api/rules${qs({ scope_name, doctype })}`),
  rule: (name: string) => request<any>("GET", `/api/rule/${enc(name)}`),
  saveRule: (body: Record<string, unknown>) => request<any>("POST", "/api/rules", body),
  updateRule: (name: string, body: Record<string, unknown>) => request<any>("PUT", `/api/rule/${enc(name)}`, body),
  deleteRule: (name: string) => request<any>("DELETE", `/api/rule/${enc(name)}`),
  testRule: (name: string, document: Record<string, unknown>, context: Record<string, unknown> = {}) =>
    request<any>("POST", `/api/rule/${enc(name)}/test`, { document, context }),
  dashboards: () => request<any[]>("GET", "/api/dashboards"),
  runDashboard: (id:string) => request<any>("GET", `/api/dashboards/${enc(id)}/run`),
  saveDashboard: (b:Record<string,unknown>) => request<any>("POST", "/api/dashboards", b),
  duplicateDashboard: (id:string,name:string) => request<any>("POST", `/api/dashboards/${encodeURIComponent(id)}/duplicate`, {name}),
  deleteDashboard: (id:string) => request<any>("DELETE", `/api/dashboards/${encodeURIComponent(id)}`),
  correctionInbox: (o:Record<string,unknown>={}) => request<any>("GET", `/api/document-corrections/inbox${qs(o)}`),
  deletedDocuments: (o:Record<string,unknown>={}) => request<any>("GET", `/api/document-corrections/deleted${qs(o)}`),
  deletedDocument: (id:string) => request<any>("GET", `/api/document-corrections/deleted/${enc(id)}`),
  restoreDeletedDocument: (id:string) => request<any>("POST", `/api/document-corrections/deleted/${enc(id)}/restore`),
  workspaces: () => request<any[]>("GET", "/api/workspaces"),
  runWorkspace: (id:string) => request<any>("GET", `/api/workspaces/${enc(id)}/run`),
  landingWorkspace: () => request<any>("GET", "/api/workspaces/landing"),
  setDefaultWorkspace: (id:string) => request<any>("POST", `/api/workspaces/${enc(id)}/default`),
  saveWorkspace: (scope:"personal"|"company", body:Record<string,unknown>) => request<any>("POST", `/api/workspaces/${scope}`, body),
  deleteWorkspace: (id:string) => request<any>("DELETE", `/api/workspaces/${enc(id)}`),
  printFormats: () => request<any[]>("GET", "/api/print-formats"),
  printFormatsFor: (doctype:string) => request<any[]>("GET", `/api/print-formats/for/${enc(doctype)}`),
  savePrintFormat: (b:Record<string,unknown>) => request<any>("POST", "/api/print-formats", b),
  websitePages: () => request<any[]>("GET", "/api/website/pages"),
  saveWebsitePage: (b:Record<string,unknown>) => request<any>("POST", "/api/website/pages", b),
  async exportMigrationPackage(b:Record<string,unknown>):Promise<{blob:Blob;filename:string}>{
    const res=await raw("POST","/api/data-migration/package/export",b);if(!res.ok){let j:any={};try{j=await res.json();}catch{}throw new ApiError(res.status,j.error||"Error",j.message||res.statusText);}return {blob:await res.blob(),filename:/filename="?([^"]+)"?/.exec(res.headers.get("Content-Disposition")||"")?.[1]||"velora_data_migration.zip"};
  },
  async importMigrationPackage(file:File,dryRun:boolean):Promise<any>{
    const res=await raw("POST",`/api/data-migration/package/import?dry_run=${dryRun?1:0}`,undefined,undefined,{data:file,filename:file.name});let j:any={};try{j=await res.json();}catch{}if(!res.ok)throw new ApiError(res.status,j.error||"Error",j.message||res.statusText);return j.data;
  },
  shareDocument: (doctype:string,name:string,b:Record<string,unknown>) => request<any>("POST",`/api/share/${enc(doctype)}/${enc(name)}`,b),
  emailDocument: (doctype:string,name:string,b:Record<string,unknown>) => request<any>("POST",`/api/email/${enc(doctype)}/${enc(name)}`,b),
  files: (doctype:string,name:string) => request<any[]>("GET",`/api/files${qs({doctype,docname:name})}`),
  uploadAttachment: (doctype:string,name:string,file:File,description="") =>
    request<any>("POST",`/api/files${qs({doctype,docname:name,description})}`,undefined,undefined,{data:file,filename:file.name}),
  deleteAttachment: (id:string) => request<any>("DELETE",`/api/files/${enc(id)}`),
  async downloadAttachment(id:string):Promise<{blob:Blob;filename:string}> { return getForFile(`/api/files/${enc(id)}`, "attachment"); },
  customScripts: () => request<any[]>("GET", "/api/custom-scripts"),
  validateCustomScript: (b:Record<string,unknown>) => request<any>("POST", "/api/custom-scripts/validate", b),
  customScriptVersions: (id:string) => request<any[]>("GET", `/api/custom-scripts/${enc(id)}/versions`),
  restoreCustomScript: (id:string,version:number) => request<any>("POST", `/api/custom-scripts/${enc(id)}/restore/${version}`),
  saveCustomScript: (b:Record<string,unknown>) => request<any>("POST", "/api/custom-scripts", b),
  deleteCustomScript: (id:string) => request<any>("DELETE", `/api/custom-scripts/${enc(id)}`),
  documentPricing(doctype: string, body: Record<string, unknown>): Promise<Record<string, unknown>[]> {
    return request("POST", `/api/document-pricing/${enc(doctype)}`, body);
  },
  async clientScript(doctype: string, kind: "form" | "list"): Promise<string> {
    const res = await raw("GET", `/api/client_script/${enc(doctype)}${qs({ kind })}`);
    return res.ok ? res.text() : "";
  },
};

export async function loadAuthConfig(): Promise<AuthMode> {
  try {
    const res = await fetch("/api/auth/config");
    const j = await res.json();
    authMode = j?.data?.mode === "password" ? "password" : "developer";
  } catch { authMode = "developer"; }
  return authMode;
}

export const auth = {
  login: (email: string, password: string, totp_code?: string) => request<Profile>("POST", "/api/auth/login", { email, password, totp_code }),
  me: () => request<Profile>("GET", "/api/auth/me"),
  logout: () => request<{ signed_out: boolean }>("POST", "/api/auth/logout"),
  setDefaultCompany: (company_id: string | null) => request<{ default_company: string | null }>("POST", "/api/auth/default-company", { company_id: company_id ?? "" }),
  switchCompany: (company_id: string) => request<{ id: string; name: string; roles: string[] }>("POST", "/api/auth/switch-company", { company_id }),
  mfaStatus: () => request<{enabled:boolean}>("GET", "/api/auth/mfa/status"),
  mfaSetup: () => request<{secret:string;otpauth_uri:string}>("POST", "/api/auth/mfa/setup"),
  mfaConfirm: (code:string) => request<{enabled:boolean}>("POST", "/api/auth/mfa/confirm", {code}),
  mfaDisable: (password:string) => request<{enabled:boolean}>("POST", "/api/auth/mfa/disable", {password}),
  loginBranding: () => request<{app_name:string;tagline:string;logo_url:string}>("GET", "/api/auth/login-branding"),
};

export const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

export interface OutstandingInvoice { invoice: string; invoice_date: string | null; due_date: string | null; currency: string; invoice_total: number | string; amount_settled: number | string; outstanding: number | string; payment_status: string }
export interface SettlementAllocation { allocations: (OutstandingInvoice & { allocate: number | string })[]; allocated: number | string; unapplied: number | string; method: string; explanation: string; lines: Record<string, unknown>[] }

// ---- Bank Reconciliation centre (routes installed by the velora_erp app) ----------------------------------
export interface BankLine { id: string; date: string; direction: "Receipt" | "Payment"; amount: string; description?: string; reference?: string; status: string; proposed_account?: string | null; posting_batch?: string | null; ignore_reason?: string | null }
export interface BankRecord { id: string; date: string; signed: string; reference?: string; description?: string; party?: string | null; source?: string }
export interface BankGroup { group: string; method: string; confidence: number; reason?: string; status: string; locked: boolean; lines: BankLine[]; records: BankRecord[] }
export interface BankWorkbench {
  bank_account: string; gl_account: string; currency: string; ledger_balance: string; matched_total: number;
  settings: { auto_accept_threshold: number; date_tolerance_days: number; auto_reconcile: boolean; auto_post_coded: boolean };
  unmatched_lines: BankLine[]; ignored_lines: BankLine[]; unmatched_records: BankRecord[]; suggestions: BankGroup[]; matched: BankGroup[];
}
export interface BankCompute {
  currency: string; ledger_balance: number | string; deposits_in_transit: number | string; outstanding_payments: number | string; adjusted_bank_balance: number | string;
  unrecorded_receipts: number | string; unrecorded_payments: number | string; adjusted_book_balance: number | string; variance: number | string; statement_check: number | string;
  statement_lines_total: number; matched_lines: number; suggested_lines: number; unmatched_lines: number; match_rate: number;
  items: { category: string; item_date: string; reference?: string; description?: string; amount: number | string }[];
}
const BR = "/api/bank-reconciliation";
export const bankRec = {
  workbench: (bank_account: string, to_date?: string) => request<BankWorkbench>("GET", `${BR}/workbench${qs({ bank_account, to_date })}`),
  compute: (bank_account: string, to_date: string, closing: string, opening?: string, from_date?: string) => request<BankCompute>("GET", `${BR}/compute${qs({ bank_account, to_date, closing, opening, from_date })}`),
  importStatement: (b: { bank_account: string; filename: string; content?: string; content_base64?: string; amount_sign?: string }) => request<Record<string, any>>("POST", `${BR}/import`, b),
  auto: (bank_account: string, post?: boolean) => request<Record<string, any>>("POST", `${BR}/auto`, { bank_account, post }),
  match: (bank_account: string, lines: string[], records: string[], reason?: string) => request<unknown>("POST", `${BR}/match`, { bank_account, lines, records, reason }),
  confirm: (groups: string[]) => request<{ confirmed: number }>("POST", `${BR}/confirm`, { groups }),
  reject: (groups: string[]) => request<{ rejected: number }>("POST", `${BR}/reject`, { groups }),
  unmatch: (groups: string[]) => request<{ released: number }>("POST", `${BR}/unmatch`, { groups }),
  ignore: (lines: string[], reason: string) => request<{ ignored: number }>("POST", `${BR}/ignore`, { lines, reason }),
  restore: (lines: string[]) => request<{ restored: number }>("POST", `${BR}/restore`, { lines }),
  post: (bank_account: string) => request<{ batch: string | null; lines: number }>("POST", `${BR}/post`, { bank_account }),
};

// ---- Update Centre (platform administrators) ----------------------------------------------------------------
export interface UpdateFile { file: string; package: string | null; version: string | null; installed: string | null; newer: boolean; size?: number; note: string }
export interface UpdateJob { id: string; state: "running" | "done" | "failed"; started: string; finished?: string; error?: string; plan?: string[]; steps: { name: string; state: string; detail: string }[]; log: string[] }
export interface UpdateState { drop_folder: string; files: UpdateFile[]; update_available: boolean; current: { velora: string; apps: Record<string, string> }; running: UpdateJob | null; last: UpdateJob | null; restart_command: string }
export const updateCentre = {
  state: () => request<UpdateState>("GET", "/api/update-centre"),
  upload: (file: File) => request<{ file: string; size: number }>("POST", "/api/update-centre/upload", undefined, undefined, { data: file, filename: file.name }),
  run: () => request<{ job: string }>("POST", "/api/update-centre/run", {}),
  job: (id: string) => request<UpdateJob>("GET", `/api/update-centre/job/${encodeURIComponent(id)}`),
  remove: (name: string) => request<{ removed: string }>("DELETE", `/api/update-centre/files/${encodeURIComponent(name)}`),
  saveSettings: (restart_command: string) => request<{ restart_command: string }>("PUT", "/api/update-centre/settings", { restart_command }),
};

// ---- Budget Workbench ---------------------------------------------------------------------------------------
export const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"] as const;
export type MonthKey = (typeof MONTHS)[number];
export type PlanRow = { account: string; cost_centre?: string | null; branch?: string | null; total?: number; previous_year_actual?: number; row_notes?: string | null } & Partial<Record<MonthKey, number>>;
export interface BudgetVarianceRow { account: string; cost_centre?: string | null; branch?: string | null; root_type?: string; annual_budget: number; budget_to_date: number; actual_to_date: number; variance: number; variance_percent: number | null; utilisation_percent: number | null; better_when: "lower" | "higher"; projected_year_end: number | null }
export interface BudgetScenario { scenario_name: string; scenario_type?: string; adjustment_percent: number; probability: number; is_active: boolean; total_budget: number; variance_from_base: number; variance_percent: number | null; expected_total: number | null }
export interface BudgetWorkbench {
  budget: { name: string; budget_name: string; financial_year: string; budget_type?: string; budget_against?: string; is_group_budget: boolean; parent_budget?: string | null; approval_status: string; budget_status: string; docstatus: number; currency: string; allocate_by?: string; allocation_method?: string };
  year: { start: string; end: string; months: Record<string, [string, string]> };
  through_month: number; plan: PlanRow[]; month_totals: Record<MonthKey, number>; actual_months: Record<MonthKey, number>; total: number;
  variance: BudgetVarianceRow[]; allocation: { branch?: string; cost_centre?: string; basis_value?: number; allocation_percent: number; allocated_amount: number; is_locked?: boolean }[]; allocation_dimension: string | null;
  scenarios: BudgetScenario[]; scenario_months: { scenario_name: string; months: Record<MonthKey, number> }[];
  children: { name: string; budget_name: string; total_budget_amount: number; approval_status: string; budget_status: string }[]; children_total: number;
}
const BP = "/api/budget-planner";
export const budgetPlanner = {
  workbench: (budget: string, through_month?: number) => request<BudgetWorkbench>("GET", `${BP}/workbench${qs({ budget, through_month })}`),
  propose: (financial_year: string, method: string, growth_percent: number) => request<{ rows: PlanRow[] }>("POST", `${BP}/propose`, { financial_year, method, growth_percent }),
  project: (financial_year: string, rows: PlanRow[], method: string, growth_percent: number) => request<{ rows: PlanRow[] }>("POST", `${BP}/project`, { financial_year, rows, method, growth_percent }),
  allocatePreview: (allocate_by: string, method: string, total: number, allocations: Record<string, unknown>[]) => request<{ rows: BudgetWorkbench["allocation"] }>("POST", `${BP}/allocate-preview`, { allocate_by, method, total, allocations }),
};

// ---- Portal access (staff) ----------------------------------------------------------------------------------
export interface PortalAccountRow { name: string; email: string; full_name: string; portal_type: "Customer" | "Supplier"; customer?: string | null; supplier?: string | null; status: "Active" | "Suspended"; last_invited?: string | null }
const PA = "/api/portal-admin";
export const portalAdmin = {
  accounts: () => request<{ items: PortalAccountRow[] }>("GET", `${PA}/accounts`).then(d => d.items),
  invite: (b: { email: string; full_name: string; portal_type: string; party: string }) => request<{ email: string; temporary_password: string }>("POST", `${PA}/invite`, b),
  reset: (email: string) => request<{ email: string; temporary_password: string }>("POST", `${PA}/reset`, { email }),
  setStatus: (email: string, status: string) => request<{ email: string; status: string }>("POST", `${PA}/status`, { email, status }),
};

// ---- Controls Check -----------------------------------------------------------------------------------------
export interface ControlFinding { code: string; scope: string; severity: "Error" | "Warning" | "Info"; title: string; why: string; count: number; amount: number | null; rows: Record<string, string | number>[]; truncated: boolean }
export interface ControlsResult { from_date: string; to_date: string; scope: string; stale_days: number; findings: ControlFinding[]; summary: { checks: number; with_findings: number; errors: number; warnings: number } }
export const controlsCheck = {
  run: (from_date: string, to_date: string, scope: string, stale_days: number) => request<ControlsResult>("GET", `/api/controls-check${qs({ from_date, to_date, scope, stale_days })}`),
};

// ---- Investments, Support Desk, Broadcast Centre, GL Review -------------------------------------------------
export interface Alloc { label: string; amount: number; percent: number; over_limit?: boolean }
export interface PortfolioHolding { name: string; investment_name: string; investment_class: string; counterparty: string | null; carrying_amount: number; effective_yield: number; maturity_date: string | null; days_to_maturity: number | null; accrued_receivable: number; measurement: string }
export interface Portfolio {
  as_of: string; currency_note: string;
  kpis: { carrying: number; cost: number; unrealised: number; accrued_receivable: number; income_ytd: number; tax_withheld_ytd: number; weighted_yield: number; holdings: number };
  by_group: Alloc[]; by_class: Alloc[]; by_counterparty: Alloc[]; ladder: { label: string; amount: number; count: number }[];
  upcoming: { date: string; event: string; investment: string; name: string; amount: number }[]; holdings: PortfolioHolding[];
  alerts: { kind: string; severity: "critical" | "warning" | "info"; message: string }[]; limits: { counterparty_percent: number; asset_group_percent: number };
}
export const investments = {
  portfolio: (as_of?: string) => request<Portfolio>("GET", `/api/investments/portfolio${qs({ as_of })}`),
  accrueAll: (as_of?: string) => request<{ made: string[]; failed: { investment: string; error: string }[] }>("POST", "/api/investments/accrue", { as_of }),
};

export interface SupportRow { name: string; subject: string; status: string; priority: string; category: string | null; customer: string | null; assigned_to: string | null; team: string | null; response_sla: string; resolution_sla: string; resolution_due: string | null; first_response_due: string | null; escalation_level: number; age_hours: number }
export interface SupportSummary {
  kpis: { open: number; unassigned: number; mine: number; at_risk: number; breached: number; waiting: number; resolved_today: number; avg_first_response_hours: number | null; avg_resolution_hours: number | null; sla_met_percent: number | null; satisfaction: number | null };
  queue: SupportRow[]; workload: { agent: string; open: number; breached: number }[]; ageing: { bucket: string; count: number }[]; trend: { date: string; opened: number; resolved: number }[]; categories: { category: string; count: number }[];
}
export const support = {
  summary: () => request<SupportSummary>("GET", "/api/support/summary"),
  reply: (name: string, message: string, kind: string, status?: string) => request<{ name: string; status: string }>("POST", `/api/support/tickets/${enc(name)}/reply`, { message, kind, status }),
  assign: (name: string, user: string) => request<{ name: string; assigned_to: string | null }>("POST", `/api/support/tickets/${enc(name)}/assign`, { user }),
};

export interface BroadcastRow { name: string; title: string; channel: string; status: string; total_recipients: number; sent_count: number; failed_count: number; opted_out_count: number; scheduled_for: string | null; started_on: string | null }
export interface BroadcastSummary {
  recent: BroadcastRow[]; scheduled: BroadcastRow[]; running: BroadcastRow[]; by_channel: Record<string, { broadcasts: number; sent: number; failed: number }>;
  opt_outs: number; gateways: { Email: boolean; SMS: boolean; WhatsApp: boolean; base_url: boolean }; outbox: Record<string, number>;
}
export const broadcasts = {
  summary: () => request<BroadcastSummary>("GET", "/api/broadcast-centre/summary"),
  build: (name: string) => request<{ recipients: number; will_send: number; skipped: number; opted_out: number }>("POST", `/api/broadcasts/${enc(name)}/build`),
  preview: (name: string) => request<{ subject: string; body: string; html?: string; recipient: string }>("GET", `/api/broadcasts/${enc(name)}/preview`),
  send: (name: string, send_at?: string) => request<{ status: string; queued?: number; scheduled_for?: string; recipients?: number }>("POST", `/api/broadcasts/${enc(name)}/send`, { send_at }),
  test: (name: string, to: string) => request<{ sent: boolean; to?: string; error?: string }>("POST", `/api/broadcasts/${enc(name)}/test`, { to }),
  cancel: (name: string) => request<{ stopped: number }>("POST", `/api/broadcasts/${enc(name)}/cancel`),
  sync: (name: string) => request<{ status: string; sent: number; failed: number; waiting: number }>("POST", `/api/broadcasts/${enc(name)}/sync`),
  testGateway: (channel: string, to: string) => request<{ sent: boolean; error?: string }>("POST", "/api/notification-settings/test-gateway", { channel, to }),
  testRule: (rule: string, doc: string, to: string) => request<{ subject: string; results: { channel: string; sent: boolean; error?: string }[] }>("POST", `/api/notify/rules/${enc(rule)}/test`, { doc, to }),
};

export interface GlFlag { account: string; code: string; name: string; root_type: string; current: number; prior: number; change: number; change_percent: number; reasons: string[] }
export interface GlReview {
  period: { from: string; to: string; prior_from: string; prior_to: string; threshold_percent: number; minimum_amount: number };
  summary: { accounts_current: number; accounts_prior: number; flagged: number; suspense_lines: number; journals_flagged: number; months_clustered: number };
  flagged_accounts: GlFlag[]; top_movements: GlFlag[]; suspense: { account: string; date: string; document: string; debit: number; credit: number; description: string }[];
  period_end: { month: string; total: number; last_three_days: number; share_percent: number; reason: string }[]; journals: { document: string; date: string; amount: number; reasons: string[] }[];
}
export const glReview = {
  run: (from_date: string, to_date: string, prior_from: string, prior_to: string, threshold_pct: number, min_amount: number) =>
    request<GlReview>("GET", `/api/gl-review${qs({ from_date, to_date, prior_from, prior_to, threshold_pct, min_amount })}`),
};

/** For client scripts: call an /api/ route of this application. */
export function apiCall<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  if (!/^\/api\/[A-Za-z0-9_\-./%?=&,:]*$/.test(path) || path.includes("..")) throw new Error("A client script can only call an /api/ route.");
  return request<T>(method.toUpperCase(), path, body);
}
