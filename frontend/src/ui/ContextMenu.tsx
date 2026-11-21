import { useEffect, useRef } from "react";
import Icon, { type IconName } from "./Icon";

export interface ContextEntry { label: string; icon?: IconName; onClick: () => void; hidden?: boolean; danger?: boolean }

/** A menu at a screen position (right-click / column options). Closes on outside click, Escape or scroll. */
export default function ContextMenu({ x, y, items, onClose }: { x: number; y: number; items: ContextEntry[]; onClose: () => void }) {
  const ref = useRef<HTMLUListElement>(null);
  useEffect(() => {
    const down = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", onClose, true);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); window.removeEventListener("scroll", onClose, true); };
  }, [onClose]);
  const left = Math.min(x, Math.max(0, window.innerWidth - 230));
  return (
    <ul ref={ref} className="ctx-menu" role="menu" style={{ left, top: y }}>
      {items.filter((i) => !i.hidden).map((i) => (
        <li key={i.label}>
          <button type="button" role="menuitem" className={i.danger ? "danger" : ""} onClick={() => { onClose(); i.onClick(); }}>
            {i.icon ? <Icon name={i.icon} /> : <span className="icon-gap" />}{i.label}
          </button>
        </li>
      ))}
    </ul>
  );
}
