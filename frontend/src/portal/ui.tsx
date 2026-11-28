import type { ReactNode } from "react";

export function Message({ kind, children }: { kind: "error" | "ok"; children: ReactNode }) { return <div className={`pt-msg pt-${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</div>; }

export function Table<T>({ rows, cols, empty, onRow }: { rows: T[]; cols: { head: string; cell: (r: T) => ReactNode; num?: boolean }[]; empty: string; onRow?: (r: T) => void }) {
  if (!rows.length) return <p className="pt-muted">{empty}</p>;
  return <div className="pt-scroll"><table className="pt-table"><thead><tr>{cols.map(c => <th key={c.head} className={c.num ? "pt-num" : ""}>{c.head}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={i} onClick={onRow ? () => onRow(r) : undefined}>{cols.map(c => <td key={c.head} className={c.num ? "pt-num" : ""}>{c.cell(r)}</td>)}</tr>)}</tbody></table></div>;
}

export const Badge = ({ s }: { s: string }) => <span className={`pt-badge pt-b-${s.toLowerCase().replace(/\W+/g, "-")}`}>{s}</span>;

/** Grey placeholder blocks shown while a page loads, so the layout does not jump. */
export function Skeleton({ rows = 3 }: { rows?: number }) {
  return <div className="pt-skel" role="status" aria-label="Loading">{Array.from({ length: rows }, (_, i) => <span key={i} style={{ width: `${92 - i * 11}%` }} />)}</div>;
}

export function Avatar({ name, size = 56 }: { name: string; size?: number }) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]!.toUpperCase()).join("") || "?";
  return <span className="pt-avatar" style={{ width: size, height: size, fontSize: size * 0.38 }} aria-hidden="true">{initials}</span>;
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} className={`pt-switch${checked ? " on" : ""}`} onClick={() => onChange(!checked)}><i /></button>;
}

export function Retry({ error, onRetry }: { error: string; onRetry: () => void }) {
  return <Message kind="error">{error} <button className="pt-link" onClick={onRetry}>Try again</button></Message>;
}
