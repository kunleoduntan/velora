/* ProjectOne read-only financial workspace. Source ledgers remain authoritative. */
(function () {
  "use strict";
  if (!window.Velora || !window.Velora.registerFormComponent || !window.React) {
    console.warn("ProjectOne finance workspace unavailable: Velora custom-form bridge not loaded.");
    return;
  }
  const React=window.React, h=React.createElement;
  const money=(value,currency)=>{
    const n=Number(value||0);
    if(!Number.isFinite(n)) return "—";
    try{return new Intl.NumberFormat(undefined,{style:"currency",currency:currency||"USD",maximumFractionDigits:0}).format(n)}
    catch(_){return `${currency||""} ${n.toLocaleString()}`}
  };
  const metric=(label,value,sub,kind)=>h("article",{className:"p1-fin-metric",key:label,"data-kind":kind||"neutral"},
    h("span",null,label),h("strong",null,value),sub?h("small",null,sub):null);
  function ProjectFinancialWorkspace({doc}) {
    const s=doc.snapshot||doc.financial_position||doc;
    const currency=s.currency||doc.currency||"USD";
    const categories=Array.isArray(doc.category_lines)?doc.category_lines:[];
    const variance=Number(s.forecast_variance||0);
    return h("div",{className:"p1-finance"},
      h("header",{className:"p1-finance-hero"},h("div",null,h("span",{className:"p1-eyebrow"},"PROJECT FINANCIAL CONTROL"),
        h("h2",null,doc.project_title||doc.project||"Project Financial Workspace"),
        h("p",null,`Currency ${currency} · As at ${s.as_at||doc.as_at||"latest available snapshot"}`)),
        h("span",{className:"p1-finance-readonly"},"SOURCE-LEDGER READ ONLY")),
      h("div",{className:"p1-finance-grid"},[
        metric("Approved budget",money(s.revised_budget??s.approved_budget,currency),`Original ${money(s.original_budget??s.approved_budget,currency)}`),
        metric("Actual cost",money(s.actual_cost,currency),"Posted source transactions"),
        metric("Open commitments",money(s.open_commitments,currency),"Uninvoiced source commitments"),
        metric("Estimate at completion",money(s.estimate_at_completion,currency),"Actual + commitments + ETC"),
        metric("Forecast variance",money(variance,currency),variance<0?"Forecast over budget":"Within forecast budget",variance<0?"negative":"positive"),
        metric("Forecast margin",money(s.forecast_margin??s.forecast_project_margin,currency),`Recognised revenue ${money(s.recognised_revenue,currency)}`)
      ]),
      h("section",{className:"p1-fin-table-section"},h("div",{className:"p1-fin-table-head"},h("h3",null,"Cost category control"),h("span",null,`${categories.length} categories`)),
        categories.length?h("div",{className:"p1-fin-table-wrap"},h("table",{className:"p1-fin-table"},
          h("thead",null,h("tr",null,["Cost category","Budget","Actual","Commitments","Estimate to complete","Forecast variance"].map(x=>h("th",{key:x},x)))),
          h("tbody",null,categories.map((r,i)=>h("tr",{key:r.cost_category||i},
            h("td",null,r.cost_category||"Unclassified"),h("td",null,money(r.budget,currency)),h("td",null,money(r.actual,currency)),
            h("td",null,money(r.open_commitments,currency)),h("td",null,money(r.estimate_to_complete,currency)),
            h("td",{className:Number(r.variance_at_completion)<0?"p1-fin-negative":""},money(r.variance_at_completion,currency))))))):
          h("p",{className:"p1-resource-hint"},"No category-level cost control data is available in this snapshot.")),
      h("p",{className:"p1-finance-note"},"This workspace is a management read model. Actual costs and recognised revenue come from authoritative source applications. Budget changes require approval. ProjectOne does not create journals, post transactions or write to the General Ledger."));
  }
  window.Velora.registerFormComponent("Project Financial Snapshot",ProjectFinancialWorkspace,"velora_projectone");
})();

/* Revenue recognition is a proposal/review surface; posting remains in Finance. */
(function () {
  "use strict";
  if (!window.Velora || !window.Velora.registerFormComponent || !window.React) return;
  const h=window.React.createElement;
  const fmt=(v,c)=>{
    const n=Number(v||0); if(!Number.isFinite(n)) return "—";
    try{return new Intl.NumberFormat(undefined,{style:"currency",currency:c||"USD",maximumFractionDigits:0}).format(n)}
    catch(_){return `${c||""} ${n.toLocaleString()}`;}
  };
  function ProjectRevenueRecognition({doc}) {
    const currency=doc.currency||"USD";
    const progress= Math.max(0,Math.min(100,Number(doc.progress_percent||0)));
    return h("section",{className:"p1-revenue-recognition"},
      h("header",null,h("span",{className:"p1-eyebrow"},"REVENUE & PROFIT RECOGNITION"),
        h("h2",null,doc.performance_obligation||doc.project||"Project recognition proposal"),
        h("p",null,`${doc.recognition_method||"Recognition method pending"} · ${doc.period_end||"Period not set"}`)),
      h("div",{className:"p1-finance-grid"},[
        ["Measured progress",`${progress.toFixed(1)}%`],
        ["Cumulative revenue",fmt(doc.cumulative_revenue,currency)],
        ["Current period revenue",fmt(doc.current_period_revenue,currency)],
        ["Current period profit",fmt(doc.current_period_profit,currency)],
        ["Forecast total profit",fmt(doc.forecast_total_profit,currency)],
        ["Forecast margin",`${Number(doc.forecast_margin_percent||0).toFixed(1)}%`]
      ].map(([label,value])=>h("article",{className:"p1-fin-metric",key:label},h("span",null,label),h("strong",null,value)))),
      h("div",{className:"p1-recognition-progress"},h("div",{className:"p1-recognition-progress-fill",style:{width:`${progress}%`}})),
      doc.potential_onerous_contract_loss?h("p",{className:"p1-fin-negative"},"Potential forecast contract loss — finance review required."):null,
      h("p",{className:"p1-finance-note"},"This is a reviewable calculation proposal, not a posted accounting result. Verify the approved performance-obligation policy, source data and period before approval. VeloraERP Finance remains responsible for accounting recognition and all ledger postings."));
  }
  window.Velora.registerFormComponent("Project Revenue Recognition",ProjectRevenueRecognition,"velora_projectone");
})();
