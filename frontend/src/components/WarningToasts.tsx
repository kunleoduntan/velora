import { useEffect, useState } from "react";
import type { Warning } from "../api";

/** Notes the server sends with a successful answer: the work went through, and here is something worth knowing. */
export default function WarningToasts() {
  const [items, setItems] = useState<(Warning & { id: number })[]>([]);
  useEffect(() => {
    let n = 0;
    const on = (e: Event) => {
      const list = ((e as CustomEvent).detail ?? []) as Warning[];
      const add = list.map((w) => ({ ...w, id: ++n + Date.now() }));
      setItems((cur) => [...cur, ...add].slice(-4));
      for (const a of add) setTimeout(() => setItems((cur) => cur.filter((x) => x.id !== a.id)), 12000);
    };
    window.addEventListener("velora:warnings", on);
    return () => window.removeEventListener("velora:warnings", on);
  }, []);
  if (!items.length) return null;
  return (
    <div className="warn-toasts" aria-live="polite">
      {items.map((w) => (
        <div key={w.id} className="warn-toast" role="status">
          <div><b>Note:</b> {w.message}</div>
          {w.hint && <div>{w.hint}</div>}
          {w.actions?.length ? <div className="advice-actions">{w.actions.map((a) => <a key={a.href} className="rbtn" href={a.href}>{a.label}</a>)}</div> : null}
          <button type="button" className="rbtn" aria-label="Dismiss" onClick={() => setItems((cur) => cur.filter((x) => x.id !== w.id))}>Dismiss</button>
        </div>))}
    </div>);
}
