import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api, errorMessage, type ThemeSpec, type ThemeState } from "../api";
import { applyTheme } from "../theme";
import Icon from "../ui/Icon";
import Toggle from "../ui/Toggle";
import Button from "../ui/Button";

const HEX = /^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
const RADII = [["square", "Square"], ["soft", "Soft"], ["round", "Round"]] as const;
const DENSITIES = [["compact", "Compact"], ["comfortable", "Comfortable"], ["spacious", "Spacious"]] as const;
const FONTS = [["system", "System"], ["rounded", "Rounded"], ["classic", "Classic"]] as const;
const MODES = [["system", "Match device"], ["light", "Light"], ["dark", "Dark"]] as const;

function Seg<T extends string>({ label, value, options, onChange, disabled }: { label: string; value: T; options: readonly (readonly [T, string])[]; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <div className="field">
      <label id={`seg-${label}`}>{label}</label>
      <div className="seg" role="radiogroup" aria-labelledby={`seg-${label}`}>
        {options.map(([v, l]) => (
          <button key={v} type="button" role="radio" aria-checked={value === v} className={value === v ? "on" : ""} disabled={disabled} onClick={() => onChange(v)}>{l}</button>
        ))}
      </div>
    </div>
  );
}

/** Mini UI drawn with the compiled tokens, so BOTH modes are visible whatever mode you are in. */
function ModePreview({ title, tokens }: { title: string; tokens: Record<string, string> }) {
  return (
    <div className="mode-preview" data-testid={`preview-${title.toLowerCase()}`} style={tokens as CSSProperties}>
      <strong>{title}</strong>
      <div className="mp-row"><span className="mp-btn">Save</span><span className="mp-link">A link</span><span className="mp-pill">Active</span><span className="mp-pill mp-danger">Overdue</span></div>
      <div className="mp-table"><div className="mp-th">Customer</div><div>Acme Ltd</div><div className="mp-zebra">Bola Stores</div></div>
      <small>Muted helper text</small>
    </div>
  );
}

