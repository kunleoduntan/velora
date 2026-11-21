import { useRef, useState } from "react";
import { defaultColumnWidth, gridFields, MAX_WIDTH, resolveColumns } from "../gridConfig";
import type { GridColumn, Meta } from "../types";
import Dialog from "../ui/Dialog";
import Icon from "../ui/Icon";

interface Item { fieldname: string; label: string; type: string; show: boolean; width: number }

/** Configure an unbounded, horizontally scrollable child-table grid. */
export default function GridColumnsDialog({ meta, columns, canCustomize, freeze, onFreeze, onSave, onReset, onClose }: {
  meta: Meta; columns: GridColumn[]; canCustomize: boolean; freeze?: number; onFreeze?: (n: number) => void;
  onSave: (cols: GridColumn[], scope: "me" | "everyone") => void; onReset: () => void; onClose: () => void;
}) {
  const [items, setItems] = useState<Item[]>(() => {
    const shown = resolveColumns(meta, columns, null);
    const names = new Set(shown.map((c) => c.field.fieldname));
    return [
      ...shown.map((c) => ({ fieldname: c.field.fieldname, label: c.field.label, type: c.field.fieldtype, show: true, width: c.width })),
      ...gridFields(meta).filter((f) => !names.has(f.fieldname)).map((f) => ({ fieldname: f.fieldname, label: f.label, type: f.fieldtype, show: false, width: defaultColumnWidth(f) })),
    ];
  });
  const shownCols = items.filter((i) => i.show);
  const problem = !shownCols.length ? "Show at least one column" : "";
  const dragName = useRef<string | null>(null);
  const patch = (name: string, p: Partial<Item>) => setItems((l) => l.map((i) => (i.fieldname === name ? { ...i, ...p } : i)));
  const moveVisible = (l: Item[], from: string, to: string): Item[] => {
    const visible = l.map((item, index) => ({ item, index })).filter((x) => x.item.show);
    const a = visible.find((x) => x.item.fieldname === from)?.index;
    const b = visible.find((x) => x.item.fieldname === to)?.index;
    if (a === undefined || b === undefined || a === b) return l;
    // Swap the actual slots rather than splicing across hidden entries. This
    // guarantees a visible column really changes position even when hidden
    // fields are interleaved in the configuration list.
    const next = [...l];
    [next[a], next[b]] = [next[b], next[a]];
    return next;
  };
  const swap = (name: string, dir: -1 | 1) => setItems((l) => {
    const visible = l.filter((item) => item.show);
    const at = visible.findIndex((item) => item.fieldname === name), target = at + dir;
    if (at < 0 || target < 0 || target >= visible.length) return l;
    return moveVisible(l, name, visible[target].fieldname);
  });
  const moveTo = (from: string, to: string) => setItems((l) => moveVisible(l, from, to));
  const out = (): GridColumn[] => shownCols.map((i) => ({ field: i.fieldname, width: i.width }));
  return (
    <Dialog title="Configure columns" onClose={onClose} wide footer={<>
      <button type="button" className="rbtn" onClick={onReset}>Reset to default</button>
      <button type="button" className="rbtn primary" disabled={!!problem} onClick={() => onSave(out(), "me")}>Save for me</button>
      {canCustomize && <button type="button" className="rbtn" disabled={!!problem} onClick={() => onSave(out(), "everyone")}>Save for everyone</button>}
    </>}>
      <p className={problem ? "error" : "muted"} role={problem ? "alert" : undefined}>{problem || `${shownCols.length} columns selected · no fixed column limit`}</p>
      {onFreeze && <label className="freeze-setting">Keep the first <input type="number" min={0} max={12} aria-label="Frozen columns" value={freeze ?? 5} onChange={(e) => onFreeze(Math.max(0, Math.min(12, Number(e.target.value) || 0)))} /> columns in view while scrolling sideways (0 turns it off)</label>}
      <ul className="cols-list">
        {items.map((i) => {
          const visibleIndex = shownCols.findIndex((x) => x.fieldname === i.fieldname);
          return <li key={i.fieldname} className={i.show ? "on" : ""} draggable={i.show} onDragStart={(e) => { dragName.current = i.fieldname; if (e.dataTransfer) { e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", i.fieldname); } catch { /* jsdom */ } } }} onDragOver={(e) => { if (dragName.current && i.show) { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = "move"; } }} onDrop={(e) => { e.preventDefault(); if (dragName.current) moveTo(dragName.current, i.fieldname); dragName.current = null; }} onDragEnd={() => { dragName.current = null; }}>
            <label><input type="checkbox" checked={i.show} aria-label={`Show ${i.label}`} onChange={(e) => patch(i.fieldname, { show: e.target.checked })} /> <span>{i.label}</span> <span className="ptype">{i.type}</span>{i.show && <span className="muted" title="Drag to reorder" aria-hidden="true">⠿</span>}</label>
            {i.show && <>
              <button type="button" className="icon-btn" aria-label={`Narrower: ${i.label}`} disabled={i.width <= 1} onClick={() => patch(i.fieldname, { width: i.width - 1 })}>−</button>
              <span className="w" aria-label={`Width of ${i.label}`}>{i.width}</span>
              <button type="button" className="icon-btn" aria-label={`Wider: ${i.label}`} disabled={i.width >= MAX_WIDTH} onClick={() => patch(i.fieldname, { width: Math.min(MAX_WIDTH, i.width + 1) })}>+</button>
              <button type="button" className="icon-btn" aria-label={`Move up: ${i.label}`} disabled={visibleIndex <= 0} onClick={() => swap(i.fieldname, -1)}><Icon name="up" size={14} /></button>
              <button type="button" className="icon-btn" aria-label={`Move down: ${i.label}`} disabled={visibleIndex === shownCols.length - 1} onClick={() => swap(i.fieldname, 1)}><Icon name="down" size={14} /></button>
            </>}
          </li>;
        })}
      </ul>
    </Dialog>
  );
}
