import { useEffect, useState } from "react";
import { api } from "../../api";
import type { ApiFilter, Filter } from "../../filters";
import type { Meta } from "../../types";
import Icon from "../../ui/Icon";

interface Group { field: string; label: string; items: { value: string | number | null; count: number }[] }
const STATUS = ["Draft", "Submitted", "Cancelled"];

export function groupFields(meta: Meta): { field: string; label: string }[] {
  const own = meta.fields.filter((f) => f.in_standard_filter && ["Select", "Link", "Check"].includes(f.fieldtype)).map((f) => ({ field: f.fieldname, label: f.label }));
  return [...own, ...(meta.is_submittable ? [{ field: "docstatus", label: "Status" }] : []), { field: "owner", label: "Created By" }].slice(0, 6);
}

/** Frappe-style "group by" sidebar: counts per value for the current filters; click a value to filter by it. */
export default function GroupBySidebar({ meta, apiFilters, active, onToggle, tick }: {
  meta: Meta; apiFilters: ApiFilter[]; active: Filter[]; onToggle: (field: string, value: string | number | null) => void; tick: number;
}) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const key = JSON.stringify(apiFilters);

  useEffect(() => {
    let cancelled = false;
    Promise.all(groupFields(meta).map(async (g) => ({ ...g, items: await api.groupBy(meta.name, g.field, apiFilters).catch(() => []) })))
      .then((r) => { if (!cancelled) setGroups(r.filter((g) => g.items.length)); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta, key, tick]);

  const show = (g: Group, v: string | number | null) => v === null ? "Not set" : g.field === "docstatus" ? STATUS[Number(v)] : g.items && meta.fields.find((f) => f.fieldname === g.field)?.fieldtype === "Check" ? (v ? "Yes" : "No") : String(v);
  const isOn = (g: Group, v: string | number | null) => active.some((f) => f.field === g.field && (v === null ? f.op === "is set" || f.op === "is not set" : f.op === "=" && String(f.value) === String(v)));

  return (
    <aside className="group-by" aria-label="Group by">
      <h3>Group by</h3>
      {groups.length === 0 && <p className="muted">Nothing to group.</p>}
      {groups.map((g) => (
        <div key={g.field} className="gb-group">
          <button type="button" className="gb-head" aria-expanded={!closed[g.field]} onClick={() => setClosed((c) => ({ ...c, [g.field]: !c[g.field] }))}>
            <span>{g.label}</span><Icon name={closed[g.field] ? "right" : "down"} size={14} />
          </button>
          {!closed[g.field] && (
            <ul>
              {g.items.map((it) => (
                <li key={String(it.value)}>
                  <button type="button" className={isOn(g, it.value) ? "on" : ""} aria-pressed={isOn(g, it.value)} onClick={() => onToggle(g.field, it.value)}>
                    <span>{show(g, it.value)}</span><span className="count">{it.count}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </aside>
  );
}
