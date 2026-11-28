import { lazy, Suspense, useCallback, useEffect, useState, type FormEvent } from "react";
import { fmt, portal, portalKind } from "./portalApi";
import type { Complaint, Invoice, OrderRow, Overview, PortalUser } from "./portalApi";
import { Badge, Message, Skeleton, Table } from "./ui";
import { Messages, PreferencesCard } from "./Shared";
import type { EmployeeView } from "./EmployeePages";

import { Meter, strength } from "../components/PasswordScreens";
const EmployeePages = lazy(() => import("./EmployeePages"));

const COMPLAINT_CATEGORIES = ["Product Quality", "Wrong Item", "Short Delivery", "Late Delivery", "Pricing or Billing", "Service", "Warranty", "Other"];
type View = "home" | "invoices" | "orders" | "support" | "account" | "messages" | EmployeeView;
const viewFromHash = (): View => { const h = location.hash.replace(/^#\/?/, ""); return (["invoices", "orders", "support", "account", "messages", "payslips", "leave", "holidays"] as View[]).includes(h as View) ? (h as View) : "home"; };

const resetToken = (): string | null => /^#\/reset\?token=([\w-]+)$/.exec(location.hash)?.[1] ?? null;

function Forgot({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState(""), [mode, setMode] = useState<"email" | "staff" | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) { e.preventDefault(); setBusy(true); setError(""); try { setMode((await portal.forgotPassword(email.trim())).mode); } catch (x) { setError(x instanceof Error ? x.message : "Could not send the request"); } finally { setBusy(false); } }
  if (mode) return <main className="pt-center"><div className="pt-card pt-signin" role="status"><div className="pt-mark">Velora</div><h1>{mode === "email" ? "Check your email" : "Request sent"}</h1>
    <p>{mode === "email" ? "If that address belongs to a portal account, a reset link is on its way. It works once and expires in 30 minutes." : "The company has been asked to give you a temporary password. You will choose your own when you sign in."}</p>
    <button className="pt-btn pt-primary" onClick={onBack}>Back to sign in</button></div></main>;
  return <main className="pt-center"><form className="pt-card pt-signin" onSubmit={submit}><div className="pt-mark">Velora</div><h1>Forgot your password?</h1><p className="pt-muted">Enter your email and we will arrange a reset.</p>
    {error && <Message kind="error">{error}</Message>}<label>Email address<input type="email" autoComplete="username" required value={email} onChange={e => setEmail(e.target.value)} /></label>
    <button className="pt-btn pt-primary" disabled={busy || !email}>{busy ? "Sending…" : "Reset my password"}</button><button type="button" className="pt-link" onClick={onBack}>← Back to sign in</button></form></main>;
}

function ResetWithLink({ token, onDone }: { token: string; onDone: () => void }) {
  const [pw, setPw] = useState(""), [again, setAgain] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false), [ok, setOk] = useState(false);
  async function submit(e: FormEvent) { e.preventDefault(); if (pw !== again) { setError("The two passwords do not match."); return; } setBusy(true); setError(""); try { await portal.resetPassword(token, pw); setOk(true); } catch (x) { setError(x instanceof Error ? x.message : "Could not reset the password"); } finally { setBusy(false); } }
  if (ok) return <main className="pt-center"><div className="pt-card pt-signin" role="status"><h1>Password changed</h1><p>You can sign in with your new password now.</p><button className="pt-btn pt-primary" onClick={onDone}>Go to sign in</button></div></main>;
  return <main className="pt-center"><form className="pt-card pt-signin" onSubmit={submit}><h1>Choose a new password</h1>{error && <Message kind="error">{error}</Message>}
    <label>New password<input type="password" autoComplete="new-password" required value={pw} onChange={e => setPw(e.target.value)} /></label><Meter password={pw} />
    <label>Repeat new password<input type="password" autoComplete="new-password" required value={again} onChange={e => setAgain(e.target.value)} /></label>
    <button className="pt-btn pt-primary" disabled={busy || !strength(pw).ok || !again}>{busy ? "Saving…" : "Save new password"}</button></form></main>;
}

function MustChange({ user, onDone }: { user: PortalUser; onDone: () => void }) {
  return <main className="pt-center"><div className="pt-card pt-signin"><div className="pt-mark">Velora</div><h1>Choose your own password</h1>
    <p className="pt-muted">You signed in with a temporary password. Choose one that only you know, then sign in again.</p><Account user={user} onDone={onDone} bare /></div></main>;
}

function SignIn({ onUser }: { onUser: (u: PortalUser) => void }) {
  const [email, setEmail] = useState(""), [password, setPassword] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false), [forgot, setForgot] = useState(false);
  if (forgot) return <Forgot onBack={() => setForgot(false)} />;
  async function submit(e: FormEvent) { e.preventDefault(); setBusy(true); setError(""); try { onUser(await portal.login(email, password)); } catch (x) { setError(x instanceof Error ? x.message : "Unable to sign in"); } finally { setBusy(false); } }
  return (
    <main className="pt-center"><form className="pt-card pt-signin" onSubmit={submit}>
      <div className="pt-mark">Velora</div><h1>Sign in to your portal</h1><p className="pt-muted">View your invoices, orders and requests in one place.</p>
      {error && <Message kind="error">{error}</Message>}
      <label>Email address<input type="email" autoComplete="username" required value={email} onChange={e => setEmail(e.target.value)} /></label>
      <label>Password<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></label>
      <button className="pt-btn pt-primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      <button type="button" className="pt-link" onClick={() => setForgot(true)}>Forgot your password?</button>
    </form></main>
  );
}

