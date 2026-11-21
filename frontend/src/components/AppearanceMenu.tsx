import { useEffect, useState } from "react";
import type { ThemeState } from "../api";
import { applyTheme, loadAppearance, saveAppearance, PALETTES, type Appearance, type Density, type Mode } from "../theme";
import Icon, { type IconName } from "../ui/Icon";
import Popover from "../ui/Popover";

const MODES: { value: Mode | null; label: string; detail: string; icon: IconName }[] = [
  { value: null, label: "Company default", detail: "Use your organisation's setting", icon: "cog" },
  { value: "light", label: "Light", detail: "Bright, high-clarity workspace", icon: "activity" },
  { value: "dark", label: "Dark", detail: "Low-glare workspace", icon: "layers" },
  { value: "system", label: "Match device", detail: "Follow your device appearance", icon: "columns" },
];
const DENS: { value: Density | null; label: string; detail: string }[] = [
  { value: null, label: "Company default", detail: "Organisation preference" },
  { value: "compact", label: "Compact", detail: "More information on screen" },
  { value: "comfortable", label: "Comfortable", detail: "Balanced spacing" },
  { value: "spacious", label: "Spacious", detail: "Larger controls and spacing" },
];

/** Personal appearance controls. Choices apply immediately and persist per user/company. */
export default function AppearanceMenu({ theme }: { theme: ThemeState }) {
  const [a, setA] = useState<Appearance>(loadAppearance());
  useEffect(() => { const next = loadAppearance(); setA(next); applyTheme(theme, next); }, [theme]);
  if (!theme.spec.allow_user_override) return null;
  const update = (patch: Appearance) => { const n = { ...a, ...patch }; setA(n); saveAppearance(n); applyTheme(theme, n); };
  return (
    <Popover align="right" className="appearance-popover" trigger={(p) => <button type="button" className="appearance-trigger" aria-label="Appearance settings" {...p}><span className="appearance-trigger-icon"><Icon name="sliders" /></span><span>Appearance</span><Icon name="down" /></button>}>
      {() => (
        <div className="appearance-panel">
          <div className="appearance-panel-head"><div><strong>Personalise your workspace</strong><small>Changes apply immediately and are saved for this account.</small></div><span className="appearance-panel-mark"><Icon name="layers" /></span></div>
          <section className="appearance-choice-section">
            <div className="appearance-choice-heading"><span>THEME</span><small>Choose a colour mode</small></div>
            <div className="appearance-mode-grid" role="radiogroup" aria-label="Mode">
              {MODES.map((item) => <button key={item.label} type="button" role="radio" aria-checked={(a.mode ?? null) === item.value} className={`appearance-mode-card${(a.mode ?? null) === item.value ? " selected" : ""}`} onClick={() => update({ mode: item.value })}>
                <span className="appearance-mode-icon"><Icon name={item.icon} /></span><span className="appearance-option-copy"><strong>{item.label}</strong><small>{item.detail}</small></span><span className="appearance-radio" />
              </button>)}
            </div>
          </section>
          <section className="appearance-choice-section">
            <div className="appearance-choice-heading"><span>COLOUR</span><small>Pick the accent colour of your workspace</small></div>
            <div className="appearance-palette" role="radiogroup" aria-label="Colour">
              {PALETTES.map((p) => <button key={p.label} type="button" role="radio" aria-checked={(a.palette ?? null) === p.value} title={p.label} className={`appearance-swatch${(a.palette ?? null) === p.value ? " selected" : ""}`} onClick={() => update({ palette: p.value })}><span style={{ background: p.swatch }} /><small>{p.label}</small></button>)}
            </div>
          </section>
          <section className="appearance-choice-section density-section">
            <div className="appearance-choice-heading"><span>DENSITY</span><small>Adjust the amount of space</small></div>
            <div className="appearance-density-list" role="radiogroup" aria-label="Density">
              {DENS.map((item) => <button key={item.label} type="button" role="radio" aria-checked={(a.density ?? null) === item.value} className={`appearance-density-option${(a.density ?? null) === item.value ? " selected" : ""}`} onClick={() => update({ density: item.value })}>
                <span className={`density-glyph density-${item.value || "default"}`}><i /><i /><i /></span><span className="appearance-option-copy"><strong>{item.label}</strong><small>{item.detail}</small></span><span className="appearance-radio" />
              </button>)}
            </div>
          </section>
        </div>
      )}
    </Popover>
  );
}
