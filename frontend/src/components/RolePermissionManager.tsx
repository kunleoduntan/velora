import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../api";
import LinkField from "./LinkField";

const ACTIONS = ["read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "import", "print", "email", "share"];
const ACCESS = ["Default", "editable", "read_only", "hidden"];

export default function RolePermissionManager() {
  const [roles, setRoles] = useState<any[]>([]);
  const [role, setRole] = useState("");
  const [doctype, setDoctype] = useState("");
  const [meta, setMeta] = useState<any>(null);
  const [effective, setEffective] = useState<any>({ permissions: [], fields: [] });
  const [newRole, setNewRole] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadRoles() {
    const list = await api.roleAdminRoles(); setRoles(list);
    if (!role && list.length) setRole(list[0].name);
  }
  async function loadMeta(target = doctype) {
    if (!target) { setMeta(null); return; }
    setMeta(await api.roleAdminDoctype(target));
  }
  async function loadEffective(target = role) {
    if (!target) { setEffective({ permissions: [], fields: [] }); return; }
    setEffective(await api.roleAdminEffective(target));
  }
  useEffect(() => { loadRoles().catch((e) => setError(errorMessage(e))); }, []);
  useEffect(() => { loadEffective().catch((e) => setError(errorMessage(e))); }, [role]);
  useEffect(() => { loadMeta().catch((e) => setError(errorMessage(e))); }, [doctype]);

  const levels = useMemo(() => [...new Set([0, ...(meta?.fields || []).map((f: any) => Number(f.permlevel || 0))])].sort((a, b) => a - b), [meta]);
  const fieldOverrides = useMemo(() => new Map((effective.fields || []).filter((x: any) => x.doctype === doctype).map((x: any) => [x.fieldname, x.access])), [effective, doctype]);
  const permissions = useMemo(() => new Map((effective.permissions || []).filter((x: any) => x.doctype === doctype).map((x: any) => [`${x.permlevel || 0}:${x.permission}`, Boolean(x.allowed)])), [effective, doctype]);

  async function createRole() {
    setBusy(true); setError(""); setNotice("");
    try { const created = await api.roleAdminCreateRole(newRole.trim()); setNewRole(""); await loadRoles(); setRole(created.name); setNotice(`Role ${created.name} created.`); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function setPermission(permlevel: number, permission: string, allowed: boolean) {
    setBusy(true); setError(""); setNotice("");
    try { await api.roleAdminSetPermission({ role, doctype, permlevel, permission, allowed }); await loadEffective(); setNotice(`${permission} permission saved for ${role} at level ${permlevel}.`); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function setFieldAccess(fieldname: string, access: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      const body = { role, doctype, fieldname };
      if (access === "Default") await api.roleAdminClearFieldAccess(body);
      else await api.roleAdminSetFieldAccess({ ...body, access });
      await loadEffective(); setNotice(`${fieldname} field policy updated.`);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  return <div className="panel role-permission-manager">
    <div className="page-head"><div><h1>Role & Field Permissions</h1><p className="muted">Configure Frappe-style DocType permissions and permission levels. The server remains the enforcement authority.</p></div></div>
    {error && <div className="error" role="alert">{error}</div>}{notice && <div className="success" role="status">{notice}</div>}
    <section className="admin-card"><h2>Permission scope</h2><div className="form-grid">
      <label>Role<select aria-label="Permission role" value={role} onChange={(e) => setRole(e.target.value)}><option value="">Select role</option>{roles.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}</select></label>
      <label>DocType<div className="role-doctype-link"><LinkField doctype="DocType" value={doctype} onChange={setDoctype} placeholder="Search any DocType…" ariaLabel="Permission DocType" /></div></label>
    </div>
    {!roles.length && <div className="role-create"><label>Create company role<input value={newRole} onChange={(e) => setNewRole(e.target.value)} placeholder="e.g. Project Finance Officer" /></label><button className="rbtn primary" disabled={busy || !newRole.trim()} onClick={() => void createRole()}>Create role</button></div>}
    {roles.length > 0 && <div className="role-create"><label>Add another company role<input value={newRole} onChange={(e) => setNewRole(e.target.value)} placeholder="e.g. Project Finance Officer" /></label><button className="rbtn" disabled={busy || !newRole.trim()} onClick={() => void createRole()}>Create role</button></div>}
    </section>
    {role && doctype && meta && <>
      <section className="admin-card"><h2>DocType permissions</h2><p className="muted">Permission level 0 is the default. Additional levels apply only to fields assigned the matching `permlevel` in DocType metadata.</p>
        <div className="table-wrap"><table className="dgrid role-permission-grid"><thead><tr><th>Permission Level</th>{ACTIONS.map((a) => <th key={a}>{a}</th>)}</tr></thead><tbody>
          {levels.map((level) => <tr key={level}><th>Level {level}</th>{ACTIONS.map((a) => <td key={a}><input type="checkbox" aria-label={`${a} permission level ${level}`} disabled={busy} checked={permissions.has(`${level}:${a}`) ? Boolean(permissions.get(`${level}:${a}`)) : Boolean(meta.permissions?.find((p: any) => p.role === role && Number(p.permlevel || 0) === level)?.[a])} onChange={(e) => void setPermission(level, a, e.target.checked)} /></td>)}</tr>)}
        </tbody></table></div>
      </section>
      <section className="admin-card"><h2>Field access overrides</h2><p className="muted">Use `permlevel` for the normal ERPNext permission model. These optional per-role overrides can further restrict a field as hidden or read-only.</p>
        <div className="table-wrap"><table className="dgrid"><thead><tr><th>Field</th><th>Field Type</th><th>Permission Level</th><th>Role Override</th></tr></thead><tbody>
          {(meta.fields || []).filter((f: any) => !f.hidden || fieldOverrides.has(f.fieldname)).map((f: any) => <tr key={f.fieldname}><td><strong>{f.label || f.fieldname}</strong><small className="muted">{f.fieldname}</small></td><td>{f.fieldtype}</td><td>{Number(f.permlevel || 0)}</td><td><select aria-label={`${f.fieldname} field access`} disabled={busy} value={String(fieldOverrides.get(f.fieldname) || "Default")} onChange={(e) => void setFieldAccess(f.fieldname, e.target.value)}>{ACCESS.map((a) => <option key={a} value={a}>{a === "Default" ? "Use DocType permission level" : a.replace("_", " ")}</option>)}</select></td></tr>)}
        </tbody></table></div>
      </section>
    </>}
    {role && doctype && !meta && <p className="muted">Loading DocType metadata…</p>}
    {(!role || !doctype) && <section className="admin-card"><p className="muted">Select a role and a DocType to configure its permissions.</p></section>}
  </div>;
}