function Home({ kind }: { kind: "customer" | "supplier" }) {
  const [o, setO] = useState<Overview | null>(null), [error, setError] = useState("");
  useEffect(() => { portal.overview(kind).then(setO).catch(e => setError(e.message)); }, [kind]);
  if (error) return <Message kind="error">{error}</Message>;
  if (!o) return <Skeleton rows={4} />;
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

function Account({ user, onDone, bare }: { user: PortalUser; onDone: () => void; bare?: boolean }) {
  const [cur, setCur] = useState(""), [next, setNext] = useState(""), [again, setAgain] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) { e.preventDefault(); if (next !== again) { setError("The two new passwords do not match."); return; } setBusy(true); setError(""); try { await portal.changePassword(cur, next); onDone(); } catch (x) { setError(x instanceof Error ? x.message : "Could not change the password"); setBusy(false); } }
  return <>{!bare && <h1>My account</h1>}<form className={bare ? "pt-form" : "pt-card pt-form"} onSubmit={submit}><p className="pt-muted pt-wide">Signed in as <strong>{user.email}</strong>. You will be asked to sign in again after changing your password.</p>{error && <Message kind="error">{error}</Message>}
    <label>Current password<input type="password" autoComplete="current-password" required value={cur} onChange={e => setCur(e.target.value)} /></label>
    <label>New password<input type="password" autoComplete="new-password" required minLength={10} value={next} onChange={e => setNext(e.target.value)} /></label><Meter password={next} email={user.email} />
    <label>Repeat new password<input type="password" autoComplete="new-password" required value={again} onChange={e => setAgain(e.target.value)} /></label>
    <button className="pt-btn pt-primary" disabled={busy}>Change password</button></form>{!bare && <PreferencesCard />}</>;
}

export default function PortalApp() {
  const [user, setUser] = useState<PortalUser | null | undefined>(undefined), [view, setView] = useState<View>(viewFromHash());
  useEffect(() => { portal.me().then(setUser).catch(() => setUser(null)); }, []);
  useEffect(() => { const h = () => setView(viewFromHash()); window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);
  async function signOut() { try { await portal.logout(); } finally { setUser(null); location.hash = ""; } }
  if (user === undefined) return <main className="pt-center"><p className="pt-muted">Loading…</p></main>;
  const token = resetToken();
  if (!user && token) return <ResetWithLink token={token} onDone={() => { location.hash = ""; }} />;
  if (!user) return <SignIn onUser={setUser} />;
  if (user.must_change) return <MustChange user={user} onDone={() => { setUser(null); location.hash = ""; }} />;
  const kind = portalKind(user);
  if (!kind) return <main className="pt-center"><div className="pt-card"><h1>No portal access</h1><p>Your sign-in does not have a portal. Please contact the company.</p><button className="pt-btn" onClick={() => void signOut()}>Sign out</button></div></main>;
  const nav: [View, string][] = kind === "employee"
    ? [["home", "Overview"], ["payslips", "Payslips"], ["leave", "Leave"], ["holidays", "Holidays"], ["messages", "Messages"], ["account", "My account"]]
    : [["home", "Overview"], ["invoices", "Invoices"], ["orders", "Orders"], ...(kind === "customer" ? [["support", "Help"] as [View, string]] : []), ["messages", "Messages"], ["account", "My account"]];
  const money = kind === "customer" || kind === "supplier" ? kind : null;
  const employeeView = (["home", "payslips", "leave", "holidays"] as View[]).includes(view) ? (view as EmployeeView) : "home";
  return <div className="pt-shell"><header className="pt-top"><strong className="pt-mark">Velora</strong><span className="pt-who">{user.full_name}</span><button className="pt-btn" onClick={() => void signOut()}>Sign out</button></header>
    <nav className="pt-nav" aria-label="Portal">{nav.map(([v, t]) => <a key={v} href={`#/${v === "home" ? "" : v}`} aria-current={view === v ? "page" : undefined}>{t}</a>)}</nav>
    <main className="pt-main">{kind === "employee" && (["home", "payslips", "leave", "holidays"] as View[]).includes(view) && <Suspense fallback={<Skeleton rows={4} />}><EmployeePages view={employeeView} /></Suspense>}
      {money && view === "home" && <Home kind={money} />}{money && view === "invoices" && <Invoices kind={money} />}{money && view === "orders" && <Orders kind={money} />}{view === "messages" && <Messages />}
      {view === "support" && kind === "customer" && <Support />}{view === "account" && <Account user={user} onDone={() => { setUser(null); location.hash = ""; }} />}</main></div>;
}
