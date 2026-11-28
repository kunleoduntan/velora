import { useMemo, useState } from "react";
import type { DocTypeInfo } from "../types";
import { CENTRES, getPins, getRecents, labelFor, search, togglePin } from "../shortcuts";
import type { Shortcut } from "../shortcuts";

/** One screen to find anything: type to search every record type and centre, pin what you use daily, and jump back to recent places. */
export default function ShortcutHub({ types }: { types: DocTypeInfo[] }) {
  const [term, setTerm] = useState(""), [pins, setPins] = useState(getPins());
  const catalogue = useMemo<Shortcut[]>(() => [
    ...CENTRES,
    ...types.map(t => ({ label: t.name, href: `#/app/${encodeURIComponent(t.name)}`, group: `Records · ${t.module || "Other"}` })),
  ], [types]);
  const found = useMemo(() => search(catalogue, term), [catalogue, term]);
  const recents = getRecents();
  const groups = useMemo(() => { const m = new Map<string, Shortcut[]>(); for (const s of found) (m.get(s.group) ?? m.set(s.group, []).get(s.group)!).push(s); return [...m.entries()]; }, [found]);
  const pin = (href: string) => setPins(togglePin(href));
  const Item = ({ s }: { s: Shortcut }) => (
    <li className="sh-item"><a href={s.href}>{s.label}</a>
      {s.group.startsWith("Records") && types.find(t => t.name === s.label)?.can_create && <a className="sh-new" href={`${s.href}/new`} title={`New ${s.label}`}>＋</a>}
      <button type="button" className="link sh-pin" aria-pressed={pins.includes(s.href)} aria-label={`${pins.includes(s.href) ? "Unpin" : "Pin"} ${s.label}`} onClick={() => pin(s.href)}>{pins.includes(s.href) ? "★" : "☆"}</button></li>
  );
  return (
    <div className="panel">
      <div className="page-head"><div><h1>Shortcuts</h1><p className="muted">Find any record type or centre. Pins and recent places are kept in this browser.</p></div></div>
      <input className="sh-search" type="search" autoFocus placeholder="Search, for example invoice, leave, ticket, bond…" aria-label="Search shortcuts" value={term} onChange={e => setTerm(e.target.value)} />
      {!term && pins.length > 0 && <section className="admin-card"><h2>Pinned</h2><ul className="sh-list">{pins.map(h => <li className="sh-item" key={h}><a href={h}>{labelFor(h, catalogue)}</a>
        <button type="button" className="link sh-pin" aria-label={`Unpin ${labelFor(h, catalogue)}`} aria-pressed onClick={() => pin(h)}>★</button></li>)}</ul></section>}
      {!term && recents.length > 0 && <section className="admin-card"><h2>Recent</h2><ul className="sh-list">{recents.map(h => <li className="sh-item" key={h}><a href={h}>{labelFor(h, catalogue)}</a></li>)}</ul></section>}
      {groups.length === 0 && <p className="muted">Nothing matches “{term}”.</p>}
      {groups.map(([group, items]) => <section className="admin-card" key={group}><h2>{group}</h2><ul className="sh-list">{items.map(s => <Item key={s.href} s={s} />)}</ul></section>)}
    </div>
  );
}
