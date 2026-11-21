import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, errorMessage } from "../api";

type CustomField = { fieldname: string; fieldtype: string; label: string; options?: string; choices?: string[]; required?: boolean; read_only?: boolean; hidden?: boolean; in_list_view?: boolean };
type Setter = { fieldname: string; property: string; value: unknown };
const FIELD_TYPES = ["Data", "Text", "Int", "Float", "Currency", "Check", "Date", "Datetime", "Select", "Link", "JSON"];
const PROPERTIES = ["label", "required", "read_only", "hidden", "default", "in_list_view", "in_standard_filter", "description", "length"];

export default function MetadataExtensions({ doctypes }: { doctypes: string[] }) {
  const [doctype, setDoctype] = useState(doctypes[0] || "");
  const [fields, setFields] = useState<CustomField[]>([]);
  const [setters, setSetters] = useState<Setter[]>([]);
  const [availableFields, setAvailableFields] = useState<string[]>([]);
  const [fieldname, setFieldname] = useState("");
  const [label, setLabel] = useState("");
  const [fieldtype, setFieldtype] = useState("Data");
  const [options, setOptions] = useState("");
  const [propertyField, setPropertyField] = useState("");
  const [property, setProperty] = useState("label");
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() {
    if (!doctype) return;
    try {
      const [f, s, meta] = await Promise.all([api.customFields(doctype), api.propertySetters(doctype), api.meta(doctype)]);
      setFields(f); setSetters(s);
      const names = (meta.fields || []).map((x: { fieldname: string }) => x.fieldname);
      setAvailableFields(names);
      if (!propertyField && names.length) setPropertyField(names[0]);
    } catch (e) { setError(errorMessage(e)); }
  }
  useEffect(() => { void refresh(); }, [doctype]);
  async function addField(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { await api.addCustomField(doctype, { fieldname, label, fieldtype, ...(fieldtype === "Link" ? { options } : {}), ...(fieldtype === "Select" ? { choices: options.split("\n").map(x => x.trim()).filter(Boolean) } : {}) });
      setFieldname(""); setLabel(""); setOptions(""); await refresh();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }
  async function saveSetter(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    let parsed: unknown = value;
    if (["required", "read_only", "hidden", "in_list_view", "in_standard_filter"].includes(property)) parsed = value === "true";
    else if (property === "length") parsed = Number(value);
    try { await api.savePropertySetter(doctype, { fieldname: propertyField, property, value: parsed }); await refresh(); }
    catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }
  async function removeField(name: string) {
    if (!window.confirm(`Remove ${name} from metadata? Existing database values will be preserved.`)) return;
    try { await api.removeCustomField(doctype, name); await refresh(); } catch (e) { setError(errorMessage(e)); }
  }
  async function resetSetter(s: Setter) {
    try { await api.removePropertySetter(doctype, s.fieldname, s.property); await refresh(); } catch (e) { setError(errorMessage(e)); }
  }
  async function exportPackage() {
    try {
      const data = await api.exportMetadataExtensions();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
      anchor.href = url; anchor.download = "velora-metadata-extensions.json"; anchor.click(); URL.revokeObjectURL(url);
    } catch (e) { setError(errorMessage(e)); }
  }
  async function importPackage(file?: File) {
    if (!file) return;
    try { const data = JSON.parse(await file.text()); await api.importMetadataExtensions(data); await refresh(); }
    catch (e) { setError(errorMessage(e)); }
  }
  return <div className="section"><div className="builder-body">
    <h3>Company metadata extensions</h3><p className="muted">Custom Fields and Property Setters apply only to the active company. Removing a Custom Field hides it from metadata but preserves its physical database column and values.</p>
    {error && <div className="error" role="alert">{error}</div>}
    <div className="field"><label htmlFor="metadata-doctype">DocType</label><select id="metadata-doctype" value={doctype} onChange={e => { setDoctype(e.target.value); setPropertyField(""); }}>
      {doctypes.map(d => <option key={d}>{d}</option>)}
    </select></div>
    <div className="toolbar"><button className="rbtn" type="button" onClick={() => void exportPackage()}>Export Company Customizations</button><label className="rbtn">Import Customizations<input type="file" accept="application/json,.json" hidden onChange={e => { void importPackage(e.target.files?.[0]); e.currentTarget.value = ""; }} /></label></div>
    <h4>Add Custom Field</h4><form onSubmit={addField} className="creator-opts">
      <div className="field"><label>Fieldname</label><input value={fieldname} onChange={e => setFieldname(e.target.value)} placeholder="custom_reference" required /></div>
      <div className="field"><label>Label</label><input value={label} onChange={e => setLabel(e.target.value)} placeholder="Reference" /></div>
      <div className="field"><label>Field type</label><select value={fieldtype} onChange={e => setFieldtype(e.target.value)}>{FIELD_TYPES.map(t => <option key={t}>{t}</option>)}</select></div>
      {(["Link", "Select"].includes(fieldtype)) && <div className="field"><label>{fieldtype === "Link" ? "Target DocType" : "Choices (one per line)"}</label><textarea value={options} onChange={e => setOptions(e.target.value)} required /></div>}
      <button className="rbtn primary" disabled={busy || !fieldname}>Add Custom Field</button>
    </form>
    <table className="dgrid"><thead><tr><th>Fieldname</th><th>Type</th><th>Label</th><th /></tr></thead><tbody>{fields.map(f => <tr key={f.fieldname}><td>{f.fieldname}</td><td>{f.fieldtype}</td><td>{f.label}</td><td><button className="rbtn" onClick={() => void removeField(f.fieldname)}>Remove</button></td></tr>)}{!fields.length && <tr><td colSpan={4}>No company Custom Fields.</td></tr>}</tbody></table>
    <h4>Property Setter</h4><form onSubmit={saveSetter} className="creator-opts">
      <div className="field"><label>Field</label><select value={propertyField} onChange={e => setPropertyField(e.target.value)}>{availableFields.map(f => <option key={f}>{f}</option>)}</select></div>
      <div className="field"><label>Property</label><select value={property} onChange={e => setProperty(e.target.value)}>{PROPERTIES.map(p => <option key={p}>{p}</option>)}</select></div>
      <div className="field"><label>Value</label>{["required", "read_only", "hidden", "in_list_view", "in_standard_filter"].includes(property) ? <select value={value} onChange={e => setValue(e.target.value)}><option value="">Choose</option><option value="true">True</option><option value="false">False</option></select> : <input value={value} onChange={e => setValue(e.target.value)} required />}</div>
      <button className="rbtn primary" disabled={busy || !propertyField || !value}>Save Property Setter</button>
    </form>
    <table className="dgrid"><thead><tr><th>Field</th><th>Property</th><th>Value</th><th /></tr></thead><tbody>{setters.map(s => <tr key={`${s.fieldname}.${s.property}`}><td>{s.fieldname}</td><td>{s.property}</td><td>{String(s.value)}</td><td><button className="rbtn" onClick={() => void resetSetter(s)}>Reset</button></td></tr>)}{!setters.length && <tr><td colSpan={4}>No Property Setters.</td></tr>}</tbody></table>
  </div></div>;
}
