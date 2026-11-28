import { useEffect, useId, useRef, useState } from "react";
import { api, ApiError, errorMessage, type SearchHit } from "../api";
import Icon from "../ui/Icon";

const MIN = 2;
export const hitHref = (h: Pick<SearchHit, "doctype" | "name">) => `#/app/${encodeURIComponent(h.doctype)}/${encodeURIComponent(h.name)}`;

/** Global search: type 2+ characters; arrows + Enter (or click) open a document; Ctrl/Cmd+K focuses it from anywhere. Renders nothing if search is not installed (404). */
export default function SearchBox({ delayMs = 250 }: { delayMs?: number }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const seq = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {                                                                      // Ctrl/Cmd+K from anywhere
    const key = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); input.current?.focus(); setOpen(true); } };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {                                                                      // click outside closes
    const down = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", down);
    return () => document.removeEventListener("mousedown", down);
  }, []);

  useEffect(() => {
    const term = q.trim();
    const mine = ++seq.current;                                                          // only the LATEST request may update the screen
    if (term.length < MIN) { setHits([]); setBusy(false); setError(""); return; }
    setBusy(true);
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      try {
        const r = await api.search(term, 12, ctl.signal);
        if (mine !== seq.current) return;
        setHits(r); setActive(0); setError("");
      } catch (e) {
        if (mine !== seq.current || ctl.signal.aborted) return;
        setHits([]);
        setError(e instanceof ApiError && e.status === 404 ? "Search service is unavailable. Please contact your administrator." : errorMessage(e));
      } finally { if (mine === seq.current) setBusy(false); }
    }, delayMs);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [q, delayMs]);

  const go = (h: SearchHit) => { setOpen(false); setQ(""); setHits([]); window.location.hash = hitHref(h); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, Math.max(hits.length - 1, 0))); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter" && open && hits[active]) { e.preventDefault(); go(hits[active]); }
    else if (e.key === "Escape") { if (open) setOpen(false); else setQ(""); }
  };
  const term = q.trim();
  const showPanel = open && term.length >= MIN;
  const groups = hits.reduce<Record<string, { hit: SearchHit; i: number }[]>>((g, hit, i) => { (g[hit.doctype] ||= []).push({ hit, i }); return g; }, {});

  return (
    <div className="search" ref={wrap}>
      <Icon name="search" />
      <input ref={input} type="search" role="combobox" aria-label="Search" aria-expanded={showPanel} aria-controls={`${id}-list`} aria-autocomplete="list"
        aria-activedescendant={showPanel && hits[active] ? `${id}-${active}` : undefined} placeholder="Search (Ctrl+K)" value={q} autoComplete="off"
        onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={onKey} />
      {showPanel && (
        <div className="search-panel" id={`${id}-list`} role="listbox" aria-label="Search results">
          {error && <div className="error" role="alert">{error}</div>}
          {busy && <p className="muted search-empty"><span className="search-spinner" aria-hidden="true" /> Searching records…</p>}
          {!error && !busy && hits.length === 0 && <p className="muted search-empty">No matching records for “{term}”. Try a document name, number, customer, supplier or description.</p>}
          {Object.entries(groups).map(([doctype, rows]) => (
            <div key={doctype} role="group" aria-label={doctype}>
              <div className="search-group">{doctype}</div>
              {rows.map(({ hit, i }) => (
                <a key={hit.name} id={`${id}-${i}`} role="option" aria-selected={i === active} className={`search-hit${i === active ? " active" : ""}`} href={hitHref(hit)}
                  onClick={(e) => { e.preventDefault(); go(hit); }} onMouseEnter={() => setActive(i)}>
                  <span>{hit.title}</span>{hit.title !== hit.name && <span className="muted">{hit.name}</span>}
                </a>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
