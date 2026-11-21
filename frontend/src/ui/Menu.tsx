import type { ReactNode } from "react";
import Icon, { type IconName } from "./Icon";
import Popover from "./Popover";

export interface MenuEntry { label: string; icon?: IconName; onClick: () => void; disabled?: boolean; danger?: boolean; hidden?: boolean }

/** A ribbon button that opens a list of actions (e.g. "Actions ▾"). */
export default function Menu({ label, icon, items, align = "left", disabled }: {
  label: ReactNode; icon?: IconName; items: MenuEntry[]; align?: "left" | "right"; disabled?: boolean;
}) {
  const visible = items.filter((i) => !i.hidden);
  return (
    <Popover align={align} className="menu" trigger={(p) => (
      <button type="button" className="rbtn" disabled={disabled || visible.length === 0} {...p}>
        {icon && <Icon name={icon} />}<span>{label}</span><Icon name="down" size={12} />
      </button>
    )}>
      {(close) => (
        <ul role="menu">
          {visible.map((it) => (
            <li key={it.label}>
              <button type="button" role="menuitem" className={it.danger ? "danger" : ""} disabled={it.disabled}
                onClick={() => { close(); it.onClick(); }}>
                {it.icon && <Icon name={it.icon} />}{it.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Popover>
  );
}
