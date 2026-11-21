import { useRef, useState } from "react";
import { fetchedValues } from "../fetchFrom";
import { gridFields } from "../gridConfig";
import type { Meta } from "../types";
import Dialog from "../ui/Dialog";
import FieldControl from "./FieldControl";

/** Every field of a row - including the ones the grid does not have room for. */
export default function RowEditDialog({ meta, childMetas, row, index, readOnly, onSave, onClose }: {
  meta: Meta; childMetas?: Record<string, Meta>; row: Record<string, unknown>; index: number; readOnly?: boolean;
  onSave: (row: Record<string, unknown>) => void; onClose: () => void;
}) {
  const [draft, setDraft] = useState<Record<string, unknown>>(row);
  const requestVersion = useRef<Record<string, number>>({});
  const update = (fieldname: string, value: unknown) => {
    setDraft((current) => ({ ...current, [fieldname]: value }));
    const version = (requestVersion.current[fieldname] ?? 0) + 1;
    requestVersion.current[fieldname] = version;
    void fetchedValues(meta, fieldname, value).then((extra) => {
      if (requestVersion.current[fieldname] !== version || !Object.keys(extra).length) return;
      setDraft((current) => current[fieldname] === value ? { ...current, ...extra } : current);
    });
  };
  return (
    <Dialog title={`${readOnly ? "Row" : "Edit row"} ${index + 1}`} onClose={onClose} wide footer={readOnly ? undefined : <>
      <button type="button" className="rbtn primary" onClick={() => onSave(draft)}>Update</button>
    </>}>
      <div className="row-form">
        {gridFields(meta).map((f) => (
          <div key={f.fieldname} className="row-form-field">
            <FieldControl field={f} value={draft[f.fieldname]} readOnly={readOnly || f.read_only} childMetas={childMetas} onChange={(v) => update(f.fieldname, v)} />
          </div>
        ))}
      </div>
    </Dialog>
  );
}
