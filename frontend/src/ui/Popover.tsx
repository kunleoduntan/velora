import { useEffect, useRef, useState, type ReactNode } from "react";

interface TriggerProps { onClick: () => void; "aria-expanded": boolean; "aria-haspopup": "true" }

/** Click-to-open panel that closes on outside click or Escape. Children receive `close`. */
export default function Popover({ trigger, children, align = "left", className = "" }: {
  trigger: (p: TriggerProps) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
  }, [open]);
  return (
    <div className="popover-wrap" ref={ref}>
      {trigger({ onClick: () => setOpen((o) => !o), "aria-expanded": open, "aria-haspopup": "true" })}
      {open && <div className={`popover popover-${align} ${className}`} role="dialog">{children(() => setOpen(false))}</div>}
    </div>
  );
}
