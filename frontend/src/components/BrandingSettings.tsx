import { useEffect, useState } from "react";
import { api, errorMessage, type ApplicationBranding, type BrandingState, type NavigationGroup } from "../api";

const EMPTY: ApplicationBranding = { app_name: "Velora", tagline: "", logo_url: "", favicon_url: "", navigation: [] };

export default function BrandingSettings() {
  const [state, setState] = useState<BrandingState | null>(null);
  const [value, setValue] = useState<ApplicationBranding>(EMPTY);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.applicationBranding().then(s => { setState(s); setValue(s.branding); }).catch(e => setError(errorMessage(e))); }, []);
  if (!state) return <div className="panel">{error || "Loading application branding…"}</div>;
  const patch = (p: Partial<ApplicationBranding>) => { setValue(v => ({ ...v, ...p })); setMessage(""); };
  const available = state.available_doctypes;
  const updateGroup = (index: number, group: NavigationGroup) => patch({ navigation: value.navigation.map((g,i) => i===index ? group : g) });
  const addGroup = () => patch({ navigation: [...value.navigation, { label: "New menu", items: [] }] });
  const removeGroup = (index: number) => patch({ navigation: value.navigation.filter((_,i) => i!==index) });
  const addItem = (index: number) => {
    const used = new Set(value.navigation.flatMap(g => g.items.map(i => i.doctype)));
    const next = available.find(d => !used.has(d.name));
    if (!next) return setError("All available DocTypes are already assigned to navigation.");
    const group = value.navigation[index];
    updateGroup(index, { ...group, items: [...group.items, { doctype: next.name, label: next.name, icon: "" }] });
  };
  const save = async () => {
    setBusy(true); setError(""); setMessage("");
    try { const result = await api.saveApplicationBranding(value); setValue(result.branding); setMessage("Application branding and navigation saved for this company."); window.dispatchEvent(new Event("velora:branding-changed")); }
    catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  return <div className="branding-page">
    <header className="page-head"><div className="titles"><h1>Application Branding & Navigation</h1><span className="muted">Configure the company application identity and sidebar menu.</span></div></header>
    <div className="ribbon"><button className="rbtn primary" disabled={!state.can_edit || busy} onClick={save}>Save branding</button><button className="rbtn" disabled={busy} onClick={() => {setValue(state.branding);setMessage("");}}>Reset changes</button></div>
    {!state.can_edit && <div className="intro">Only a System Manager can change application branding.</div>}
    {error && <div className="error" role="alert">{error}</div>}{message && <div className="success" role="status">{message}</div>}
    <section className="section"><div className="section-head static"><span>Application identity</span></div>
      <div className="admin-grid">
        <div className="admin-card"><label>Application name</label><input maxLength={60} value={value.app_name} disabled={!state.can_edit} onChange={e=>patch({app_name:e.target.value})}/>
          <label>Tagline</label><input maxLength={120} value={value.tagline} disabled={!state.can_edit} onChange={e=>patch({tagline:e.target.value})}/>
          <label>Logo path or HTTPS URL</label><input maxLength={500} placeholder="/assets/my_app/logo.svg" value={value.logo_url} disabled={!state.can_edit} onChange={e=>patch({logo_url:e.target.value})}/>
          <label>Favicon path or HTTPS URL</label><input maxLength={500} placeholder="/assets/my_app/favicon.ico" value={value.favicon_url} disabled={!state.can_edit} onChange={e=>patch({favicon_url:e.target.value})}/>
          <small>Use site-relative asset paths or HTTPS URLs. Upload management and image transformation are not part of this release.</small>
        </div>
        <div className="admin-card"><h2>Live identity preview</h2><div className="branding-preview">
          {value.logo_url ? <img src={value.logo_url} alt="Application logo" /> : <div className="branding-mark">V</div>}
          <div><strong>{value.app_name || "Your application"}</strong><small>{value.tagline || "Application tagline"}</small></div>
        </div><p className="muted">Preview uses the current browser theme. The saved identity appears in the application shell.</p></div>
      </div>
    </section>
    <section className="section"><div className="section-head static"><span>Sidebar navigation designer</span><button className="rbtn" disabled={!state.can_edit} onClick={addGroup}>＋ Add menu group</button></div>
      <p className="muted">Create menu groups and place readable DocTypes under them. When at least one custom group is saved, it replaces the automatic module grouping. Unassigned DocTypes remain accessible through search.</p>
      {value.navigation.map((group,index)=><div className="admin-card nav-design-group" key={index}>
        <div className="nav-design-head"><input aria-label={`Menu group ${index+1} name`} value={group.label} disabled={!state.can_edit} onChange={e=>updateGroup(index,{...group,label:e.target.value})}/>
          <button className="rbtn danger" disabled={!state.can_edit} onClick={()=>removeGroup(index)}>Remove group</button></div>
        {group.items.map((item,itemIndex)=><div className="nav-design-item" key={item.doctype}>
          <select aria-label="Navigation DocType" value={item.doctype} disabled={!state.can_edit} onChange={e=>{const next=available.find(d=>d.name===e.target.value);const items=[...group.items];items[itemIndex]={...item,doctype:e.target.value,label:next?.name??e.target.value};updateGroup(index,{...group,items});}}>
            {available.filter(d=>d.name===item.doctype || !value.navigation.some(g=>g.items.some(x=>x.doctype===d.name))).map(d=><option key={d.name} value={d.name}>{d.module} · {d.name}</option>)}
          </select>
          <input aria-label="Navigation label" placeholder="Menu label" maxLength={60} value={item.label} disabled={!state.can_edit} onChange={e=>{const items=[...group.items];items[itemIndex]={...item,label:e.target.value};updateGroup(index,{...group,items});}}/>
          <input aria-label="Lucide icon name" placeholder="icon-name" maxLength={40} value={item.icon} disabled={!state.can_edit} onChange={e=>{const items=[...group.items];items[itemIndex]={...item,icon:e.target.value};updateGroup(index,{...group,items});}}/>
          <button className="icon-btn" aria-label="Remove navigation item" disabled={!state.can_edit} onClick={()=>updateGroup(index,{...group,items:group.items.filter((_,i)=>i!==itemIndex)})}>×</button>
        </div>)}
        <button className="rbtn" disabled={!state.can_edit || available.length===0} onClick={()=>addItem(index)}>＋ Add DocType</button>
      </div>)}
      {!value.navigation.length && <div className="empty-state">No custom navigation configured. Velora will continue grouping DocTypes automatically by module.</div>}
    </section>
  </div>;
}
