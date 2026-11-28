import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, errorMessage, getCompany } from "../api";
import { CREATED_CHANNEL, openInNewTab } from "../router";

interface Props {
  doctype: string;
  value: string;
  onChange: (v: string) => void;
  readOnly?: boolean;
  invalid?: boolean;
  id?: string;
  placeholder?: string;
  ariaLabel?: string;
  filters?: [string, string, unknown][];
  /** Replaces the default lookup (e.g. the batches of the row's item). `scope` keeps its cached answers apart from other lookups of the same DocType. */
  fetcher?: (txt: string, signal: AbortSignal) => Promise<LinkItem[]>;
  scope?: string;
}
export interface LinkItem { name: string; title?: string }

/** Permission-aware, keyboard-accessible autocomplete for linked DocType records. */
/** Lookups already fetched (kept for 20 seconds): reopening a field, retyping or going back a character is instant. */
const LOOKUP_CACHE = new Map<string, { at: number; items: { name: string; title?: string }[] }>();
const LOOKUP_TTL = 20_000;
const cacheKey = (dt: string, text: string, filters: unknown, scope = "") => `${getCompany() ?? ""}|${dt}|${scope}|${JSON.stringify(filters ?? [])}|${text.toLowerCase()}`;

export default function LinkField({ doctype, value, onChange, readOnly, invalid, id, placeholder, ariaLabel, filters, fetcher, scope }: Props) {
  const listboxId = useId();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<LinkItem[]>([]);
  const [text, setText] = useState(value);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const skipBlurCommit = useRef(false);
  const awaitingNew = useRef(false);
  const anchorRef = useRef<HTMLDivElement | null>(null);
  const [box, setBox] = useState<{ left: number; top: number; width: number; up: boolean; max: number } | null>(null);

  useEffect(() => { setText(value); }, [value]);
  // A record created in the tab opened by the + button: forget stale lookups and, if this field is waiting for it, fill it in.
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(CREATED_CHANNEL);
    channel.onmessage = (e: MessageEvent) => {
      const m = e.data as { doctype?: string; name?: string };
      if (m?.doctype !== doctype || !m.name) return;
      LOOKUP_CACHE.clear();
      if (awaitingNew.current && !value) { awaitingNew.current = false; setText(m.name); onChange(m.name); }
    };
    return () => channel.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doctype, value]);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
    controller.current?.abort();
  }, []);

  // The list is drawn on the page itself (not inside the field), so a scrolling grid or a dialog can never clip it.
  const showing = open && (items.length > 0 || loading || text.trim().length > 0);
  useLayoutEffect(() => {
    if (!showing) { setBox(null); return; }
    const place = () => {
      const el = anchorRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect(), below = window.innerHeight - r.bottom - 8, above = r.top - 8;
      const up = below < 160 && above > below;
      setBox({ left: r.left, top: up ? r.top : r.bottom, width: Math.max(r.width, 240), up, max: Math.max(120, Math.min(260, up ? above : below)) });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => { window.removeEventListener("scroll", place, true); window.removeEventListener("resize", place); };
  }, [showing, items.length, loading]);

  function search(q: string) {
    if (timer.current) clearTimeout(timer.current);
    controller.current?.abort();
    const current = ++sequence.current;
    const normalized = q.trim();
    if (!fetcher && doctype !== "DocType" && normalized.length === 1) {
      setItems([]); setLoading(false); setError(""); setActive(0);
      return;
    }
    const abort = new AbortController();
    controller.current = abort;
    const key = cacheKey(doctype, normalized, filters, scope);
    const hit = LOOKUP_CACHE.get(key);
    setError("");
    setActive(0);
    if (hit && Date.now() - hit.at < LOOKUP_TTL) { setItems(hit.items); setLoading(false); return; }
    setLoading(true);
    timer.current = setTimeout(async () => {
      try {
        if (doctype === "DocType") {
          const all = await api.doctypes();
          if (current !== sequence.current || abort.signal.aborted) return;
          const needle = q.trim().toLowerCase();
          setItems(all.filter((d) => !needle || d.name.toLowerCase().includes(needle) || d.module.toLowerCase().includes(needle))
            .slice(0, 25).map((d) => ({ name: d.name, title: d.module })));
          return;
        }
        const mapped = fetcher ? await fetcher(normalized, abort.signal)
          : (await api.searchLink(doctype, normalized, filters ?? [], 10, abort.signal)).map((r) => ({ name: r.name, title: r.description || r.title || undefined }));
        if (current !== sequence.current || abort.signal.aborted) return;
        LOOKUP_CACHE.set(key, { at: Date.now(), items: mapped });
        setItems(mapped);
      } catch (err) {
        if (current === sequence.current && !abort.signal.aborted) { setItems([]); setError(errorMessage(err)); }
      } finally {
        if (current === sequence.current) setLoading(false);
      }
    }, 120);
  }

  function choose(item: LinkItem) {
    setText(item.name);
    onChange(item.name);
    setItems([]);
    setOpen(false);
    setLoading(false);
    skipBlurCommit.current = true;
    inputRef.current?.blur();
  }

  function commit() {
    const needle = text.trim().toLocaleLowerCase();
    if (!needle) { onChange(""); setText(""); return; }
    const exact = items.find((item) => item.name.toLocaleLowerCase() === needle);
    if (exact) { choose(exact); return; }
    // A Link must point to an actual record. Do not silently store arbitrary text on blur.
    setText(value);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" && open && items.length) {
      e.preventDefault(); setActive((n) => Math.min(items.length - 1, n + 1));
    } else if (e.key === "ArrowUp" && open && items.length) {
      e.preventDefault(); setActive((n) => Math.max(0, n - 1));
    } else if (e.key === "Enter" && open && items.length) {
      e.preventDefault(); choose(items[active] ?? items[0]);
    } else if (e.key === "Escape") {
      setOpen(false); setItems([]); setText(value); controller.current?.abort();
    }
  }

  if (readOnly) return <input id={id} type="text" readOnly value={value} />;
  return (
    <div className="link-field" ref={anchorRef}>
      <div className="link-field-control">
        <input
          ref={inputRef} id={id} type="text" autoComplete="off" role="combobox" aria-autocomplete="list"
          aria-expanded={open} aria-controls={listboxId} aria-activedescendant={open && items[active] ? `${listboxId}-${active}` : undefined}
          placeholder={placeholder} aria-label={ariaLabel} aria-invalid={invalid || undefined}
          className={invalid ? "invalid" : ""} value={text}
          onFocus={() => { setOpen(true); search(text); }}
          onBlur={() => { window.setTimeout(() => {
            setOpen(false);
            if (skipBlurCommit.current) { skipBlurCommit.current = false; return; }
            commit();
          }, 120); }}
          onKeyDown={onKeyDown}
          onChange={(e) => { setText(e.target.value); setOpen(true); search(e.target.value); }}
        />
        {doctype !== "DocType" && <button type="button" className="link-create" title={`Create new ${doctype} (opens in a new tab)`} aria-label={`Create new ${doctype}`} onMouseDown={(e) => e.preventDefault()} onClick={() => { awaitingNew.current = true; openInNewTab(doctype, "new"); }}><span aria-hidden="true">＋</span></button>}
      </div>
      {showing && box && createPortal(
        <ul id={listboxId} role="listbox" aria-label={`${doctype} results`} className="link-menu"
          style={{ position: "fixed", left: box.left, width: box.width, maxHeight: box.max, ...(box.up ? { bottom: window.innerHeight - box.top + 2 } : { top: box.top + 2 }) }}>
          {loading && !items.length && <li className="link-loading" role="presentation">Searching…</li>}
          {items.map((it, index) => (
            <li key={it.name} id={`${listboxId}-${index}`} role="option" aria-selected={index === active}
              className={index === active ? "active" : ""}
              onMouseEnter={() => setActive(index)}
              onMouseDown={(e) => { e.preventDefault(); choose(it); }}>
              <strong>{it.name}</strong>{it.title && <span> {it.title}</span>}
            </li>
          ))}
          {!loading && !items.length && error && <li className="link-empty" role="alert">{error}</li>}
          {!loading && !items.length && !error && text.trim().length === 1 && <li className="link-empty" role="presentation">Type at least 2 characters to search</li>}
          {!loading && !items.length && !error && text.trim().length !== 1 && <li className="link-empty" role="presentation">No matching {doctype.toLowerCase()} found</li>}
        </ul>, document.body)}
    </div>
  );
}
