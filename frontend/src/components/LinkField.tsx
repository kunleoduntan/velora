import { useEffect, useId, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { navigate } from "../router";

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
}
interface LinkItem { name: string; title?: string }

/** Permission-aware, keyboard-accessible autocomplete for linked DocType records. */
export default function LinkField({ doctype, value, onChange, readOnly, invalid, id, placeholder, ariaLabel, filters }: Props) {
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

  useEffect(() => { setText(value); }, [value]);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
    controller.current?.abort();
  }, []);

  function search(q: string) {
    if (timer.current) clearTimeout(timer.current);
    controller.current?.abort();
    const current = ++sequence.current;
    const abort = new AbortController();
    controller.current = abort;
    setLoading(true);
    setError("");
    setActive(0);
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
        const rows = await api.searchLink(doctype, q, filters ?? [], 10, abort.signal);
        if (current !== sequence.current || abort.signal.aborted) return;
        setItems(rows.map((r) => ({ name: r.name, title: r.description || r.title || undefined })));
      } catch (err) {
        if (current === sequence.current && !abort.signal.aborted) { setItems([]); setError(errorMessage(err)); }
      } finally {
        if (current === sequence.current) setLoading(false);
      }
    }, 180);
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
    <div className="link-field">
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
        {doctype !== "DocType" && <button type="button" className="link-create" title={`Create new ${doctype}`} aria-label={`Create new ${doctype}`} onMouseDown={(e) => e.preventDefault()} onClick={() => navigate(doctype, "new")}><span aria-hidden="true">＋</span></button>}
      </div>
      {open && (items.length > 0 || loading || text.trim().length > 0) && (
        <ul id={listboxId} role="listbox" aria-label={`${doctype} results`}>
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
          {!loading && !items.length && !error && <li className="link-empty" role="presentation">No matching {doctype.toLowerCase()} found</li>}
        </ul>
      )}
    </div>
  );
}
