import { useEffect, useState } from "react";
import { api, errorMessage, type FinancialLayoutInfo } from "../api";
import { goTo } from "../router";

export default function FinancialReportingCentre() {
  const [layouts,setLayouts]=useState<FinancialLayoutInfo[]>([]);
  const [busy,setBusy]=useState(true);
  const [error,setError]=useState("");
  const [query,setQuery]=useState("");
  useEffect(()=>{let active=true; api.financialLayouts().then(rows=>{if(active)setLayouts(rows);}).catch(e=>{if(active)setError(errorMessage(e));}).finally(()=>{if(active)setBusy(false);}); return ()=>{active=false;};},[]);
  const visible=layouts.filter(x=>x.name.toLowerCase().includes(query.toLowerCase()));
  return <main style={{padding:28,maxWidth:1400,margin:"0 auto"}}>
    <header className="frd-header"><div><div className="eyebrow">ACCOUNTING / FINANCIAL REPORTING</div><h1>Financial reporting centre</h1><p>Access governed financial statements, reporting layouts and General Ledger drill-down for the active company.</p></div></header>
    <section className="frd-panel" style={{padding:18,marginBottom:18}}><div style={{display:"flex",gap:12,flexWrap:"wrap",alignItems:"center",justifyContent:"space-between"}}><div><h2 style={{marginTop:0}}>Reporting workspace</h2><p className="muted">Saved layouts are loaded using your authenticated company session and existing report permissions.</p></div><button className="rbtn primary" onClick={()=>goTo("#/financial-reports")}>Design financial report</button></div><label className="frd-field"><span>Search reporting layouts</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search by report name" /></label></section>
    {busy&&<p role="status">Loading reporting layouts…</p>}
    {error&&<div className="error" role="alert">{error}</div>}
    {!busy&&!error&&<section className="frd-panel" style={{padding:18}}><h2>Reporting layouts</h2><h3>Financial statements</h3>{visible.length===0?<p className="muted">No saved financial reporting layouts match this search. Create a layout to get started.</p>:<div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(260px,1fr))",gap:12}}>{visible.map(item=><article key={item.id} className="frd-panel" style={{padding:16}}><h3>{item.name}</h3><p className="muted">{item.shared?"Shared reporting layout":"Company reporting layout"}</p><div style={{display:"flex",gap:8,flexWrap:"wrap"}}><button className="rbtn primary" onClick={()=>goTo(`#/financial-report-run?id=${encodeURIComponent(item.id)}`)}>Run report</button><button className="rbtn" onClick={()=>goTo(`#/financial-reports?id=${encodeURIComponent(item.id)}`)}>Open layout</button></div></article>)}</div>}</section>}
    <section className="frd-panel" style={{padding:18,marginTop:18}}><h2>Reporting controls</h2><ul><li>Reports use the active company context.</li><li>Report access is checked by the existing server-side financial reporting API.</li><li>Drill-down remains linked to source General Ledger transactions.</li><li>Review, approval and publication controls remain separate from report execution.</li></ul></section>
  </main>;
}
