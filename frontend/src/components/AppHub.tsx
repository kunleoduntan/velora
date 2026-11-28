import { useEffect, useMemo, useRef, useState } from "react";
import Icon from "../ui/Icon";
import { visibleHubs, type HubItem } from "../hubs";
import type { DocTypeInfo } from "../types";
import type { ReportInfo } from "../api";
import { EMPTY_LAYOUT, addSection, addShortcut, arrange, editShortcut, isCustomised, moveItem, moveSection, nudgeItem, readLayout, removeItem, removeSection, resetLayout, restoreItem, writeLayout, type HubLayout } from "../hubLayout";

const FAV_KEY = "velora.hub.favourites";
const readFavs = (): string[] => { try { const v = JSON.parse(localStorage.getItem(FAV_KEY) ?? "[]"); return Array.isArray(v) ? v.filter(x => typeof x === "string") : []; } catch { return []; } };
const writeFavs = (v: string[]) => { try { localStorage.setItem(FAV_KEY, JSON.stringify(v)); } catch { /* storage blocked: favourites are simply not kept */ } };

const TABS: [string, string][] = [["all", "All"], ["doctype", "Documents"], ["report", "Reports"], ["centre", "Centres"], ["fav", "Favourites"]];
const KIND: Record<HubItem["kind"], string> = { doctype: "Document", report: "Report", centre: "Centre" };

