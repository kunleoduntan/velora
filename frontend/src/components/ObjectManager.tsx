import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

type ManagedObject = { name: string; module: string; app: string; field_count: number; is_child: boolean; is_submittable: boolean; definition: Record<string, unknown> };
type Payload = { company: string; objects: ManagedObject[]; archived: { archived_on?: string; definition?: Record<string, unknown> }[]; conflicts?: { name: string; reason: string }[] };
const starter = {
  name: "New Business Object", module: "Custom", fields: [
    { fieldname: "title", label: "Title", fieldtype: "Data", required: true, in_list_view: true },
    { fieldname: "description", label: "Description", fieldtype: "Small Text" },
  ],
};

export default function ObjectManager() {
  const [data, setData] = useState<Payload | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [json, setJson] = useState(JSON.stringify(starter, null, 2));
  const [mode, setMode] = useState<"new" | "edit">("new");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function refresh(preferred?: string) {
    const result = await api.companyObjects(); setData(result);
    const name = preferred && result.objects.some((x) => x.name === preferred) ? preferred : "";
    setSelected(name);
    if (name) { const item = result.objects.find((x) => x.name === name)!; setJson(JSON.stringify(item.definition, null, 2)); setMode("edit"); }
  }
  useEffect(() => { refresh().catch((e) => setError(errorMessage(e))); }, []);
  function choose(name: string) {
    setSelected(name); setError(""); setMessage("");
    if (!name) { setMode("new"); setJson(JSON.stringify(starter, null, 2)); return; }
    const item = data?.objects.find((x) => x.name === name);
    if (item) { setMode("edit"); setJson(JSON.stringify(item.definition, null, 2)); }
  }
  async function save() {
    setBusy(true); setError(""); setMessage("");
    try {
      const definition = JSON.parse(json);
      const result = mode === "new" ? await api.companyObjectCreate(definition) : await api.companyObjectUpdate(selected, definition);
      setMessage(`${mode === "new" ? "Created" : "Updated"} ${mode === "new" ? result.created : result.updated}. ${result.migration?.length ?? 0} schema operation(s) applied.`);
      await refresh(mode === "new" ? result.created : selected);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function restore(name: string) {
    setBusy(true); setError(""); setMessage("");
    try { const result = await api.companyObjectRestore(name); setMessage(`${result.restored} restored.`); await refresh(result.restored); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function remove() {
    if (!selected || !window.confirm(`Archive ${selected}? Its metadata will be removed from the active object catalogue, but its database table and records will be retained.`)) return;
    setBusy(true); setError(""); setMessage("");
    try { const result = await api.companyObjectDelete(selected); setMessage(`${result.deleted} archived. ${result.note}`); await refresh(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <div className="creator">
    <header className="page-head"><div className="titles"><h1>Company Object Manager</h1><span className="muted">Create and manage DocType metadata stored exclusively in the active company database.</span></div></header>
    {data && <div className="panel"><strong>Active company:</strong> {data.company} <span className="muted">· {data.objects.length} company objects</span></div>}
    {error && <div className="error" role="alert">{error}</div>}{message && <div className="success" role="status">{message}</div>}
    <div className="section"><div className="builder-body">
      <div className="field"><label htmlFor="managed-doctype">Select an existing object or create a new one</label><select id="managed-doctype" value={selected} onChange={(e) => choose(e.target.value)}><option value="">＋ Create new object</option>{data?.objects.map((x) => <option key={x.name} value={x.name}>{x.name} · {x.module}</option>)}</select></div>
      <div className="creator-opts">
        <div><h3>{mode === "new" ? "New DocType definition" : `Edit ${selected}`}</h3><p className="muted">Edit the complete metadata definition as JSON. Changes are validated and the company database schema is migrated.</p></div>
        <div className="field"><label htmlFor="object-json">DocType JSON</label><textarea id="object-json" className="code-editor" rows={24} spellCheck={false} value={json} onChange={(e) => setJson(e.target.value)} /></div>
      </div>
      <div className="actions"><button className="rbtn primary" disabled={busy} onClick={save}>{busy ? "Saving…" : mode === "new" ? "Create object" : "Save changes"}</button>{mode === "edit" && <button className="rbtn danger" disabled={busy} onClick={remove}>Archive object</button>}<button className="rbtn" disabled={busy} onClick={() => choose("")}>New object</button></div>
    </div></div>
    <div className="section"><div className="builder-body"><h3>Company object catalogue</h3><p className="muted">Application DocTypes remain managed by their installed application. This catalogue contains company-local DocTypes only.</p>
      <table className="dgrid"><thead><tr><th>DocType</th><th>Module</th><th>Fields</th><th>Type</th><th>Actions</th></tr></thead><tbody>{data?.objects.map((x) => <tr key={x.name}><td>{x.name}</td><td>{x.module}</td><td>{x.field_count}</td><td>{x.is_child ? "Child" : x.is_submittable ? "Submittable" : "Standard"}</td><td><button className="link" type="button" onClick={() => choose(x.name)}>Open / edit</button></td></tr>)}{data?.objects.length === 0 && <tr><td colSpan={5} className="muted">No company-local objects have been created.</td></tr>}</tbody></table>
    </div></div>
    <div className="section"><div className="builder-body"><h3>Archived objects</h3><p className="muted">Archived metadata can be restored. Its underlying database tables and records are retained.</p>
      <table className="dgrid"><thead><tr><th>DocType</th><th>Archived on</th><th>Action</th></tr></thead><tbody>{data?.archived.map((x: any, i: number) => <tr key={`${x.definition?.name}-${i}`}><td>{x.definition?.name}</td><td>{x.deleted_on}</td><td><button className="link" type="button" disabled={busy} onClick={() => restore(x.definition.name)}>Restore</button></td></tr>)}{data?.archived.length === 0 && <tr><td colSpan={3} className="muted">No archived objects.</td></tr>}</tbody></table>
    </div></div>
  </div>;
}
