import { useMemo, useState } from "react";
import { api, errorMessage, type CreatorReport, type CreatorResult } from "../api";

type FieldType = "Data" | "Text" | "Int" | "Float" | "Currency" | "Check" | "Date" | "Datetime" | "Select" | "Link" | "Table" | "JSON" | "Tab Break" | "Section Break" | "Column Break";
type FieldRow = { id: number; fieldname: string; label: string; fieldtype: FieldType; options: string; required: boolean; unique: boolean; read_only: boolean; hidden: boolean; in_list_view: boolean; in_standard_filter: boolean; default_value: string; length: string; description: string; depends_on: string; mandatory_depends_on: string; read_only_depends_on: string };
type PermissionRow = { role: string; read: boolean; write: boolean; create: boolean; delete: boolean; submit: boolean; cancel: boolean; report: boolean; export: boolean; import: boolean; print: boolean; email: boolean; share: boolean; amend: boolean };
const fieldTypes: FieldType[] = ["Data", "Text", "Int", "Float", "Currency", "Check", "Date", "Datetime", "Select", "Link", "Table", "JSON", "Tab Break", "Section Break", "Column Break"];
const blankField = (id: number): FieldRow => ({ id, fieldname: "", label: "", fieldtype: "Data", options: "", required: false, unique: false, read_only: false, hidden: false, in_list_view: false, in_standard_filter: false, default_value: "", length: "", description: "", depends_on: "", mandatory_depends_on: "", read_only_depends_on: "" });
const managerPermission = (): PermissionRow => ({ role: "System Manager", read: true, write: true, create: true, delete: true, submit: true, cancel: true, report: true, export: true, import: true, print: true, email: true, share: true, amend: true });