/** The App Hub: with no hub chosen, a tile per application; with one, everything in it (search, tabs, favourites) on one page. */
export default function AppHub({ types, reports, hubId }: { types: DocTypeInfo[]; reports: ReportInfo[]; hubId?: string }) {
  const hubs = useMemo(() => visibleHubs(types, reports), [types, reports]);
  const [q, setQ] = useState(""), [tab, setTab] = useState("all"), [favs, setFavs] = useState<string[]>(readFavs);
  const guides = useMemo(() => {
    const seen = new Map<string, string>([["/tutorial", "Velora framework manual"]]);
    for (const { hub } of hubs) if (hub.guide) seen.set(hub.guide, hub.guideTitle ?? hub.title);
    return [...seen].map(([url, title]) => ({ url, title }));
  }, [hubs]);
  const current = hubId ? hubs.find(h => h.hub.id === hubId) : undefined;
  const [layout, setLayoutState] = useState<HubLayout>(() => hubId ? readLayout(hubId) : EMPTY_LAYOUT);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<{ key?: string; label: string; href: string; section: string } | null>(null);
  const [formError, setFormError] = useState(""), [newSection, setNewSection] = useState("");
  const drag = useRef<{ kind: "item"; key: string } | { kind: "section"; name: string } | null>(null);
  useEffect(() => { setLayoutState(hubId ? readLayout(hubId) : EMPTY_LAYOUT); setEditing(false); setForm(null); }, [hubId]);
  const setLayout = (next: HubLayout) => { setLayoutState(next); if (hubId) writeLayout(hubId, next); };

  if (!current) {
    return (
      <div className="panel hub">
        <div className="hub-head"><div><h1>App Hub</h1><p className="muted">Every application you can use, each with its own hub of documents, reports and centres.</p></div></div>
        <div className="hub-guides"><b>How-to guides</b>{guides.map(g => <a key={g.url} className="hub-chip" href={g.url} target="_blank" rel="noopener">{g.title} ↗</a>)}</div>
        {hubId && <div className="error" role="alert">There is no “{hubId}” hub, or you cannot open anything in it.</div>}
        <div className="hub-tiles">
          {hubs.map(({ hub, items }) => (
            <a key={hub.id} className="hub-tile" href={`#/hub/${hub.id}`} style={{ ["--hub" as string]: hub.color }}>
              <span className="hub-tile-icon"><Icon name={hub.icon} size={22} /></span>
              <strong>{hub.title}</strong><small>{hub.blurb}</small>
              <span className="hub-tile-count">{items.filter(i => i.kind === "doctype").length} documents · {items.filter(i => i.kind === "report").length} reports</span>
            </a>
          ))}
          {hubs.length === 0 && <p className="muted">Nothing is available to your account yet.</p>}
        </div>
      </div>
    );
  }

  const { hub, items } = current;
  const term = q.trim().toLowerCase();
  const natural = ["Centres", ...(hub.sections?.map(s => s.name) ?? []), "Setup & Other", "Reports"];
  const view = arrange(items, natural, layout);                                   // the person's arrangement of the page
  const matches = (i: HubItem) => editing || ((tab === "all" || (tab === "fav" ? favs.includes(i.key) : i.kind === tab)) && (!term || `${i.label} ${i.section} ${i.words ?? ""}`.toLowerCase().includes(term)));
  const visibleSections = editing ? view : view.map(s => ({ name: s.name, items: s.items.filter(matches) })).filter(s => s.items.length > 0);
  const shownCount = view.reduce((n, s) => n + s.items.filter(matches).length, 0);
  const hiddenItems = items.filter(i => layout.hidden.includes(i.key));
  const kindOf = (i: HubItem & { key: string }) => i.key.startsWith("custom|") ? "Shortcut" : KIND[i.kind];
  const toggle = (key: string) => { const next = favs.includes(key) ? favs.filter(f => f !== key) : [...favs, key].slice(-60); setFavs(next); writeFavs(next); };
  const favItems = view.flatMap(s => s.items).filter(i => favs.includes(i.key));
  const sectionNames = view.map(s => s.name);
  const dropOnItem = (e: React.DragEvent, section: string, key: string) => { e.preventDefault(); e.stopPropagation(); const d = drag.current; drag.current = null; if (d?.kind === "item" && d.key !== key) setLayout(moveItem(layout, view, d.key, section, key)); };
  const dropOnSection = (e: React.DragEvent, name: string) => { e.preventDefault(); const d = drag.current; drag.current = null; if (!d) return; setLayout(d.kind === "item" ? moveItem(layout, view, d.key, name) : d.name !== name ? moveSection(layout, view, d.name, name) : layout); };
  const submitForm = () => {
    if (!form) return;
    const r = form.key ? editShortcut(layout, form.key, form.label, form.href) : addShortcut(layout, form.label, form.href, form.section || sectionNames[0] || "Centres");
    if (r.error) { setFormError(r.error); return; }
    setFormError(""); setForm(null); setLayout(r.layout);
  };

  return (
    <div className="panel hub" style={{ ["--hub" as string]: hub.color }}>
      <div className="hub-head">
        <a className="hub-back" href="#/hub"><Icon name="left" size={14} /> App Hub</a>
        <div className="hub-title"><span className="hub-tile-icon"><Icon name={hub.icon} size={22} /></span><div><h1>{hub.title}</h1><p className="muted">{hub.blurb}</p></div></div>
        {(hub.intro || hub.guide) && <p className="hub-intro">{hub.intro} {hub.guide && <a className="hub-guide" href={hub.guide} target="_blank" rel="noopener">How-to guide ↗</a>}</p>}
        <div className="hub-tools">
          <div className="hub-search"><Icon name="search" size={15} /><input type="search" autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder={`Search ${hub.title}…`} aria-label={`Search ${hub.title}`} /></div>
          <button type="button" className={`btn${editing ? " primary" : ""}`} aria-pressed={editing} onClick={() => { setEditing(!editing); setForm(null); setFormError(""); }}><Icon name="sliders" size={14} /> {editing ? "Done" : "Customise"}</button>
        </div>
      </div>
      <div className="hub-tabs" role="tablist">{TABS.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>{label}</button>)}</div>
      {editing && (
        <div className="hub-edit" role="region" aria-label="Customise this hub">
          <p className="muted">Drag a shortcut to move it, in a section or to another one; drag a section by its grip to reorder the sections. The arrows do the same from the keyboard. Your arrangement is kept for you only.</p>
          <div className="hub-edit-actions">
            <button type="button" className="btn" onClick={() => { setForm({ label: "", href: "#/", section: sectionNames[0] ?? "Centres" }); setFormError(""); }}><Icon name="plus" size={14} /> Add shortcut</button>
            <span className="hub-newsec"><input value={newSection} onChange={e => setNewSection(e.target.value)} placeholder="New section name" aria-label="New section name" />
              <button type="button" className="btn" onClick={() => { const r = addSection(layout, view, newSection); if (r.error) setFormError(r.error); else { setFormError(""); setNewSection(""); setLayout(r.layout); } }}>Add section</button></span>
            {isCustomised(layout) && <button type="button" className="btn" onClick={() => { resetLayout(hub.id); setLayoutState(EMPTY_LAYOUT); }}>Reset to standard layout</button>}
          </div>
          {form && (
            <div className="hub-form" role="group" aria-label={form.key ? "Edit shortcut" : "Add shortcut"}>
              <label>Name<input value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} /></label>
              <label>Opens<input value={form.href} list="hub-routes" onChange={e => setForm({ ...form, href: e.target.value })} /></label>
              <datalist id="hub-routes">{items.map(i => <option key={i.key} value={i.href}>{i.label}</option>)}</datalist>
              {!form.key && <label>Section<input value={form.section} list="hub-sections" onChange={e => setForm({ ...form, section: e.target.value })} /></label>}
              <datalist id="hub-sections">{sectionNames.map(n => <option key={n} value={n} />)}</datalist>
              <button type="button" className="btn primary" onClick={submitForm}>{form.key ? "Save shortcut" : "Add"}</button>
              <button type="button" className="btn" onClick={() => { setForm(null); setFormError(""); }}>Cancel</button>
            </div>
          )}
          {formError && <div className="error" role="alert">{formError}</div>}
          {hiddenItems.length > 0 && <div className="hub-hidden"><b>Hidden</b>{hiddenItems.map(i => <button key={i.key} type="button" className="hub-chip" onClick={() => setLayout(restoreItem(layout, i.key))}>＋ {i.label}</button>)}</div>}
        </div>
      )}
      {!editing && tab === "all" && !term && favItems.length > 0 && <div className="hub-fav-row"><b>★ Favourites</b>{favItems.map(i => <a key={i.key} className="hub-chip" href={i.href}>{i.label}</a>)}</div>}
      <div className="hub-cols">
        {visibleSections.map((sec, si) => {
          const list = editing ? sec.items : sec.items.filter(matches);
          return (
            <section key={sec.name} className={`hub-card${editing ? " editing" : ""}`} aria-label={sec.name}
              onDragOver={editing ? e => e.preventDefault() : undefined} onDrop={editing ? e => dropOnSection(e, sec.name) : undefined}>
              <h2 draggable={editing} onDragStart={editing ? e => { drag.current = { kind: "section", name: sec.name }; e.dataTransfer?.setData("text/plain", sec.name); } : undefined}>
                {editing && <span className="hub-grip" title="Drag to reorder this section"><Icon name="grip" size={14} /></span>}
                {sec.name}<span>{list.length}</span>
                {editing && <span className="hub-sec-tools">
                  <button type="button" aria-label={`Move section ${sec.name} earlier`} disabled={si === 0} onClick={() => setLayout(moveSection(layout, view, sec.name, view[si - 1]?.name))}>↑</button>
                  <button type="button" aria-label={`Move section ${sec.name} later`} disabled={si === view.length - 1} onClick={() => setLayout(moveSection(layout, view, sec.name, view[si + 2]?.name))}>↓</button>
                  {list.length === 0 && layout.extra.includes(sec.name) && <button type="button" aria-label={`Remove section ${sec.name}`} onClick={() => setLayout(removeSection(layout, sec.name))}>✕</button>}
                </span>}
              </h2>
              <ul>{list.map(i => (
                <li key={i.key} draggable={editing} data-key={i.key}
                  onDragStart={editing ? e => { drag.current = { kind: "item", key: i.key }; e.dataTransfer?.setData("text/plain", i.key); } : undefined}
                  onDragOver={editing ? e => e.preventDefault() : undefined} onDrop={editing ? e => dropOnItem(e, sec.name, i.key) : undefined}>
                  {editing ? <span className="hub-grip" title="Drag to move"><Icon name="grip" size={14} /></span>
                    : <button type="button" className={`hub-star${favs.includes(i.key) ? " on" : ""}`} aria-pressed={favs.includes(i.key)} aria-label={`${favs.includes(i.key) ? "Remove" : "Add"} ${i.label} ${favs.includes(i.key) ? "from" : "to"} favourites`} onClick={() => toggle(i.key)}>{favs.includes(i.key) ? "★" : "☆"}</button>}
                  <a href={i.href}>{i.label}</a><small>{kindOf(i)}</small>
                  {editing ? <span className="hub-item-tools">
                    <button type="button" aria-label={`Move ${i.label} up`} onClick={() => setLayout(nudgeItem(layout, view, i.key, -1))}>↑</button>
                    <button type="button" aria-label={`Move ${i.label} down`} onClick={() => setLayout(nudgeItem(layout, view, i.key, 1))}>↓</button>
                    {i.key.startsWith("custom|") && <button type="button" aria-label={`Edit ${i.label}`} onClick={() => { setForm({ key: i.key, label: i.label, href: i.href, section: sec.name }); setFormError(""); }}>✎</button>}
                    <button type="button" aria-label={`${i.key.startsWith("custom|") ? "Delete" : "Hide"} ${i.label}`} onClick={() => setLayout(removeItem(layout, i.key))}>✕</button>
                  </span> : i.kind === "doctype" && i.canCreate && <a className="hub-new" href={`${i.href}/new`} title={`New ${i.label}`} aria-label={`New ${i.label}`}>＋</a>}
                </li>
              ))}
              {editing && list.length === 0 && <li className="hub-drop-hint">Drop a shortcut here</li>}</ul>
            </section>
          );
        })}
      </div>
      {!editing && shownCount === 0 && <div className="hub-empty"><strong>{tab === "fav" ? "No favourites yet" : "Nothing found"}</strong><span>{tab === "fav" ? "Tap the star beside anything to keep it here." : "Try another word."}</span></div>}
    </div>
  );
}
