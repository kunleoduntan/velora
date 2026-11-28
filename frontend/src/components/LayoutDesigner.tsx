import { askConfirm, askPrompt, askAlert } from "../ui/ask";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, clearCaches, errorMessage, type LayoutInfo } from "../api";
import * as L from "../layoutModel";
import type { Field, FieldAppearance, GridLayout } from "../types";
import Icon from "../ui/Icon";

type Drag = { kind: "cell" | "palette"; field: string } | null;
let dragging: Drag = null;                       // set on dragstart; read on drop (dataTransfer is not readable during dragover, and absent in tests)

const PRESETS: [string, number][] = [["¼", 3], ["⅓", 4], ["½", 6], ["⅔", 8], ["¾", 9], ["Full", 12]];

/** Customize a form like a form designer: drag fields onto a 12-column grid, resize them, group them into sections and tabs. */
export default function LayoutDesigner({ doctype }: { doctype: string }) {
  const [info, setInfo] = useState<LayoutInfo | null>(null);
  const [layout, setLayout] = useState<GridLayout | null>(null);
  const [appearance, setAppearance] = useState<Record<string, FieldAppearance>>({});
  const [savedAppearance, setSavedAppearance] = useState("{}");
  const [past, setPast] = useState<GridLayout[]>([]);
  const [future, setFuture] = useState<GridLayout[]>([]);
  const [saved, setSaved] = useState("");
  const [tab, setTab] = useState(0);
  const [sel, setSel] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState("");

  async function load() {
    try {
      const i = await api.layoutGet(doctype);
      setInfo(i); setLayout(i.layout); setSaved(JSON.stringify(i.layout)); setAppearance(i.appearance ?? {}); setSavedAppearance(JSON.stringify(i.appearance ?? {})); setPast([]); setFuture([]); setTab(0); setSel(null);
    } catch (e) { setError(errorMessage(e)); }
  }
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [doctype]);

  const fields = useMemo(() => Object.fromEntries((info?.fields ?? []).map((f) => [f.fieldname, f])) as Record<string, Field>, [info]);
  const editable = !!info?.editable;
  const dirty = !!layout && JSON.stringify(layout) !== saved;
  const appearanceDirty = JSON.stringify(appearance) !== savedAppearance;
  const palette = useMemo(() => (layout && info ? L.unplaced(layout, info.fields).filter((f) => !q || `${f.label} ${f.fieldname}`.toLowerCase().includes(q.toLowerCase())) : []), [layout, info, q]);
  const t = Math.min(tab, (layout?.tabs.length ?? 1) - 1);

  function apply(fn: (l: GridLayout) => GridLayout) {
    if (!layout || !editable) return;
    try {
      const next = fn(layout);
      setPast((p) => [...p, layout]); setFuture([]); setLayout(next); setError(""); setNote("");
    } catch (e) { setError(e instanceof L.LayoutError ? e.message : errorMessage(e)); }
  }
  const undo = () => { if (past.length && layout) { setFuture((f) => [layout, ...f]); setLayout(past[past.length - 1]); setPast(past.slice(0, -1)); } };
  const redo = () => { if (future.length && layout) { setPast((p) => [...p, layout]); setLayout(future[0]); setFuture(future.slice(1)); } };

  async function save(target: "company" | "app") {
    if (!layout) return;
    const problems = L.validate(layout);
    if (problems.length) return setError(problems.join("; "));
    setBusy(true); setError(""); setNote("");
    try {
      const res = await api.layoutSave(doctype, layout, target);
      clearCaches();                                                  // the form must fetch the new layout, not the cached old one
      setNote(res.note ? res.note : target === "app" ? "Saved into the app's DocType file." : "Saved for everyone in this company.");
      await load();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function saveAppearance() {
    setBusy(true); setError(""); setNote("");
    try {
      const result = await api.saveFormAppearance(doctype, appearance);
      setAppearance(result.appearance); setSavedAppearance(JSON.stringify(result.appearance));
      clearCaches(); setNote("Field presentation settings saved for this company.");
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function resetAppearance() {
    if (!await askConfirm("Reset all field presentation settings for this DocType?")) return;
    setBusy(true); setError(""); setNote("");
    try {
      await api.resetFormAppearance(doctype);
      setAppearance({}); setSavedAppearance("{}"); clearCaches();
      setNote("Field presentation settings have been reset.");
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  function updateAppearance(fieldname: string, patch: Partial<FieldAppearance>) {
    setAppearance((current) => {
      const next = { ...current, [fieldname]: { ...(current[fieldname] ?? {}), ...patch } };
      if (Object.values(next[fieldname]).every((v) => v === undefined || v === "")) delete next[fieldname];
      return next;
    });
  }

  async function reset() {
    if (!await askConfirm("Remove this company's layout and go back to the app's?")) return;
    setBusy(true);
    try { await api.layoutReset(doctype); clearCaches(); setNote("Back to the default layout."); await load(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  // ---- drag and drop ----------------------------------------------------------------------------------------------
  function dropTo(to: L.Drop) {
    const d = dragging;
    dragging = null; setOver("");
    if (!d) return;
    apply((l) => (d.kind === "cell" ? L.moveField(l, d.field, to) : L.placeField(l, fields[d.field], to)));
  }
  function zone(id: string, to: L.Drop, label: string, cls = "dropzone") {
    return (
      <div key={id} className={`${cls}${over === id ? " over" : ""}`} data-testid={`drop-${id}`} aria-label={label}
        onDragOver={(e) => { if (dragging) { e.preventDefault(); setOver(id); } }} onDragLeave={() => setOver((o) => (o === id ? "" : o))}
        onDrop={(e) => { e.preventDefault(); dropTo(to); }} />
    );
  }
  const startDrag = (kind: "cell" | "palette", field: string) => (e: React.DragEvent) => {
    dragging = { kind, field };
    try { e.dataTransfer.setData("text/plain", field); e.dataTransfer.effectAllowed = "move"; } catch { /* not available in every environment */ }
  };

  function resizeByPointer(e: React.PointerEvent, field: string, rowEl: HTMLElement | null) {
    if (!rowEl) return;
    const rect = rowEl.getBoundingClientRect();
    if (!rect.width) return;
    const cellLeft = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect().left;
    const col = rect.width / 12;
    const move = (ev: PointerEvent) => apply((l) => L.resizeField(l, field, Math.round((ev.clientX - cellLeft) / col)));
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  }

  if (!info || !layout) return <div className="panel">{error ? <div className="error" role="alert">{error}</div> : "Loading…"}</div>;
  const tabNow = layout.tabs[t];
  const sectionTarget = (): { tab: number; section: number } => (sel && L.find(layout, sel)) ? { tab: L.find(layout, sel)!.tab, section: L.find(layout, sel)!.section } : { tab: t, section: 0 };

  return (
    <div className="designer">
      <header className="page-head">
        <div className="titles"><h1>Customize form: {doctype}</h1>
          <span className={`pill pill-${info.source === "auto" ? "draft" : "saved"}`}>{info.source === "company" ? "Company layout" : info.source === "app" ? "App layout" : "Not customised yet"}</span></div>
      </header>
      <div className="ribbon" role="toolbar" aria-label="Designer actions">
        {editable && <>
          <button type="button" className="rbtn primary" disabled={busy || !dirty} onClick={() => save("company")}><Icon name="save" /><span>Save layout</span></button>
          <button type="button" className="rbtn" disabled={busy || !appearanceDirty} onClick={saveAppearance}><Icon name="sliders" /><span>Save field design</span></button>
          <button type="button" className="rbtn" disabled={busy || !Object.keys(appearance).length} onClick={resetAppearance}><Icon name="refresh" /><span>Reset field design</span></button>
          {info.can_write_app && <button type="button" className="rbtn" disabled={busy || !dirty} onClick={() => save("app")}><Icon name="download" /><span>Save into the app</span></button>}
          <button type="button" className="rbtn" disabled={!past.length} onClick={undo}><Icon name="refresh" /><span>Undo</span></button>
          <button type="button" className="rbtn" disabled={!future.length} onClick={redo}><span>Redo</span></button>
          {info.source === "company" && <button type="button" className="rbtn danger" disabled={busy} onClick={reset}><Icon name="trash" /><span>Reset to default</span></button>}
          <span className="rsep" />
        </>}
        <a className="rbtn" href={`#/app/${encodeURIComponent(doctype)}/new`}><span>Open the form</span></a>
      </div>
      {!editable && <div className="intro">Only a System Manager can change this layout.</div>}
      {error && <div className="error" role="alert">{error}</div>}
      {note && <div className="success" role="status">{note}</div>}

      <div className="designer-intro">
        <div><strong>Design the user experience</strong><span>Changes affect presentation only. Your DocType fields, database columns and existing records remain unchanged.</span></div>
        <div className="designer-hints"><span><Icon name="move" size={14}/> Drag to reposition</span><span><Icon name="arrow-left-right" size={14}/> Resize to align</span><span><Icon name="layers" size={14}/> Organise with tabs and sections</span></div>
      </div>
      <div className="designer-grid">
        <aside className="palette" aria-label="Fields not on the form">
          <h3>Not on the form <span className="muted">({palette.length})</span></h3>
          <input type="search" aria-label="Search fields" placeholder="Search fields…" value={q} onChange={(e) => setQ(e.target.value)} />
          {palette.length === 0 && <p className="muted">{q ? "No match." : "Every field is on the form."}</p>}
          {palette.map((f) => (
            <div key={f.fieldname} className="pitem" draggable={editable} onDragStart={startDrag("palette", f.fieldname)} onDragEnd={() => { dragging = null; setOver(""); }}>
              <Icon name="grip" size={14} /><span className="pname">{f.label}</span><span className="ptype">{f.fieldtype}</span>
              {editable && <button type="button" className="icon-btn" aria-label={`Add ${f.label} to the form`} onClick={() => { const at = sectionTarget(); apply((l) => L.placeField(l, f, { ...at, row: null })); setSel(f.fieldname); }}><Icon name="plus" size={14} /></button>}
            </div>
          ))}
          {sel && L.find(layout, sel) && (() => {
            const pos = L.find(layout, sel)!;
            const field = fields[sel];
            const cell = layout.tabs[pos.tab].sections[pos.section].rows[pos.row][pos.index];
            return <div className="field-inspector" aria-label="Selected field properties">
              <div className="inspector-title"><Icon name="sliders" size={15} /><strong>Field properties</strong></div>
              <div className="inspector-name">{field?.label ?? sel}</div>
              <small>{field?.fieldtype ?? "Field"} · {sel}</small>
              <label>Width
                <select aria-label="Selected field width" value={cell.span} disabled={!editable} onChange={(e) => apply((l) => L.resizeField(l, sel, Number(e.target.value)))}>
                  {[1,2,3,4,5,6,7,8,9,10,11,12].map((n) => <option key={n} value={n}>{n}/12 · {Math.round(n/12*100)}%</option>)}
                </select>
              </label>
              <div className="appearance-editor">
                <div className="appearance-heading">Control appearance</div>
                <label>Label position
                  <select value={appearance[sel]?.label_position ?? "top"} disabled={!editable} onChange={(e) => updateAppearance(sel, { label_position: e.target.value as FieldAppearance["label_position"] })}>
                    <option value="top">Above control</option><option value="left">Left of control</option>
                  </select>
                </label>
                <label>Control size
                  <select value={appearance[sel]?.control_size ?? "medium"} disabled={!editable} onChange={(e) => updateAppearance(sel, { control_size: e.target.value as FieldAppearance["control_size"] })}>
                    <option value="small">Small · 30px</option><option value="medium">Medium · 36px</option><option value="large">Large · 44px</option>
                  </select>
                </label>
                <label>Display style
                  <select value={appearance[sel]?.display_style ?? "standard"} disabled={!editable} onChange={(e) => updateAppearance(sel, { display_style: e.target.value as FieldAppearance["display_style"] })}>
                    <option value="standard">Standard</option><option value="compact">Compact</option><option value="emphasized">Emphasized</option>
                  </select>
                </label>
                <label>Placeholder
                  <input value={appearance[sel]?.placeholder ?? ""} maxLength={500} disabled={!editable} placeholder="Enter a helpful prompt" onChange={(e) => updateAppearance(sel, { placeholder: e.target.value })} />
                </label>
                <label>Help text override
                  <textarea value={appearance[sel]?.help_text ?? ""} maxLength={500} disabled={!editable} rows={2} placeholder="Optional guidance below the control" onChange={(e) => updateAppearance(sel, { help_text: e.target.value })} />
                </label>
                <label className="appearance-check"><input type="checkbox" checked={appearance[sel]?.show_description !== false} disabled={!editable} onChange={(e) => updateAppearance(sel, { show_description: e.target.checked })} /> Show DocType description</label>
                <label className="appearance-check"><input type="checkbox" checked={!!appearance[sel]?.readonly_style} disabled={!editable} onChange={(e) => updateAppearance(sel, { readonly_style: e.target.checked })} /> Emphasise read-only state</label>
              </div>
              <div className="inspector-actions">
                <button type="button" className="rbtn" disabled={!editable || pos.index === 0} onClick={() => apply((l) => L.moveField(l, sel, { tab: pos.tab, section: pos.section, row: pos.row, index: pos.index - 1 }))}>Move left</button>
                <button type="button" className="rbtn" disabled={!editable} onClick={() => apply((l) => L.moveField(l, sel, { tab: pos.tab, section: pos.section, row: null, rowAt: pos.row + 1 }))}>New row</button>
                <button type="button" className="rbtn" disabled={!editable} onClick={() => { apply((l) => L.unplaceField(l, sel)); setSel(null); }}>Remove</button>
              </div>
            </div>;
          })()}
        </aside>

        <section className="canvas" aria-label="Form layout design canvas">
          <div className="canvas-heading">
            <div><strong>Form canvas</strong><small>Arrange fields on a 12-column grid. Drag to reposition; resize to control alignment and width.</small></div>
            <span className="canvas-grid-badge">12-column grid</span>
          </div>
          <nav className="tabs" role="tablist">
            {layout.tabs.map((tb, i) => <button key={i} role="tab" type="button" aria-selected={i === t} className={i === t ? "active" : ""} onClick={() => setTab(i)}>{tb.label || `Tab ${i + 1}`}</button>)}
            {editable && <button type="button" className="rbtn" aria-label="Add tab" onClick={() => { apply((l) => L.addTab(l)); setTab(layout.tabs.length); }}><Icon name="plus" /><span>Tab</span></button>}
          </nav>
          {editable && tabNow && (
            <div className="tab-tools">
              <input aria-label="Tab name" value={tabNow.label} onChange={(e) => apply((l) => L.renameTab(l, t, e.target.value))} />
              <button type="button" className="icon-btn" aria-label="Move tab left" disabled={t === 0} onClick={() => { apply((l) => L.moveTab(l, t, -1)); setTab(t - 1); }}><Icon name="left" size={14} /></button>
              <button type="button" className="icon-btn" aria-label="Move tab right" disabled={t >= layout.tabs.length - 1} onClick={() => { apply((l) => L.moveTab(l, t, 1)); setTab(t + 1); }}><Icon name="right" size={14} /></button>
              <button type="button" className="icon-btn" aria-label="Delete tab" disabled={layout.tabs.length <= 1} onClick={() => { apply((l) => L.removeTab(l, t)); setTab(0); }}><Icon name="trash" size={14} /></button>
            </div>
          )}
          {tabNow?.sections.map((s, si) => {
            const at = { tab: t, section: si };
            return (
              <div key={si} className="dsection" data-testid={`section-${si}`}>
                <div className="dsec-head">
                  {editable ? <input aria-label={`Section ${si + 1} title`} value={s.label} placeholder="(no title)" onChange={(e) => apply((l) => L.updateSection(l, at, { label: e.target.value }))} /> : <strong>{s.label || "(no title)"}</strong>}
                  {s.auto && <span className="ptype">added automatically</span>}
                  {editable && <>
                    <label className="chk-inline"><input type="checkbox" checked={!!s.collapsible} onChange={(e) => apply((l) => L.updateSection(l, at, { collapsible: e.target.checked }))} /> Collapsible</label>
                    <button type="button" className="icon-btn" aria-label={`Move section ${si + 1} up`} disabled={si === 0} onClick={() => apply((l) => L.moveSection(l, at, -1))}><Icon name="up" size={14} /></button>
                    <button type="button" className="icon-btn" aria-label={`Move section ${si + 1} down`} disabled={si >= tabNow.sections.length - 1} onClick={() => apply((l) => L.moveSection(l, at, 1))}><Icon name="down" size={14} /></button>
                    <button type="button" className="icon-btn" aria-label={`Delete section ${si + 1}`} onClick={() => apply((l) => L.removeSection(l, at))}><Icon name="trash" size={14} /></button>
                  </>}
                </div>
                {s.rows.map((row, ri) => (
                  <div key={ri} className="drow-wrap">
                    {editable && zone(`${t}:${si}:above-${ri}`, { ...at, row: null, rowAt: ri }, "Drop here for a new row")}
                    <RowView row={row} at={at} ri={ri} s={s} fields={fields} sel={sel} editable={editable} apply={apply} setSel={setSel} zone={zone} startDrag={startDrag} resizeByPointer={resizeByPointer}
                      onDragEnd={() => { dragging = null; setOver(""); }} nRows={s.rows.length} />
                  </div>
                ))}
                {editable && zone(`${t}:${si}:end`, { ...at, row: null, rowAt: s.rows.length }, "Drop here for a new row", "dropzone end")}
              </div>
            );
          })}
          {editable && <button type="button" className="rbtn" onClick={() => apply((l) => L.addSection(l, t))}><Icon name="plus" /><span>Add section</span></button>}
        </section>
      </div>
    </div>
  );
}

interface RowProps {
  row: GridLayout["tabs"][0]["sections"][0]["rows"][0]; at: { tab: number; section: number }; ri: number; s: GridLayout["tabs"][0]["sections"][0]; nRows: number;
  fields: Record<string, Field>; sel: string | null; editable: boolean;
  apply: (fn: (l: GridLayout) => GridLayout) => void; setSel: (f: string | null) => void;
  zone: (id: string, to: L.Drop, label: string, cls?: string) => React.ReactNode;
  startDrag: (kind: "cell" | "palette", field: string) => (e: React.DragEvent) => void;
  resizeByPointer: (e: React.PointerEvent, field: string, rowEl: HTMLElement | null) => void;
  onDragEnd: () => void;
}

function RowView({ row, at, ri, s, fields, sel, editable, apply, setSel, zone, startDrag, resizeByPointer, onDragEnd, nRows }: RowProps) {
  const ref = useRef<HTMLDivElement>(null);
  const free = 12 - L.rowSum(row);
  const rowAt = { ...at, row: ri };
  return (
    <div className="drow-line">
      <div className="drow" ref={ref}>
        {row.map((c, ci) => {
          const f = fields[c.field];
          const cell = { ...at, row: ri, index: ci };
          return (
            <div key={c.field} className={`dcell${sel === c.field ? " selected" : ""}`} style={{ gridColumn: `span ${c.span}` }} draggable={editable} data-field={c.field} data-span={c.span}
              onDragStart={startDrag("cell", c.field)} onDragEnd={onDragEnd} onClick={() => setSel(c.field)}>
              {editable && zone(`${at.tab}:${at.section}:${ri}:before-${ci}`, { ...at, row: ri, index: ci }, `Drop before ${f?.label ?? c.field}`, "dropzone before")}
              <div className="dcell-body">
                <span className="dname">{f?.label ?? c.field}{f?.required && <span className="req"> *</span>}</span>
                <span className="ptype">{f?.fieldtype ?? "?"} · {c.span}/12</span>
              </div>
              {editable && (
                <div className="dcell-tools">
                  <button type="button" className="icon-btn" aria-label={`Narrower: ${f?.label ?? c.field}`} disabled={c.span <= 1} onClick={() => apply((l) => L.resizeField(l, c.field, c.span - 1))}>−</button>
                  <button type="button" className="icon-btn" aria-label={`Wider: ${f?.label ?? c.field}`} disabled={c.span >= 12} onClick={() => apply((l) => L.resizeField(l, c.field, c.span + 1))}>+</button>
                  <select aria-label={`Width of ${f?.label ?? c.field}`} value={PRESETS.some(([, n]) => n === c.span) ? c.span : ""} onChange={(e) => e.target.value && apply((l) => L.resizeField(l, c.field, Number(e.target.value)))}>
                    <option value="" disabled>{c.span}/12</option>{PRESETS.map(([n, v]) => <option key={v} value={v}>{n}</option>)}
                  </select>
                  <button type="button" className="icon-btn" aria-label={`Move left: ${f?.label ?? c.field}`} disabled={ci === 0} onClick={() => apply((l) => L.moveField(l, c.field, { ...rowAt, index: ci - 1 }))}><Icon name="left" size={14} /></button>
                  <button type="button" className="icon-btn" aria-label={`Move right: ${f?.label ?? c.field}`} disabled={ci >= row.length - 1} onClick={() => apply((l) => L.moveField(l, c.field, { ...rowAt, index: ci + 2 }))}><Icon name="right" size={14} /></button>
                  <button type="button" className="icon-btn" aria-label={`Move up: ${f?.label ?? c.field}`} onClick={() => apply((l) => (ri > 0 ? L.moveField(l, c.field, { ...at, row: ri - 1, index: ci }) : L.moveField(l, c.field, { ...at, row: null, rowAt: 0 })))}><Icon name="up" size={14} /></button>
                  <button type="button" className="icon-btn" aria-label={`Move down: ${f?.label ?? c.field}`} onClick={() => apply((l) => (ri < nRows - 1 ? L.moveField(l, c.field, { ...at, row: ri + 1, index: ci }) : L.moveField(l, c.field, { ...at, row: null, rowAt: nRows })))}><Icon name="down" size={14} /></button>
                  <button type="button" className="icon-btn" aria-label={`Remove from the form: ${f?.label ?? c.field}`} onClick={() => { apply((l) => L.unplaceField(l, c.field)); setSel(null); }}><Icon name="x" size={14} /></button>
                </div>
              )}
              {editable && (
                <div role="slider" tabIndex={0} className="resize-handle" aria-label={`Resize ${f?.label ?? c.field}`} aria-valuemin={1} aria-valuemax={12} aria-valuenow={c.span}
                  onPointerDown={(e) => resizeByPointer(e, c.field, ref.current)}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowRight") { e.preventDefault(); apply((l) => L.resizeField(l, c.field, c.span + 1)); }
                    if (e.key === "ArrowLeft") { e.preventDefault(); apply((l) => L.resizeField(l, c.field, c.span - 1)); }
                  }} />
              )}
            </div>
          );
        })}
        {editable && free > 0 && <div className="dfree" style={{ gridColumn: `span ${free}` }}>{zone(`${at.tab}:${at.section}:${ri}:fill`, { ...at, row: ri }, "Drop to fill this row", "dropzone fill")}<span>{free} free</span></div>}
      </div>
      {editable && (
        <div className="row-tools">
          <button type="button" className="icon-btn" aria-label={`Equal widths in section ${at.section + 1}, row ${ri + 1}`} onClick={() => apply((l) => L.equalizeRow(l, rowAt))}>=</button>
          <button type="button" className="icon-btn" aria-label={`Move section ${at.section + 1} row ${ri + 1} up`} disabled={ri === 0} onClick={() => apply((l) => L.moveRow(l, rowAt, -1))}><Icon name="up" size={14} /></button>
          <button type="button" className="icon-btn" aria-label={`Move section ${at.section + 1} row ${ri + 1} down`} disabled={ri >= s.rows.length - 1} onClick={() => apply((l) => L.moveRow(l, rowAt, 1))}><Icon name="down" size={14} /></button>
        </div>
      )}
    </div>
  );
}
