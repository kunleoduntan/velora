import { useMemo, useState } from "react";
import { dataFields } from "../../filters";
import type { Meta } from "../../types";
import Dialog from "../../ui/Dialog";
import Icon from "../../ui/Icon";

/** D365-style "Insert columns": search, tick the fields to show, order them. New ones go right after the column you clicked. */
export default function InsertColumnsDialog({ meta, columns, afterColumn, onApply, onClose }: {
  meta: Meta; columns: string[]; afterColumn?: string | null; onApply: (cols: string[] | null) => void; onClose: () => void;
}) {
  const all = useMemo(() => dataFields(meta).filter((f) => f.fieldname !== "name" && f.fieldtype !== "JSON"), [meta]);
  const [selected, setSelected] = useState<string[]>(columns);
  const [q, setQ] = useState("");
  const shown = all.filter((f) => f.label.toLowerCase().includes(q.trim().toLowerCase()) || f.fieldname.includes(q.trim().toLowerCase()));
  const label = (n: string) => all.find((f) => f.fieldname === n)?.label ?? n;

  const toggle = (n: string) => setSelected((cur) => {
    if (cur.includes(n)) return cur.filter((c) => c !== n);
    if (afterColumn === "name") return [n, ...cur];                       // "insert after ID" = at the front
    const i = afterColumn ? cur.indexOf(afterColumn) : -1;
    return i >= 0 ? [...cur.slice(0, i + 1), n, ...cur.slice(i + 1)] : [...cur, n];
  });
  const move = (i: number, d: number) => setSelected((cur) => { const c = [...cur]; [c[i], c[i + d]] = [c[i + d], c[i]]; return c; });
  const allShownOn = shown.length > 0 && shown.every((f) => selected.includes(f.fieldname));
  const toggleShown = () => setSelected((cur) => allShownOn ? cur.filter((c) => !shown.some((f) => f.fieldname === c))
    : [...cur, ...shown.map((f) => f.fieldname).filter((n) => !cur.includes(n))]);

  return (
    <Dialog title="Insert columns" wide onClose={onClose} footer={<>
      <button type="button" className="rbtn" onClick={() => onApply(null)}>Reset to default</button>
      <span className="grow" />
      <button type="button" className="rbtn" onClick={onClose}>Cancel</button>
      <button type="button" className="rbtn primary" onClick={() => onApply(selected)}>OK</button>
    </>}>
      <div className="ic-grid">
        <section aria-label="Available columns">
          <div className="search ic-search"><Icon name="search" size={14} /><input type="search" placeholder="Search columns" aria-label="Search columns" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <label className="ic-row ic-all"><input type="checkbox" aria-label="Select all shown" checked={allShownOn} onChange={toggleShown} /><strong>Column</strong><span className="muted">Type</span></label>
          <ul className="ic-list">
            {shown.length === 0 && <li className="muted ic-empty">No columns match</li>}
            {shown.map((f) => (
              <li key={f.fieldname}>
                <label className="ic-row">
                  <input type="checkbox" checked={selected.includes(f.fieldname)} onChange={() => toggle(f.fieldname)} aria-label={f.label} />
                  <span>{f.label}</span><span className="muted">{f.fieldtype}</span>
                </label>
              </li>
            ))}
          </ul>
        </section>
        <section aria-label="Column order">
          <h4>Visible columns ({selected.length + 1})</h4>
          <ul className="col-list">
            <li className="fixed"><span>ID</span><span className="muted">always first</span></li>
            {selected.map((c, i) => (
              <li key={c}>
                <span>{label(c)}</span>
                <span className="col-actions">
                  <button type="button" className="icon-btn" aria-label={`Move ${label(c)} up`} disabled={i === 0} onClick={() => move(i, -1)}><Icon name="arrowUp" size={14} /></button>
                  <button type="button" className="icon-btn" aria-label={`Move ${label(c)} down`} disabled={i === selected.length - 1} onClick={() => move(i, 1)}><Icon name="arrowDown" size={14} /></button>
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </Dialog>
  );
}