export default function VisualDocTypeBuilder({ apps }: { apps: string[] }) {
  const [app, setApp] = useState(apps[0] || "");
  const [module, setModule] = useState("");
  const [name, setName] = useState("");
  const [child, setChild] = useState(false);
  const [submittable, setSubmittable] = useState(false);
  const [track, setTrack] = useState(true);
  const [autoname, setAutoname] = useState("series");
  const [prefix, setPrefix] = useState("DOC");
  const [fields, setFields] = useState<FieldRow[]>([blankField(1)]);
  const [permissions, setPermissions] = useState<PermissionRow[]>([managerPermission()]);
  const [report, setReport] = useState<CreatorReport | null>(null);
  const [result, setResult] = useState<CreatorResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const nextId = useMemo(() => Math.max(0, ...fields.map((f) => f.id)) + 1, [fields]);

  function updateField(id: number, patch: Partial<FieldRow>) {
    setFields((old) => old.map((f) => f.id === id ? { ...f, ...patch } : f));
    setReport(null); setResult(null);
  }
  function spec() {
    const cleanFields = fields.map((f) => {
      const row: Record<string, unknown> = { fieldname: f.fieldname.trim(), label: f.label.trim(), fieldtype: f.fieldtype };
      if (["Link", "Table"].includes(f.fieldtype)) row.options = f.options.trim();
      if (f.fieldtype === "Select") row.options = f.options.split("\n").map((x) => x.trim()).filter(Boolean);
      for (const k of ["required", "unique", "read_only", "hidden", "in_list_view", "in_standard_filter"] as const) if (f[k]) row[k] = true;
      for (const k of ["description", "depends_on", "mandatory_depends_on", "read_only_depends_on"] as const) if (f[k].trim()) row[k] = f[k].trim();
      if (f.default_value !== "") row.default = f.default_value;
      if (f.length.trim()) row.length = Number(f.length);
      return row;
    });
    const perms = permissions.filter((p) => p.role.trim()).map((p) => ({ ...p }));
    return {
      name: name.trim(), module: module.trim(), istable: child, is_submittable: !child && submittable,
      track_changes: track, autoname: child ? "hash" : autoname === "series" ? `series:${prefix.trim() || "DOC"}-.####` : autoname,
      fields: cleanFields, permissions: child ? [] : perms,
    };
  }
  const body = () => ({ json: JSON.stringify(spec()), app, module: module || undefined, on_conflict: "error" as const });
  async function preview() {
    setBusy(true); setError(""); setResult(null);
    try { setReport(await api.creatorPreview(body())); } catch (e) { setError(errorMessage(e)); setReport(null); } finally { setBusy(false); }
  }
  async function create() {
    setBusy(true); setError("");
    try { setResult(await api.creatorCreate(body())); setReport(null); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const invalid = !app || !module.trim() || !name.trim() || fields.length === 0 || fields.some((f) => !["Tab Break", "Section Break", "Column Break"].includes(f.fieldtype) && !/^[a-z][a-z0-9_]{0,62}$/.test(f.fieldname.trim()));
  return <section className="section" data-testid="visual-doctype-builder"><div className="builder-body">
    <h3>Visual DocType Builder</h3>
    <p className="muted">Design a DocType using fields and permissions. Preview validates the complete definition before source files are written to the selected application.</p>
    {error && <div className="error" role="alert">{error}</div>}
    <div className="creator-opts">
      <div className="field"><label htmlFor="vdt_app">Application</label><select id="vdt_app" value={app} onChange={(e) => { setApp(e.target.value); setReport(null); }}>{apps.map((a) => <option key={a}>{a}</option>)}</select></div>
      <div className="field"><label htmlFor="vdt_module">Module</label><input id="vdt_module" value={module} onChange={(e) => setModule(e.target.value)} placeholder="e.g. Sales" /></div>
      <div className="field"><label htmlFor="vdt_name">DocType name</label><input id="vdt_name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sales Invoice" /></div>
      <div className="field"><label htmlFor="vdt_naming">Naming</label><select id="vdt_naming" value={autoname} disabled={child} onChange={(e) => setAutoname(e.target.value)}><option value="series">Naming series</option><option value="hash">Generated ID</option><option value="prompt">User enters name</option></select></div>
      {autoname === "series" && !child && <div className="field"><label htmlFor="vdt_prefix">Series prefix</label><input id="vdt_prefix" value={prefix} onChange={(e) => setPrefix(e.target.value)} /></div>}
    </div>
    <div className="creator-flags">
      <label><input type="checkbox" checked={child} onChange={(e) => { setChild(e.target.checked); if (e.target.checked) setSubmittable(false); setReport(null); }} /> Child table</label>
      <label><input type="checkbox" checked={submittable} disabled={child} onChange={(e) => setSubmittable(e.target.checked)} /> Submittable</label>
      <label><input type="checkbox" checked={track} disabled={child} onChange={(e) => setTrack(e.target.checked)} /> Track changes</label>
    </div>
    <h4>Fields</h4>
    <div className="table-scroll"><table className="dgrid"><thead><tr><th>Fieldname</th><th>Label</th><th>Type</th><th>Options / Choices</th><th>Required</th><th>List</th><th>Actions</th></tr></thead><tbody>
      {fields.map((f) => <tr key={f.id}><td><input aria-label={`Fieldname ${f.id}`} value={f.fieldname} disabled={f.fieldtype.includes("Break")} onChange={(e) => updateField(f.id, { fieldname: e.target.value })} placeholder="field_name" /></td><td><input aria-label={`Label ${f.id}`} value={f.label} onChange={(e) => updateField(f.id, { label: e.target.value })} /></td><td><select aria-label={`Type ${f.id}`} value={f.fieldtype} onChange={(e) => updateField(f.id, { fieldtype: e.target.value as FieldType, options: "" })}>{fieldTypes.filter((t) => child ? !["Table", "Tab Break"].includes(t) : true).map((t) => <option key={t}>{t}</option>)}</select></td><td>{["Link", "Table"].includes(f.fieldtype) ? <input aria-label={`Options ${f.id}`} value={f.options} onChange={(e) => updateField(f.id, { options: e.target.value })} placeholder="Target DocType" /> : f.fieldtype === "Select" ? <textarea aria-label={`Options ${f.id}`} rows={2} value={f.options} onChange={(e) => updateField(f.id, { options: e.target.value })} placeholder="One option per line" /> : <input aria-label={`Default ${f.id}`} value={f.default_value} onChange={(e) => updateField(f.id, { default_value: e.target.value })} placeholder="Default" />}</td><td><input aria-label={`Required ${f.id}`} type="checkbox" checked={f.required} onChange={(e) => updateField(f.id, { required: e.target.checked })} /></td><td><input aria-label={`List ${f.id}`} type="checkbox" checked={f.in_list_view} onChange={(e) => updateField(f.id, { in_list_view: e.target.checked })} /></td><td><button type="button" className="rbtn" disabled={fields.length === 1} onClick={() => { setFields((old) => old.filter((x) => x.id !== f.id)); setReport(null); }}>Remove</button></td></tr>)}
    </tbody></table></div>
    <details className="section" open><summary><strong>Advanced field properties</strong> <span className="muted">Descriptions, validation and conditional behaviour</span></summary>
      <div className="table-scroll"><table className="dgrid"><thead><tr><th>Field</th><th>Description</th><th>Depends on</th><th>Mandatory when</th><th>Read-only when</th><th>Other properties</th></tr></thead><tbody>
        {fields.filter((f) => !f.fieldtype.includes("Break")).map((f) => <tr key={`advanced-${f.id}`}>
          <td><strong>{f.label || f.fieldname || `Field ${f.id}`}</strong><br/><code>{f.fieldname || "unnamed"}</code></td>
          <td><textarea aria-label={`Description ${f.id}`} rows={2} value={f.description} onChange={(e) => updateField(f.id, { description: e.target.value })} /></td>
          <td><input aria-label={`Depends on ${f.id}`} value={f.depends_on} onChange={(e) => updateField(f.id, { depends_on: e.target.value })} placeholder="eval:doc.status == 'Open'" /></td>
          <td><input aria-label={`Mandatory depends on ${f.id}`} value={f.mandatory_depends_on} onChange={(e) => updateField(f.id, { mandatory_depends_on: e.target.value })} placeholder="eval:doc.enabled == 1" /></td>
          <td><input aria-label={`Read only depends on ${f.id}`} value={f.read_only_depends_on} onChange={(e) => updateField(f.id, { read_only_depends_on: e.target.value })} placeholder="eval:doc.docstatus == 1" /></td>
          <td><div className="creator-flags">
            <label><input type="checkbox" aria-label={`Unique ${f.id}`} checked={f.unique} onChange={(e) => updateField(f.id, { unique: e.target.checked })}/> Unique</label>
            <label><input type="checkbox" aria-label={`Read only ${f.id}`} checked={f.read_only} onChange={(e) => updateField(f.id, { read_only: e.target.checked })}/> Read only</label>
            <label><input type="checkbox" aria-label={`Hidden ${f.id}`} checked={f.hidden} onChange={(e) => updateField(f.id, { hidden: e.target.checked })}/> Hidden</label>
            <label><input type="checkbox" aria-label={`Standard filter ${f.id}`} checked={f.in_standard_filter} onChange={(e) => updateField(f.id, { in_standard_filter: e.target.checked })}/> Standard filter</label>
          </div></td>
        </tr>)}
      </tbody></table></div>
      <p className="muted">Use Frappe-style expressions such as <code>eval:doc.status == 'Open'</code>. Supported expressions are evaluated in a restricted environment; arbitrary Python and JavaScript are not executed.</p>
    </details>
    <button type="button" className="rbtn" onClick={() => setFields((old) => [...old, blankField(nextId)])}>Add field</button>
    {!child && <><h4>Role permissions</h4><div className="table-scroll"><table className="dgrid"><thead><tr><th>Role</th>{["read", "write", "create", "delete", "submit", "cancel", "report", "export", "import"].map((p) => <th key={p}>{p}</th>)}</tr></thead><tbody>{permissions.map((p, i) => <tr key={i}><td><input aria-label={`Permission role ${i}`} value={p.role} onChange={(e) => setPermissions((old) => old.map((x, n) => n === i ? { ...x, role: e.target.value } : x))} /></td>{(["read", "write", "create", "delete", "submit", "cancel", "report", "export", "import"] as const).map((k) => <td key={k}><input aria-label={`${k} permission ${i}`} type="checkbox" checked={p[k]} onChange={(e) => setPermissions((old) => old.map((x, n) => n === i ? { ...x, [k]: e.target.checked } : x))} /></td>)}</tr>)}</tbody></table></div><button type="button" className="rbtn" onClick={() => setPermissions((old) => [...old, { ...managerPermission(), role: "" }])}>Add role</button></>}
    <div className="ribbon"><button type="button" className="rbtn primary" disabled={busy || invalid} onClick={preview}>Preview DocType</button><button type="button" className="rbtn" disabled={busy || !report?.ok} onClick={create}>Create DocType</button></div>
    {report && <div className="intro" role="status"><strong>{report.ok ? "Definition valid" : "Definition needs attention"}</strong>{report.errors.length > 0 && <ul>{report.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}{report.warnings.map((w, i) => <p key={i}>{w}</p>)}{report.doctypes.map((d) => <p key={d.name}>{d.name}: {d.fields} fields · {d.child ? "Child table" : d.submittable ? "Submittable" : "Standard DocType"}</p>)}</div>}
    {result && <div className="success" role="status">Created {result.created.join(", ")}. Generated source files: {result.files.length}. <a href={`#/app/${encodeURIComponent(result.created[0])}`}>Open list</a></div>}
  </div></section>;
}
