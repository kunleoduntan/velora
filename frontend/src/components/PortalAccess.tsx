import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage, portalAdmin } from "../api";
import type { PortalAccountRow } from "../api";
import LinkField from "./LinkField";

/** Invite customer and supplier contacts to the portal. A temporary password is shown once, here, and stored nowhere. */
export default function PortalAccess() {
  const [rows, setRows] = useState<PortalAccountRow[]>([]);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<{ email: string; password: string } | null>(null), [copied, setCopied] = useState(false);
  const [f, setF] = useState({ portal_type: "Customer", party: "", full_name: "", email: "" });
  const load = useCallback(() => portalAdmin.accounts().then(setRows).catch(e => setError(errorMessage(e))), []);
  useEffect(() => { void load(); }, [load]);
  const portalUrl = `${location.origin}/portal`;

  async function invite(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(""); setSecret(null);
    try { const r = await portalAdmin.invite(f); setSecret({ email: r.email, password: r.temporary_password }); setF({ ...f, party: "", full_name: "", email: "" }); await load(); }
    catch (x) { setError(errorMessage(x)); } finally { setBusy(false); }
  }
  async function act(fn: () => Promise<{ email: string; temporary_password?: string }>) {
    setBusy(true); setError(""); setSecret(null);
    try { const r = await fn(); if (r.temporary_password) setSecret({ email: r.email, password: r.temporary_password }); await load(); }
    catch (x) { setError(errorMessage(x)); } finally { setBusy(false); }
  }
  async function copy(text: string) { try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { setCopied(false); } }

  return (
    <div className="panel">
      <div className="page-head"><div><h1>Portal Access</h1><p className="muted">Give a customer or supplier contact a sign-in. They see only their own invoices and orders. Portal address: <code>{portalUrl}</code></p></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      {secret && <div className="admin-card" role="status"><h2>Temporary password for {secret.email}</h2>
        <p><code style={{ fontSize: "1.15rem" }}>{secret.password}</code> <button className="rbtn" onClick={() => void copy(secret.password)}>{copied ? "Copied" : "Copy"}</button></p>
        <p className="muted">Send it to the contact now. It is not stored and cannot be shown again; you can issue a new one at any time. They can change it under My account.</p></div>}
      <form className="admin-card form-grid" onSubmit={invite}>
        <h2 style={{ gridColumn: "1 / -1" }}>Invite a contact</h2>
        <label>Portal<select value={f.portal_type} onChange={e => setF({ ...f, portal_type: e.target.value, party: "" })}><option>Customer</option><option>Supplier</option></select></label>
        <label>{f.portal_type}<LinkField doctype={f.portal_type} value={f.party} onChange={v => setF({ ...f, party: v })} ariaLabel={f.portal_type} /></label>
        <label>Contact name<input required value={f.full_name} onChange={e => setF({ ...f, full_name: e.target.value })} /></label>
        <label>Email address<input type="email" required value={f.email} onChange={e => setF({ ...f, email: e.target.value })} /></label>
        <div><button className="rbtn primary" disabled={busy || !f.party}>Create sign-in</button></div>
      </form>
      <div className="table-wrap"><table><thead><tr><th>Contact</th><th>Email</th><th>Portal</th><th>Linked to</th><th>Status</th><th /></tr></thead>
        <tbody>{rows.map(r => <tr key={r.email}><td>{r.full_name}</td><td>{r.email}</td><td>{r.portal_type}</td><td>{r.customer || r.supplier}</td><td><span className={`pill ${r.status === "Active" ? "pill-green" : "pill-red"}`}>{r.status}</span></td>
          <td><button className="rbtn" disabled={busy} onClick={() => void act(() => portalAdmin.reset(r.email))}>New password</button>
            <button className="rbtn" disabled={busy} onClick={() => void act(() => portalAdmin.setStatus(r.email, r.status === "Active" ? "Suspended" : "Active"))}>{r.status === "Active" ? "Suspend" : "Reactivate"}</button></td></tr>)}
          {!rows.length && <tr><td colSpan={6} className="muted">No portal contacts yet.</td></tr>}</tbody></table></div>
    </div>
  );
}
