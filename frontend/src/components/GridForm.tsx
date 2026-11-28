import type { ReactNode } from "react";
import type { Field, GridLayout } from "../types";
import Icon from "../ui/Icon";

interface Props {
  layout: GridLayout;
  fields: Record<string, Field>;
  hidden: Record<string, boolean>;
  tabIdx: number;
  onTab: (i: number) => void;
  collapsed: Record<string, boolean>;
  onToggle: (key: string) => void;
  render: (field: Field) => ReactNode;
}

/** A form laid out on a 12-column grid: tabs > sections > rows > cells (each cell a field with a width). On a phone every cell becomes full width
 *  (narrow ones pair up two per row) so the same layout stays usable on a small screen. */
export default function GridForm({ layout, fields, hidden, tabIdx, onTab, collapsed, onToggle, render }: Props) {
  const shown = (name: string) => !!fields[name] && !fields[name].hidden && !hidden[name];
  const tabs = layout.tabs.filter((t) => t.sections.some((s) => s.rows.some((r) => r.some((c) => shown(c.field)))));
  return (
    <>
      {tabs.length > 1 && (
        <nav className="tabs" role="tablist">
          {tabs.map((t, i) => (
            <button key={t.label + i} role="tab" aria-selected={i === tabIdx} className={i === tabIdx ? "active" : ""} type="button" onClick={() => onTab(i)}>{t.label || `Tab ${i + 1}`}</button>
          ))}
        </nav>
      )}
      {tabs.map((tab, ti) => (
        <div key={tab.label + ti} className="tab-panel" hidden={ti !== tabIdx} role="tabpanel">
          {tab.sections.map((sec, si) => {
            const rows = sec.rows.map((r) => r.filter((c) => shown(c.field))).filter((r) => r.length);
            if (!rows.length) return null;
            const key = `${ti}:${si}`, closed = !!collapsed[key];
            return (
              <section key={si} className={`section${closed ? " collapsed" : ""}`} data-auto={sec.auto ? "true" : undefined}>
                {sec.label && (
                  <button type="button" className="section-head" aria-expanded={!closed} onClick={() => onToggle(key)}>
                    <span>{sec.label}</span><Icon name={closed ? "down" : "up"} />
                  </button>
                )}
                {!closed && (
                  <div className="grid-rows">
                    {rows.map((row, ri) => (
                      <div key={ri} className="grow">
                        {row.map((c) => (
                          <div key={c.field} className="gcell" data-field={c.field} data-span={c.span} data-narrow={c.span <= 4 ? "true" : undefined}
                            style={{ "--span": c.span } as React.CSSProperties}>
                            {render(fields[c.field])}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      ))}
    </>
  );
}
