import type { ReactNode } from "react";

export const money = (v: number | null | undefined, digits = 0) => v == null ? "–" : v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const pct = (v: number | null | undefined) => v == null ? "–" : `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
export const today = () => new Date().toISOString().slice(0, 10);

export function Kpi({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: "bad" | "ok" | "warn"; hint?: string }) {
  return <div className="brc-kpi" title={hint}><span>{label}</span><strong className={tone === "bad" ? "brc-bad" : tone === "ok" ? "brc-ok" : tone === "warn" ? "cx-warn" : ""}>{value}</strong></div>;
}

/** Horizontal bars: one row per item, width = share of the largest value. */
export function Bars({ items, format = (n: number) => money(n), mark }: { items: { label: string; value: number; flag?: boolean; note?: string }[]; format?: (n: number) => string; mark?: string }) {
  const max = Math.max(1, ...items.map(i => Math.abs(i.value)));
  if (!items.length) return <p className="muted">Nothing to show yet.</p>;
  return (
    <div className="cx-bars" role="list">
      {items.map(i => (
        <div key={i.label} className="cx-bar" role="listitem">
          <span className="cx-bar-label" title={i.label}>{i.label}</span>
          <span className="cx-bar-track"><span className={`cx-bar-fill${i.flag ? " cx-over" : ""}`} style={{ width: `${Math.max(2, Math.abs(i.value) / max * 100)}%` }} /></span>
          <span className="cx-bar-value">{format(i.value)}{i.note ? <small> {i.note}</small> : null}{i.flag && mark ? <small className="cx-over-text"> {mark}</small> : null}</span>
        </div>
      ))}
    </div>
  );
}

export function Card({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  return <section className="admin-card"><h2>{title}</h2>{note && <p className="muted">{note}</p>}{children}</section>;
}

export function Tone({ state }: { state: string }) {
  const cls = state === "Breached" || state === "Failed" || state === "Dead" ? "pill-red" : state === "At risk" || state === "Partly Sent" || state === "Scheduled" ? "pill-orange" : state === "Met" || state === "Sent" || state === "On track" ? "pill-green" : "pill-grey";
  return state ? <span className={`pill ${cls}`}>{state}</span> : <span className="muted">–</span>;
}
