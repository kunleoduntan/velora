import { useState } from "react";
import type { Doc, Meta } from "../../types";
import Dialog from "../../ui/Dialog";
import FieldControl from "../FieldControl";

export function BulkEditDialog({ meta, count, onApply, onClose }: { meta: Meta; count: number; onApply: (values: Doc) => void; onClose: () => void }) {
  const fields = meta.fields.filter((f) => !f.read_only && !["Table", "JSON", "Section Break", "Column Break", "Tab Break"].includes(f.fieldtype));
  const [name, setName] = useState(fields[0]?.fieldname ?? "");
  const [value, setValue] = useState<unknown>(null);
  const field = fields.find((f) => f.fieldname === name);
  return (
    <Dialog title={`Edit ${count} ${meta.name} record${count === 1 ? "" : "s"}`} onClose={onClose} footer={<>
      <button type="button" className="rbtn" onClick={onClose}>Cancel</button>
      <button type="button" className="rbtn primary" disabled={!field} onClick={() => onApply({ [name]: value })}>Update</button>
    </>}>
      <div className="field"><label htmlFor="bulk-field">Field</label>
        <select id="bulk-field" value={name} onChange={(e) => { setName(e.target.value); setValue(null); }}>
          {fields.map((f) => <option key={f.fieldname} value={f.fieldname}>{f.label}</option>)}
        </select></div>
      {field && <FieldControl key={name} field={{ ...field, required: false, label: "New value" }} value={value} onChange={setValue} />}
    </Dialog>
  );
}

export function BulkResultsDialog({ verb, results, onClose }: { verb: string; results: { name: string; ok: boolean; error?: string }[]; onClose: () => void }) {
  const failed = results.filter((r) => !r.ok);
  return (
    <Dialog title={`${verb}: ${results.length - failed.length} of ${results.length} succeeded`} onClose={onClose} footer={<button type="button" className="rbtn primary" onClick={onClose}>OK</button>}>
      {failed.length === 0 ? <p>All records were processed.</p> : <>
        <p>These records could not be processed (the others were):</p>
        <ul className="fail-list">{failed.map((r) => <li key={r.name}><strong>{r.name}</strong><span>{r.error}</span></li>)}</ul>
      </>}
    </Dialog>
  );
}
