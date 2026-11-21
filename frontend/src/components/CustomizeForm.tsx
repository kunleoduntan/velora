import { useEffect, useMemo, useState } from "react";
import { api, clearCaches, errorMessage } from "../api";
import type { Field, Meta } from "../types";

const TYPES = ["Data", "Text", "Small Text", "Int", "Float", "Currency", "Percent", "Check", "Date", "Datetime", "Select", "Link"];
const FLAGS: [keyof Field & string, string][] = [["required", "Required"], ["hidden", "Hidden"], ["read_only", "Read only"], ["in_list_view", "In list"], ["in_standard_filter", "In filter"]];
const LAYOUT = ["Section Break", "Column Break", "Tab Break"];
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^(\d)/, "f_$1").slice(0, 60);

/** Customize Form, the ERPNext way: pick any DocType, see every field, change how a field behaves, add your own field after any other. Applies to this company only. */
export default function CustomizeForm({ initial = "" }: { initial?: string }) {
  const [doctypes, setDoctypes] = useState<{ name: string; module: string }[]>([]);
  const [module, setModule] = useState("");
  const [doctype, setDoctype] = useState(initial);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [custom, setCustom] = useState<string[]>([]);
  const [changed, setChanged] = useState<Record<string, Record<string, unknown>>>({});
  const [draft, setDraft] = useState({ label: "", fieldname: "", fieldtype: "Data", options: "", insert_after: "", required: false });
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.doctypes().then((r) => setDoctypes([...r].sort((a, b) => a.name.localeCompare(b.name)))).catch((e) => setError(errorMessage(e))); }, []);

  async function load(name: string) {
    setError(""); setNote(""); setChanged({});
    if (!doctypes.some((d) => d.name === name)) { setMeta(null); return; }
    try { const [m, cf] = await Promise.all([api.meta(name), api.customFields(name)]); setMeta(m); setCustom(cf.map((x: { fieldname: string }) => x.fieldname)); } catch (e) { setError(errorMessage(e)); setMeta(null); }
  }
  useEffect(() => { if (doctypes.length && doctype) void load(doctype); }, [doctypes, doctype]);

  const modules = useMemo(() => [...new Set(doctypes.map((d) => d.module))].sort(), [doctypes]);
  const shown = doctypes.filter((d) => !module || d.module === module);
  const fields = (meta?.fields ?? []).filter((f) => !LAYOUT.includes(f.fieldtype));
  const value = (f: Field, prop: string) => (changed[f.fieldname]?.[prop] !== undefined ? changed[f.fieldname][prop] : (f as unknown as Record<string, unknown>)[prop]);
  const edit = (f: Field, prop: string, v: unknown) => setChanged((c) => ({ ...c, [f.fieldname]: { ...c[f.fieldname], [prop]: v } }));
  const pending = Object.values(changed).reduce((n, o) => n + Object.keys(o).length, 0);

  async function update() {
    setBusy(true); setError(""); setNote("");
    try {
      for (const [fieldname, props] of Object.entries(changed)) for (const [property, v] of Object.entries(props)) await api.savePropertySetter(doctype, { fieldname, property, value: v });
      clearCaches(); setNote(`Updated ${pending} setting${pending === 1 ? "" : "s"}.`); await load(doctype);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function addField() {
    setBusy(true); setError(""); setNote("");
    try {
      const fieldname = draft.fieldname || slug(draft.label);
      if (!draft.label.trim() || !fieldname) throw new Error("Give the new field a label.");
      const body: Record<string, unknown> = { fieldname, label: draft.label.trim(), fieldtype: draft.fieldtype, required: draft.required, ...(draft.insert_after ? { insert_after: draft.insert_after } : {}) };
      if (draft.fieldtype === "Link") body.options = draft.options;
      if (draft.fieldtype === "Select") body.choices = draft.options.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
      await api.addCustomField(doctype, body);
      clearCaches(); setNote(`Added ${draft.label.trim()}.`); setDraft({ label: "", fieldname: "", fieldtype: "Data", options: "", insert_after: "", required: false }); await load(doctype);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function remove(name: string) {
    if (!window.confirm(`Remove ${name} from the form? Values already saved are kept in the database.`)) return;
    try { await api.removeCustomField(doctype, name); clearCaches(); await load(doctype); } catch (e) { setError(errorMessage(e)); }
  }

  return (
    <div className="panel customize-form">
      <header className="page-head"><div className="titles"><h1>Customize Form</h1><span className="muted">Change how any document looks and behaves, or add your own fields. This applies to your company only.</span></div></header>
      <div className="cf-pick">
        <label>Module<select aria-label="Module" value={module} onChange={(e) => setModule(e.target.value)}><option value="">All modules</option>{modules.map((m) => <option key={m}>{m}</option>)}</select></label>
        <label>Document type<input aria-label="Document type" list="cf-doctypes" value={doctype} placeholder="Choose a document type" onChange={(e) => setDoctype(e.target.value)} /></label>
        <datalist id="cf-doctypes">{shown.map((d) => <option key={d.name} value={d.name} label={d.module} />)}</datalist>
        <span className="muted">{shown.length} document types</span>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {note && <div className="success" role="status">{note}</div>}

      {meta && <>
        <div className="cf-actions"><button type="button" className="rbtn primary" disabled={!pending || busy} onClick={() => void update()}>Update{pending ? ` (${pending})` : ""}</button>
          <a className="rbtn" href={`#/app/${encodeURIComponent(doctype)}`}>Open {doctype}</a></div>
        <div className="grid-scroll"><table className="dgrid cf-table">
          <thead><tr><th>No.</th><th>Label</th><th>Field name</th><th>Type</th><th>Options</th>{FLAGS.map(([, l]) => <th key={l}>{l}</th>)}<th /></tr></thead>
          <tbody>{fields.map((f, i) => (
            <tr key={f.fieldname}>
              <td>{i + 1}</td>
              <td><input aria-label={`Label of ${f.fieldname}`} value={String(value(f, "label") ?? "")} onChange={(e) => edit(f, "label", e.target.value)} /></td>
              <td><code>{f.fieldname}</code> {custom.includes(f.fieldname) && <span className="chip">Custom</span>}</td>
              <td>{f.fieldtype}</td><td className="muted">{Array.isArray(f.options) ? f.options.join(", ") : f.fieldtype === "Link" ? f.options : ""}</td>
              {FLAGS.map(([p, l]) => <td key={p}><input type="checkbox" aria-label={`${l} for ${f.fieldname}`} checked={!!value(f, p)} onChange={(e) => edit(f, p, e.target.checked)} /></td>)}
              <td>{custom.includes(f.fieldname) && <button type="button" className="rbtn danger" onClick={() => void remove(f.fieldname)}>Remove</button>}</td>
            </tr>))}</tbody></table></div>

        <section className="admin-card" aria-label="Add a field"><h2>Add a field</h2>
          <div className="cf-add">
            <label>Label<input aria-label="New field label" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value, fieldname: slug(e.target.value) })} /></label>
            <label>Field name<input aria-label="New field name" value={draft.fieldname} onChange={(e) => setDraft({ ...draft, fieldname: slug(e.target.value) })} /></label>
            <label>Type<select aria-label="New field type" value={draft.fieldtype} onChange={(e) => setDraft({ ...draft, fieldtype: e.target.value, options: "" })}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select></label>
            {draft.fieldtype === "Link" && <label>Links to<input aria-label="New field links to" list="cf-doctypes" value={draft.options} onChange={(e) => setDraft({ ...draft, options: e.target.value })} /></label>}
            {draft.fieldtype === "Select" && <label>Choices (comma or one per line)<textarea aria-label="New field choices" value={draft.options} onChange={(e) => setDraft({ ...draft, options: e.target.value })} /></label>}
            <label>Insert after<select aria-label="Insert after" value={draft.insert_after} onChange={(e) => setDraft({ ...draft, insert_after: e.target.value })}><option value="">(at the end)</option>{fields.map((f) => <option key={f.fieldname} value={f.fieldname}>{f.label}</option>)}</select></label>
            <label className="check"><input type="checkbox" checked={draft.required} onChange={(e) => setDraft({ ...draft, required: e.target.checked })} /> Required</label>
            <button type="button" className="rbtn primary" disabled={busy} onClick={() => void addField()}>Add field</button>
          </div>
        </section>
      </>}
    </div>
  );
}
