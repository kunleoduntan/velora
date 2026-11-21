export interface PortalUser { id: string; email: string; full_name: string; roles: string[] }
export interface Money { currency: string; outstanding: number | string; overdue: number | string; open_invoices: number }
export interface Invoice { name: string; invoice_date: string; due_date?: string; currency: string; grand_total: number | string; amount_settled: number | string; outstanding: number | string; overdue_days: number; state: "Open" | "Overdue" | "Paid"; party_reference?: string; narration?: string }
export interface OrderRow { name: string; document_date: string; currency: string; grand_total: number | string; document_status: string; narration?: string }
export interface Complaint { name: string; complaint_date: string; category: string; severity: string; description: string; resolution_status: string; resolution?: string; sales_invoice?: string }
export interface Overview {
  who: { name: string; email: string };
  party: { code: string; email?: string; phone?: string; currency?: string; billing_address?: string; payment_terms?: string; credit_limit?: number | string; customer_name?: string; supplier_name?: string };
  summary: { open_invoices: number; overdue_invoices: number; by_currency: Money[] };
  ageing: { currency: string; total: number | string; buckets: { label: string; amount: number | string }[] }[];
  recent_invoices: Invoice[]; open_orders: number; open_complaints?: number;
}

async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, credentials: "same-origin", headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  let j: { data?: T; message?: string; detail?: string } = {};
  try { j = await r.json(); } catch { /* an empty or non-JSON reply */ }
  if (!r.ok) throw new Error(j.message || (typeof j.detail === "string" ? j.detail : "") || (r.status === 403 ? "Please sign in again." : "Something went wrong. Please try again."));
  return j.data as T;
}
const res = <T,>(key: string, params: Record<string, unknown> = {}) => call<T>("GET", `/api/portal/resources/${key}?params=${encodeURIComponent(JSON.stringify(params))}`);

export const portal = {
  me: () => call<{ user: PortalUser }>("GET", "/api/portal/auth/me").then(d => d.user),
  login: (email: string, password: string) => call<{ user: PortalUser }>("POST", "/api/portal/auth/login", { email, password }).then(d => d.user),
  logout: () => call<unknown>("POST", "/api/portal/auth/logout", {}),
  changePassword: (current_password: string, new_password: string) => call<unknown>("POST", "/api/portal/auth/change-password", { current_password, new_password }),
  overview: (kind: "customer" | "supplier") => res<Overview>(`${kind}.overview`),
  invoices: (kind: "customer" | "supplier", status?: string) => res<{ items: Invoice[] }>(`${kind}.invoices`, status ? { status } : {}).then(d => d.items),
  orders: (kind: "customer" | "supplier") => res<{ items: OrderRow[] }>(`${kind}.orders`).then(d => d.items),
  complaints: () => res<{ items: Complaint[] }>("customer.complaints").then(d => d.items),
  raiseComplaint: (b: { category: string; severity: string; description: string; sales_invoice?: string }) => call<{ name: string }>("POST", "/api/portal/actions/customer.complaint", b),
};

export const portalKind = (u: PortalUser): "customer" | "supplier" | null => (u.roles.includes("Customer Portal") ? "customer" : u.roles.includes("Supplier Portal") ? "supplier" : null);
export const fmt = (v: unknown, cur = "") => `${cur} ${Number(v ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
