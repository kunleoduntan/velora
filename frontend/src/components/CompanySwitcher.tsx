import type { CompanyEntry } from "../api";
import Icon from "../ui/Icon";
import Popover from "../ui/Popover";

/** "ACTIVE COMPANY" selector: pick another company without signing in again. */
export default function CompanySwitcher({ companies, activeId, defaultId = null, onSwitch, onDefault }: { companies: CompanyEntry[]; activeId: string | null; defaultId?: string | null; onSwitch: (id: string) => void; onDefault?: (id: string | null) => void }) {
  const active = companies.find((c) => c.id === activeId);
  return (
    <Popover className="company-pop" trigger={(p) => (
      <button type="button" className="company-btn" {...p}>
        <span className="company-label">ACTIVE COMPANY</span>
        <span className="company-name">{active?.name ?? "Select a company"}<Icon name="down" size={14} /></span>
      </button>
    )}>
      {(close) => (
        <ul role="listbox" aria-label="Companies">
          {companies.map((c) => (
            <li key={c.id}>
              <button type="button" role="option" aria-selected={c.id === activeId} disabled={c.status !== "active"} className={c.id === activeId ? "on" : ""}
                onClick={() => { close(); if (c.id !== activeId) onSwitch(c.id); }}>
                <strong>{c.name}</strong>
                <small>{c.tenant} · {c.roles.join(", ")}{c.status !== "active" ? ` · ${c.status}` : ""}{c.id === defaultId ? " · default" : ""}</small>
              </button>
              {onDefault && c.status === "active" && (
                <button type="button" className="rbtn company-default" aria-label={c.id === defaultId ? `Clear default company ${c.name}` : `Make ${c.name} the default company`}
                  onClick={() => onDefault(c.id === defaultId ? null : c.id)}>{c.id === defaultId ? "Default ✓" : "Make default"}</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Popover>
  );
}
