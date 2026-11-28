import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { adviceOf, errorMessage, people, type Advice, type PeopleOptions, type PersonRow } from "../api";
import ErrorAdvice from "./ErrorAdvice";

/** People & Access: add a person in one step (email, name, what they do), change what they can do, or take access away. */
export default function PeopleAccess() {
  const [rows, setRows] = useState<PersonRow[]>([]);
  const [opts, setOpts] = useState<PeopleOptions>({ profiles: [], roles: [] });
  const [error, setError] = useState(""); const [advice, setAdvice] = useState<Advice | null>(null); const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ email: "", full_name: "" });
  const [profiles, setProfiles] = useState<string[]>([]); const [extra, setExtra] = useState<string[]>([]); const [more, setMore] = useState(false);
  const [secret, setSecret] = useState<{ email: string; password: string } | null>(null); const [left, setLeft] = useState(0); const [done, setDone] = useState("");
  const [editing, setEditing] = useState<PersonRow | null>(null);
  const fail = (e: unknown) => { setError(errorMessage(e).split(" How to fix it:")[0]); setAdvice(adviceOf(e)); };
  const load = useCallback(() => Promise.all([people.list(), people.options()]).then(([r, o]) => { setRows(r); setOpts(o); }).catch(fail), []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!secret) return; setLeft(45);
    const t = setInterval(() => setLeft((n) => { if (n <= 1) { clearInterval(t); setSecret(null); return 0; } return n - 1; }), 1000);
    return () => clearInterval(t);
  }, [secret]);
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const picked = useMemo(() => [...new Set([...opts.profiles.filter((p) => profiles.includes(p.name)).flatMap((p) => p.roles), ...extra])].sort(), [opts, profiles, extra]);

  async function add(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(""); setAdvice(null); setDone(""); setSecret(null);
    try {
      const r = await people.add({ ...f, profiles, roles: extra });
      if (r.temporary_password) setSecret({ email: r.email, password: r.temporary_password });
      setDone(r.new_user ? `${r.email} can sign in now with the temporary password below.` : `${r.email} already had a Velora sign-in and can now open this company.`);
      setF({ email: "", full_name: "" }); setProfiles([]); setExtra([]); await load();
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  return (
    <div className="admin-page people-access">
      <h1>People &amp; Access</h1>
      <p className="muted">Add a person, choose what they do, done. They get one sign-in for every company they work in; what they can do is set here, per company.</p>
      <ErrorAdvice error={error} advice={advice} />
      {done && <div className="notice" role="status">{done}</div>}
      {secret && <div className="notice secret" role="status">Temporary password for <b>{secret.email}</b>: <code>{secret.password}</code>{" "}
        <button type="button" className="rbtn" onClick={() => void navigator.clipboard?.writeText(secret.password)}>Copy</button>
        <span className="muted"> Shown once; it disappears in {left} s. They choose their own at the first sign-in.</span></div>}

      <form className="admin-card" onSubmit={(e) => void add(e)} aria-label="Add a person">
        <h2>Add a person</h2>
        <div className="row">
          <label>Email <input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} aria-label="Email" /></label>
          <label>Full name <input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} aria-label="Full name" /></label>
        </div>
        <h3>What do they do?</h3>
        <div className="profiles">{opts.profiles.map((p) => (
          <label key={p.name} className="profile"><input type="checkbox" checked={profiles.includes(p.name)} onChange={() => setProfiles(toggle(profiles, p.name))} aria-label={p.name} />
            <b>{p.name}</b><span className="muted">{p.description}</span></label>))}</div>
        <button type="button" className="rbtn" onClick={() => setMore(!more)}>{more ? "Hide individual roles" : "Choose individual roles…"}</button>
        {more && <RolePicker roles={opts.roles} value={extra} onChange={setExtra} />}
        <p className="muted">Roles given: {picked.length ? picked.join(", ") : "none yet"}</p>
        <button type="submit" className="rbtn primary" disabled={busy || !f.email || !picked.length}>{busy ? "Adding…" : "Add person"}</button>
      </form>

      <section className="admin-card">
        <h2>People in this company ({rows.length})</h2>
        <table className="dgrid"><thead><tr><th>Name</th><th>Email</th><th>Roles</th><th>Last sign-in</th><th /></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.email}><td>{r.full_name}{!r.is_active && <span className="muted"> (suspended)</span>}</td><td>{r.email}</td>
              <td>{r.roles.map((x) => <span key={x} className="chip">{x}</span>)}</td><td>{r.last_login ? new Date(r.last_login).toLocaleDateString() : "never"}</td>
              <td><button type="button" className="rbtn" onClick={() => setEditing(r)}>Change access</button>{" "}
                <button type="button" className="rbtn" onClick={() => { if (window.confirm(`Take ${r.email}'s access to this company away?`)) people.remove(r.email).then(load).catch(fail); }}>Remove</button></td></tr>))}</tbody></table>
      </section>
      {editing && <EditRoles person={editing} options={opts} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void load(); }} />}
    </div>);
}

function RolePicker({ roles, value, onChange }: { roles: PeopleOptions["roles"]; value: string[]; onChange: (v: string[]) => void }) {
  const [q, setQ] = useState("");
  const shown = roles.filter((r) => !q || r.name.toLowerCase().includes(q.toLowerCase()) || r.areas.some((a) => a.toLowerCase().includes(q.toLowerCase())));
  return (
    <div className="role-picker">
      <input placeholder="Find a role or an area (e.g. Payroll)" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a role" />
      <div className="role-grid">{shown.map((r) => (
        <label key={r.name} title={r.areas.join(", ")}><input type="checkbox" checked={value.includes(r.name)} onChange={() => onChange(value.includes(r.name) ? value.filter((x) => x !== r.name) : [...value, r.name])} aria-label={r.name} />
          {r.name}{r.areas.length > 0 && <span className="muted"> · {r.areas.slice(0, 3).join(", ")}</span>}</label>))}</div>
    </div>);
}

function EditRoles({ person, options, onClose, onSaved }: { person: PersonRow; options: PeopleOptions; onClose: () => void; onSaved: () => void }) {
  const [roles, setRoles] = useState<string[]>(person.roles);
  const [error, setError] = useState(""); const [advice, setAdvice] = useState<Advice | null>(null);
  async function save() {
    try { await people.setRoles(person.email, roles); onSaved(); } catch (e) { setError(errorMessage(e).split(" How to fix it:")[0]); setAdvice(adviceOf(e)); }
  }
  return (
    <div className="overlay" role="presentation"><div className="dialog" role="dialog" aria-label={`Access of ${person.email}`}>
      <header><h2>What {person.full_name || person.email} can do</h2></header>
      <div className="dialog-body">
        <ErrorAdvice error={error} advice={advice} />
        <div className="profiles">{options.profiles.map((p) => (
          <button key={p.name} type="button" className="rbtn" title={p.description} onClick={() => setRoles([...new Set([...roles, ...p.roles])])}>+ {p.name}</button>))}</div>
        <RolePicker roles={options.roles} value={roles} onChange={setRoles} />
      </div>
      <footer><button type="button" className="btn" onClick={onClose}>Cancel</button><button type="button" className="btn primary" disabled={!roles.length} onClick={() => void save()}>Save</button></footer>
    </div></div>);
}
