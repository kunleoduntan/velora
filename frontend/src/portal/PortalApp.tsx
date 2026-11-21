import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { fmt, portal, portalKind } from "./portalApi";
import type { Complaint, Invoice, OrderRow, Overview, PortalUser } from "./portalApi";

const COMPLAINT_CATEGORIES = ["Product Quality", "Wrong Item", "Short Delivery", "Late Delivery", "Pricing or Billing", "Service", "Warranty", "Other"];
type View = "home" | "invoices" | "orders" | "support" | "account";
const viewFromHash = (): View => { const h = location.hash.replace(/^#\/?/, ""); return (["invoices", "orders", "support", "account"] as View[]).includes(h as View) ? (h as View) : "home"; };

function Message({ kind, children }: { kind: "error" | "ok"; children: ReactNode }) { return <div className={`pt-msg pt-${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</div>; }

function SignIn({ onUser }: { onUser: (u: PortalUser) => void }) {
  const [email, setEmail] = useState(""), [password, setPassword] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) { e.preventDefault(); setBusy(true); setError(""); try { onUser(await portal.login(email, password)); } catch (x) { setError(x instanceof Error ? x.message : "Unable to sign in"); } finally { setBusy(false); } }
  return (
    <main className="pt-center"><form className="pt-card pt-signin" onSubmit={submit}>
      <div className="pt-mark">Velora</div><h1>Sign in to your portal</h1><p className="pt-muted">View your invoices, orders and requests in one place.</p>
      {error && <Message kind="error">{error}</Message>}
      <label>Email address<input type="email" autoComplete="username" required value={email} onChange={e => setEmail(e.target.value)} /></label>
      <label>Password<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></label>
      <button className="pt-btn pt-primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      <small className="pt-muted">Your sign-in was sent to you by the company. If you have forgotten it, ask them to reset it.</small>
    </form></main>
  );
}

function Table<T>({ rows, cols, empty, onRow }: { rows: T[]; cols: { head: string; cell: (r: T) => ReactNode; num?: boolean }[]; empty: string; onRow?: (r: T) => void }) {
  if (!rows.length) return <p className="pt-muted">{empty}</p>;
  return <div className="pt-scroll"><table className="pt-table"><thead><tr>{cols.map(c => <th key={c.head} className={c.num ? "pt-num" : ""}>{c.head}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={i} onClick={onRow ? () => onRow(r) : undefined}>{cols.map(c => <td key={c.head} className={c.num ? "pt-num" : ""}>{c.cell(r)}</td>)}</tr>)}</tbody></table></div>;
}
const Badge = ({ s }: { s: string }) => <span className={`pt-badge pt-b-${s.toLowerCase().replace(/\W+/g, "-")}`}>{s}</span>;

function Home({ kind }: { kind: "customer" | "supplier" }) {
  const [o, setO] = useState<Overview | null>(null), [error, setError] = useState("");
  useEffect(() => { portal.overview(kind).then(setO).catch(e => setError(e.message)); }, [kind]);
  if (error) return <Message kind="error">{error}</Message>;
  if (!o) return <p className="pt-muted">Loading…</p>;
  const name = o.party.customer_name || o.party.supplier_name || o.party.code;
  return <>
    <h1>Welcome, {o.who.name}</h1><p className="pt-muted">{name}{o.party.payment_terms ? ` · Terms: ${o.party.payment_terms}` : ""}</p>
    <div className="pt-kpis">
      {o.summary.by_currency.length ? o.summary.by_currency.map(m => <div className="pt-kpi" key={m.currency}><span>{kind === "customer" ? "You owe" : "We owe you"} ({m.currency})</span><strong>{fmt(m.outstanding)}</strong><small className={Number(m.overdue) ? "pt-bad" : ""}>{Number(m.overdue) ? `${fmt(m.overdue)} overdue` : "Nothing overdue"}</small></div>)
        : <div className="pt-kpi"><span>{kind === "customer" ? "You owe" : "We owe you"}</span><strong>0.00</strong><small>All settled</small></div>}
      <div className="pt-kpi"><span>Open invoices</span><strong>{o.summary.open_invoices}</strong><small>{o.summary.overdue_invoices} overdue</small></div>
      <div className="pt-kpi"><span>Open orders</span><strong>{o.open_orders}</strong>{kind === "customer" && <small>{o.open_complaints ?? 0} open request(s)</small>}</div>
    </div>
    {o.ageing.map(a => { const total = Number(a.total) || 1; return <section className="pt-card" key={a.currency}><h2>How old is the balance? ({a.currency})</h2>
      <div className="pt-ageing" role="img" aria-label="Balance by age">{a.buckets.map((b, i) => <span key={b.label} className={`pt-seg pt-seg-${i}`} style={{ flexGrow: Math.max(Number(b.amount) / total, 0.0001) }} title={`${b.label}: ${fmt(b.amount)}`} />)}</div>
      <ul className="pt-legend">{a.buckets.map((b, i) => <li key={b.label}><i className={`pt-seg-${i}`} /> {b.label}<strong>{fmt(b.amount)}</strong></li>)}</ul></section>; })}
    <section className="pt-card"><h2>Recent invoices</h2><Table rows={o.recent_invoices} empty="No invoices yet." cols={[
      { head: "Invoice", cell: r => r.name }, { head: "Date", cell: r => r.invoice_date }, { head: "Due", cell: r => r.due_date || "—" }, { head: "Amount", num: true, cell: r => fmt(r.grand_total, r.currency) },
      { head: "Balance", num: true, cell: r => fmt(r.outstanding, r.currency) }, { head: "Status", cell: r => <Badge s={r.state} /> }]} /></section>
  </>;
}

function Invoices({ kind }: { kind: "customer" | "supplier" }) {
  const [rows, setRows] = useState<Invoice[]>([]), [status, setStatus] = useState("all"), [error, setError] = useState(""), [q, setQ] = useState("");
  useEffect(() => { portal.invoices(kind, status).then(setRows).catch(e => setError(e.message)); }, [kind, status]);
  const shown = rows.filter(r => !q || `${r.name} ${r.party_reference || ""} ${r.narration || ""}`.toLowerCase().includes(q.toLowerCase()));
  const total = shown.reduce((s, r) => s + Number(r.outstanding), 0);
  return <><h1>Invoices</h1>{error && <Message kind="error">{error}</Message>}
    <div className="pt-bar"><div className="pt-tabs" role="tablist">{["all", "open", "overdue", "paid"].map(s => <button key={s} role="tab" aria-pressed={status === s} onClick={() => setStatus(s)}>{s[0].toUpperCase() + s.slice(1)}</button>)}</div>
      <input type="search" placeholder="Search invoices" aria-label="Search invoices" value={q} onChange={e => setQ(e.target.value)} /></div>
    <Table rows={shown} empty="No invoices match." cols={[{ head: "Invoice", cell: r => r.name }, { head: "Reference", cell: r => r.party_reference || "—" }, { head: "Date", cell: r => r.invoice_date }, { head: "Due", cell: r => r.due_date || "—" },
      { head: "Amount", num: true, cell: r => fmt(r.grand_total, r.currency) }, { head: "Paid", num: true, cell: r => fmt(r.amount_settled, r.currency) }, { head: "Balance", num: true, cell: r => fmt(r.outstanding, r.currency) },
      { head: "Status", cell: r => <>{<Badge s={r.state} />}{r.overdue_days ? <small className="pt-bad"> {r.overdue_days}d</small> : null}</> }]} />
    {shown.length > 0 && <p className="pt-total">Balance shown: <strong>{fmt(total)}</strong> <small className="pt-muted">(amounts in different currencies are added as numbers only)</small></p>}</>;
}

function Orders({ kind }: { kind: "customer" | "supplier" }) {
  const [rows, setRows] = useState<OrderRow[]>([]), [error, setError] = useState("");
  useEffect(() => { portal.orders(kind).then(setRows).catch(e => setError(e.message)); }, [kind]);
  return <><h1>Orders</h1>{error && <Message kind="error">{error}</Message>}<Table rows={rows} empty="No orders yet." cols={[{ head: "Order", cell: r => r.name }, { head: "Date", cell: r => r.document_date },
    { head: "Amount", num: true, cell: r => fmt(r.grand_total, r.currency) }, { head: "Status", cell: r => <Badge s={r.document_status} /> }, { head: "Note", cell: r => r.narration || "—" }]} /></>;
}

function Support() {
  const [rows, setRows] = useState<Complaint[]>([]), [invoices, setInvoices] = useState<Invoice[]>([]), [error, setError] = useState(""), [ok, setOk] = useState(""), [busy, setBusy] = useState(false);
  const [f, setF] = useState({ category: "Service", severity: "Medium", description: "", sales_invoice: "" });
  const load = useCallback(() => { portal.complaints().then(setRows).catch(e => setError(e.message)); }, []);
  useEffect(() => { load(); portal.invoices("customer").then(setInvoices).catch(() => undefined); }, [load]);
  async function send(e: FormEvent) { e.preventDefault(); setBusy(true); setError(""); setOk(""); try { const r = await portal.raiseComplaint({ ...f, sales_invoice: f.sales_invoice || undefined }); setOk(`Thank you. Your request ${r.name} has been received.`); setF({ ...f, description: "", sales_invoice: "" }); load(); } catch (x) { setError(x instanceof Error ? x.message : "Could not send"); } finally { setBusy(false); } }
  return <><h1>Help and complaints</h1>{error && <Message kind="error">{error}</Message>}{ok && <Message kind="ok">{ok}</Message>}
    <form className="pt-card pt-form" onSubmit={send}><h2>Tell us what went wrong</h2>
      <label>What is it about?<select value={f.category} onChange={e => setF({ ...f, category: e.target.value })}>{COMPLAINT_CATEGORIES.map(c => <option key={c}>{c}</option>)}</select></label>
      <label>How serious is it?<select value={f.severity} onChange={e => setF({ ...f, severity: e.target.value })}>{["Low", "Medium", "High", "Critical"].map(c => <option key={c}>{c}</option>)}</select></label>
      <label>Related invoice (optional)<select value={f.sales_invoice} onChange={e => setF({ ...f, sales_invoice: e.target.value })}><option value="">None</option>{invoices.map(i => <option key={i.name} value={i.name}>{i.name} · {i.invoice_date}</option>)}</select></label>
      <label className="pt-wide">Describe the problem<textarea rows={4} required value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></label>
      <button className="pt-btn pt-primary" disabled={busy || !f.description.trim()}>Send</button></form>
    <section className="pt-card"><h2>Your requests</h2><Table rows={rows} empty="You have not raised any requests." cols={[{ head: "Reference", cell: r => r.name }, { head: "Date", cell: r => r.complaint_date }, { head: "About", cell: r => r.category },
      { head: "Status", cell: r => <Badge s={r.resolution_status} /> }, { head: "Our reply", cell: r => r.resolution || "—" }]} /></section></>;
}

function Account({ user, onDone }: { user: PortalUser; onDone: () => void }) {
  const [cur, setCur] = useState(""), [next, setNext] = useState(""), [again, setAgain] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) { e.preventDefault(); if (next !== again) { setError("The two new passwords do not match."); return; } setBusy(true); setError(""); try { await portal.changePassword(cur, next); onDone(); } catch (x) { setError(x instanceof Error ? x.message : "Could not change the password"); setBusy(false); } }
  return <><h1>My account</h1><form className="pt-card pt-form" onSubmit={submit}><p className="pt-muted pt-wide">Signed in as <strong>{user.email}</strong>. You will be asked to sign in again after changing your password.</p>{error && <Message kind="error">{error}</Message>}
    <label>Current password<input type="password" autoComplete="current-password" required value={cur} onChange={e => setCur(e.target.value)} /></label>
    <label>New password (10 characters or more)<input type="password" autoComplete="new-password" required minLength={10} value={next} onChange={e => setNext(e.target.value)} /></label>
    <label>Repeat new password<input type="password" autoComplete="new-password" required value={again} onChange={e => setAgain(e.target.value)} /></label>
    <button className="pt-btn pt-primary" disabled={busy}>Change password</button></form></>;
}

export default function PortalApp() {
  const [user, setUser] = useState<PortalUser | null | undefined>(undefined), [view, setView] = useState<View>(viewFromHash());
  useEffect(() => { portal.me().then(setUser).catch(() => setUser(null)); }, []);
  useEffect(() => { const h = () => setView(viewFromHash()); window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);
  async function signOut() { try { await portal.logout(); } finally { setUser(null); location.hash = ""; } }
  if (user === undefined) return <main className="pt-center"><p className="pt-muted">Loading…</p></main>;
  if (!user) return <SignIn onUser={setUser} />;
  const kind = portalKind(user);
  if (!kind) return <main className="pt-center"><div className="pt-card"><h1>No portal access</h1><p>Your sign-in does not have a portal. Please contact the company.</p><button className="pt-btn" onClick={() => void signOut()}>Sign out</button></div></main>;
  const nav: [View, string][] = [["home", "Overview"], ["invoices", "Invoices"], ["orders", "Orders"], ...(kind === "customer" ? [["support", "Help"] as [View, string]] : []), ["account", "My account"]];
  return <div className="pt-shell"><header className="pt-top"><strong className="pt-mark">Velora</strong><span className="pt-who">{user.full_name}</span><button className="pt-btn" onClick={() => void signOut()}>Sign out</button></header>
    <nav className="pt-nav" aria-label="Portal">{nav.map(([v, t]) => <a key={v} href={`#/${v === "home" ? "" : v}`} aria-current={view === v ? "page" : undefined}>{t}</a>)}</nav>
    <main className="pt-main">{view === "home" && <Home kind={kind} />}{view === "invoices" && <Invoices kind={kind} />}{view === "orders" && <Orders kind={kind} />}
      {view === "support" && kind === "customer" && <Support />}{view === "account" && <Account user={user} onDone={() => { setUser(null); location.hash = ""; }} />}</main></div>;
}