export default function ThemeSettings() {
  const [saved, setSaved] = useState<ThemeState | null>(null);
  const [spec, setSpec] = useState<ThemeSpec | null>(null);
  const [preview, setPreview] = useState<ThemeState | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    api.theme().then((t) => { setSaved(t); setSpec(t.spec); setPreview(t); }).catch((e) => setError(errorMessage(e)));
  }, []);

  const brandOk = !spec?.brand || HEX.test(spec.brand);
  const accentOk = !spec?.accent || HEX.test(spec.accent);
  const dirty = useMemo(() => !!saved && !!spec && JSON.stringify(spec) !== JSON.stringify(saved.spec), [saved, spec]);
  const canEdit = !!saved?.can_edit;

  // live preview: compile on the server (debounced) and apply instantly - nothing is stored until Save
  useEffect(() => {
    if (!spec || !saved?.can_edit || !brandOk || !accentOk || !dirty) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try { const p = await api.previewTheme(spec); setPreview(p); applyTheme(p); setError(""); }
      catch (e) { setError(errorMessage(e)); }
    }, 250);
    return () => clearTimeout(timer.current);
  }, [spec, brandOk, accentOk, dirty, saved?.can_edit]);

  if (!saved || !spec) return <div className="panel">{error ? <div className="error" role="alert">{error}</div> : "Loading…"}</div>;
  const set = (patch: Partial<ThemeSpec>) => { setSpec({ ...spec, ...patch }); setNote(""); };
  const view = preview ?? saved;
  const audit = view.audit ?? [];
  const failing = audit.filter((a) => !a.pass);

  async function save() {
    setBusy(true); setError("");
    try { const t = await api.saveTheme(spec!); setSaved(t); setPreview(t); setSpec(t.spec); applyTheme(t); setNote("Theme saved for everyone in this company."); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  const revert = () => { setSpec(saved.spec); setPreview(saved); applyTheme(saved); setNote(""); };
  const x = view.excel ?? {};

  return (
    <div className="theme-page">
      <header className="page-head"><div className="titles"><h1>Theme</h1><span className="muted">Appearance of the Desk and of every Excel export</span></div></header>
      <div className="ribbon" role="toolbar" aria-label="Theme actions">
        <button type="button" className="rbtn primary" disabled={!canEdit || !dirty || busy || !brandOk || !accentOk} onClick={save}><Icon name="save" /><span>Save theme</span></button>
        <button type="button" className="rbtn" disabled={!dirty} onClick={revert}><Icon name="refresh" /><span>Revert</span></button>
        {dirty && <span className="muted">Unsaved changes - previewing</span>}
      </div>
      {!canEdit && <div className="intro">Only a System Manager can change the theme. You can still choose light/dark and density for yourself from the Appearance menu.</div>}
      {error && <div className="error" role="alert">{error}</div>}
      {note && <div className="success" role="status">{note}</div>}

      <section className="section"><div className="section-head static"><span>Preset</span></div>
        <div className="preset-grid" role="radiogroup" aria-label="Theme preset">
          {(saved.presets ?? []).map((p) => (
            <button key={p.name} type="button" role="radio" aria-checked={spec.preset === p.name} disabled={!canEdit} className={`preset-card${spec.preset === p.name ? " on" : ""}`}
              onClick={() => set({ preset: p.name, brand: null })}>
              <span className="swatch" style={{ background: p.brand }} aria-hidden="true" />
              <strong>{p.label}</strong><small>{p.description}</small>
            </button>
          ))}
        </div>
      </section>

      <div className="theme-grid">
        <section className="section"><div className="section-head static"><span>Customise</span></div>
          <div className="columns" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <div className="column">
              <div className={`field${brandOk ? "" : " has-error"}`}><label htmlFor="brand">Brand colour</label>
                <div className="color-row"><input type="color" aria-label="Pick brand colour" value={HEX.test(spec.brand ?? "") && (spec.brand ?? "").length === 7 ? spec.brand! : view.brand} disabled={!canEdit} onChange={(e) => set({ brand: e.target.value })} />
                  <input id="brand" type="text" placeholder={view.brand} value={spec.brand ?? ""} disabled={!canEdit} onChange={(e) => set({ brand: e.target.value || null })} /></div>
                {!brandOk && <small className="req">Use a hex colour like #0f6cbd</small>}
                {spec.brand && <button type="button" className="link" onClick={() => set({ brand: null })}>Use the preset colour</button>}</div>
              <div className={`field${accentOk ? "" : " has-error"}`}><label htmlFor="accent">Accent colour</label>
                <input id="accent" type="text" placeholder="Automatic" value={spec.accent ?? ""} disabled={!canEdit} onChange={(e) => set({ accent: e.target.value || null })} />
                {!accentOk && <small className="req">Use a hex colour like #0f6cbd</small>}</div>
              <div className="field"><label htmlFor="bname">Company name in the header</label>
                <input id="bname" type="text" maxLength={60} value={spec.brand_name} disabled={!canEdit} onChange={(e) => set({ brand_name: e.target.value })} /></div>
            </div>
            <div className="column">
              <Seg label="Corners" value={spec.radius as "square"} options={RADII} disabled={!canEdit} onChange={(v) => set({ radius: v })} />
              <Seg label="Density" value={spec.density as "compact"} options={DENSITIES} disabled={!canEdit} onChange={(v) => set({ density: v })} />
              <Seg label="Font" value={spec.font as "system"} options={FONTS} disabled={!canEdit} onChange={(v) => set({ font: v })} />
              <Seg label="Default mode" value={(spec.default_mode ?? view.default_mode) as "system"} options={MODES} disabled={!canEdit} onChange={(v) => set({ default_mode: v })} />
              <div className="field"><label htmlFor="override">Let people choose their own mode and density</label>
                <Toggle id="override" checked={spec.allow_user_override} disabled={!canEdit} onChange={(v) => set({ allow_user_override: v })} /></div>
            </div>
          </div>
        </section>

        <section className="section"><div className="section-head static"><span>Preview</span></div>
          <div className="previews">
            {view.tokens && <><ModePreview title="Light" tokens={view.tokens.light} /><ModePreview title="Dark" tokens={view.tokens.dark} /></>}
          </div>
          <h4>Excel reports</h4>
          <div className="xl-preview" data-testid="excel-preview" aria-label="Excel colour preview">
            <div className="xl-head" style={{ background: `#${x.header_bg}`, color: `#${x.header_text}`, borderBottom: `2px solid #${x.rule}` }}><span>Customer</span><span>Amount</span></div>
            <div className="xl-sec" style={{ background: `#${x.section_bg}`, color: `#${x.header_text}` }}>Retail</div>
            <div className="xl-row"><span>Acme Ltd</span><span>1,250.50</span></div>
            <div className="xl-tot" style={{ background: `#${x.total_bg}`, borderTop: `2px solid #${x.rule}` }}><span>TOTAL</span><span>1,250.50</span></div>
          </div>
        </section>
      </div>

      <section className="section"><div className="section-head static"><span>Application button styles</span></div>
        <p className="muted">Consistent action hierarchy across forms, lists, dialogs and application modules. Choose the semantic type that matches the action.</p>
        <div className="button-showcase" data-testid="button-style-preview">
          <Button variant="primary">Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="success">Success</Button>
          <Button variant="warning">Warning</Button>
          <Button variant="danger">Destructive</Button>
          <Button variant="link">Link</Button>
        </div>
        <div className="button-showcase" style={{ marginTop: 8 }}>
          <Button size="small" variant="primary">Small</Button>
          <Button size="medium" variant="primary">Medium</Button>
          <Button size="large" variant="primary">Large</Button>
          <Button variant="primary" disabled>Disabled</Button>
        </div>
      </section>

      <section className="section"><div className="section-head static"><span>Accessibility</span></div>
        <p role="status" className={failing.length ? "error" : "success"} data-testid="audit-summary">
          {failing.length ? `${failing.length} of ${audit.length} contrast checks fail` : `All ${audit.length} contrast checks pass (WCAG AA) in light and dark mode`}
        </p>
        <details><summary>Show every check</summary>
          <table className="dgrid"><thead><tr><th>Mode</th><th>Pair</th><th className="num">Ratio</th><th className="num">Needs</th><th /></tr></thead>
            <tbody>{audit.map((a, i) => (<tr key={i}><td>{a.mode}</td><td>{a.pair}</td><td className="num">{a.ratio.toFixed(2)}:1</td><td className="num">{a.required}:1</td>
              <td><span className={`pill ${a.pass ? "pill-green" : "pill-red"}`}>{a.pass ? "pass" : "fail"}</span></td></tr>))}</tbody></table></details>
      </section>
    </div>
  );
}
