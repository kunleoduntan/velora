/* ProjectOne Enterprise Dashboard Studio — permission-aware, read-only analytics UI. */
(function () {
  'use strict';
  const DEFINITIONS = [
    {id:'portfolio', title:'Portfolio Executive', group:'Executive', subtitle:'Portfolio health, strategic alignment and investment exposure', icon:'◈'},
    {id:'delivery', title:'Project Delivery', group:'Execution', subtitle:'Task execution, milestones, blockers and overdue commitments', icon:'▦'},
    {id:'schedule', title:'Schedule & Critical Path', group:'Execution', subtitle:'Critical activities, float, late work and baseline performance', icon:'◷'},
    {id:'resources', title:'Resource & Capacity', group:'Execution', subtitle:'Resource availability, utilisation, allocation and timesheets', icon:'♙'},
    {id:'financial', title:'Project Financial Control', group:'Commercial', subtitle:'Budgets, actuals, commitments and forecast exposure', icon:'◉'},
    {id:'commercial', title:'Commercial & Contracts', group:'Commercial', subtitle:'Contract values, variations, claims, retention and billing', icon:'▤'},
    {id:'risk', title:'Risk & Governance', group:'Assurance', subtitle:'Risk exposure, issues, actions and change control', icon:'△'},
    {id:'agile', title:'Agile Delivery', group:'Execution', subtitle:'Sprint health, backlog, throughput and blocked stories', icon:'⌁'},
    {id:'quality', title:'Quality & Deliverables', group:'Assurance', subtitle:'Inspection outcomes, defects and deliverable acceptance', icon:'✓'},
    {id:'programme', title:'Programme Performance', group:'Executive', subtitle:'Programme governance, project alignment and exceptions', icon:'▧'},
    {id:'benefits', title:'Benefits Realisation', group:'Assurance', subtitle:'Benefits baselines, targets, realised outcomes and gaps', icon:'✦'}
  ];
  const LABELS = {
    projects:'Projects', active:'Active projects', completed:'Completed projects', approved_budget:'Approved budget', actual_cost:'Actual cost',
    open_commitments:'Open commitments', forecast_exposure:'Forecast exposure', available_budget:'Available budget', overdue_projects:'Overdue projects',
    total_tasks:'Total tasks', completed_tasks:'Completed tasks', in_progress_tasks:'In progress', blocked_tasks:'Blocked tasks', overdue_tasks:'Overdue tasks',
    milestones:'Milestones', overdue_milestones:'Overdue milestones', projects_behind:'Projects behind schedule', activities:'Activities',
    critical_activities:'Critical activities', late_activities:'Late activities', zero_float_activities:'Zero-float activities',
    average_schedule_variance_days:'Average schedule variance', resources:'Resources', available_hours:'Available hours', allocated_hours:'Allocated hours',
    utilisation_percent:'Utilisation', overallocated_resources:'Overallocated resources', pending_timesheets:'Pending timesheets', approved_timesheets:'Approved timesheets',
    projects_over_budget:'Projects over budget', projects_with_unfunded_exposure:'Projects with unfunded exposure', contracts:'Contracts', contract_value:'Contract value',
    unapproved_variations:'Unapproved variations', open_claims:'Open claims', unbilled_milestones:'Unbilled milestones', retention_held:'Retention held', advance_balance:'Advance balance',
    risks:'Risks', critical_risks:'Critical risks', open_issues:'Open issues', overdue_actions:'Overdue actions', pending_changes:'Pending changes',
    active_sprints:'Active sprints', planned_sprints:'Planned sprints', backlog_stories:'Backlog stories', completed_stories:'Completed stories', blocked_stories:'Blocked stories',
    remaining_story_points:'Remaining story points', inspections:'Inspections', failed_inspections:'Failed inspections', open_defects:'Open defects', overdue_defects:'Overdue defects',
    deliverables_awaiting_acceptance:'Deliverables awaiting acceptance', programmes:'Programmes', active_programmes:'Active programmes', completed_programmes:'Completed programmes', projects_in_programmes:'Projects in programmes', unassigned_projects:'Unassigned projects', programme_exceptions:'Programme exceptions', benefits:'Benefits', realised_benefits:'Realised benefits', benefits_at_risk:'Benefits at risk', benefits_under_target:'Benefits below target'
  };
  const TABLE_LABELS = {
    largest_projects:'Largest projects', exceptions:'Priority exceptions', overdue_items:'Overdue work', critical_path:'Critical path activities',
    largest_variances:'Largest schedule variances', allocation_conflicts:'Allocation conflicts', utilisation_by_resource:'Resource utilisation',
    positions:'Project financial positions', largest_forecast_overruns:'Largest forecast overruns', commercial_exceptions:'Commercial exceptions',
    priority_register:'Priority risk register', open_issues:'Open issues', blocked_work:'Blocked stories', quality_exceptions:'Quality exceptions', largest_benefit_gaps:'Largest benefit gaps', at_risk_benefits:'Benefits at risk'
  };
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const human = key => LABELS[key] || TABLE_LABELS[key] || String(key).replace(/_/g,' ').replace(/\b\w/g, x => x.toUpperCase());
  const numeric = value => value !== null && value !== '' && Number.isFinite(Number(value));
  const number = (value, digits=1) => value == null || value === '' ? '—' : numeric(value) ? Number(value).toLocaleString(undefined,{maximumFractionDigits:digits}) : esc(value);
  const money = (value, currency) => value == null || value === '' ? 'Not available' : numeric(value) ? `${currency ? esc(currency)+' ' : ''}${Number(value).toLocaleString(undefined,{maximumFractionDigits:2})}` : esc(value);
  const badgeClass = value => /critical|red|overdue|blocked|failed|high|late|behind|disputed/i.test(String(value)) ? 'danger' : /amber|medium|pending|submitted|review|warning/i.test(String(value)) ? 'warning' : /green|completed|approved|accepted|closed|done/i.test(String(value)) ? 'success' : 'neutral';
  const dateText = value => value ? esc(String(value).slice(0,10)) : '—';

  function metricCard(key, value, currency, index) {
    const pct = key.endsWith('_percent');
    const isMoney = /budget|cost|commitment|exposure|revenue|variance|contract_value|retention|advance_balance/i.test(key);
    const shown = isMoney ? money(value, currency) : `${number(value)}${pct ? '%' : ''}`;
    return `<article class="po-metric po-metric-${index%5}"><div class="po-metric-top"><span>${esc(human(key))}</span><i>${['◈','↗','◷','▦','◎'][index%5]}</i></div><strong>${shown}</strong><small>${pct ? 'Current measure' : 'Current position'}</small></article>`;
  }
  function barPanel(title, obj) {
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return '';
    const entries = Object.entries(obj).filter(([,v]) => numeric(v));
    if (!entries.length) return '';
    const max = Math.max(1,...entries.map(([,v])=>Math.max(0,Number(v))));
    return `<section class="po-card po-chart-card"><div class="po-card-head"><div><span class="po-kicker">ANALYSIS</span><h3>${esc(human(title))}</h3></div><span class="po-card-menu">•••</span></div><div class="po-bars">${entries.slice(0,9).map(([label,value])=>`<div class="po-bar-line"><div class="po-bar-meta"><span>${esc(label)}</span><b>${number(value,2)}</b></div><div class="po-bar-rail"><i style="width:${Math.max(0,Math.min(100,Number(value)/max*100))}%"></i></div></div>`).join('')}</div></section>`;
  }
  function currencyPanel(groups) {
    if (!groups || typeof groups !== 'object' || Array.isArray(groups) || !Object.keys(groups).length) return '';
    const commercial=Object.values(groups).some(v=>Object.prototype.hasOwnProperty.call(v,'contract_value'));
    return `<section class="po-card po-chart-card"><div class="po-card-head"><div><span class="po-kicker">FINANCIAL BREAKDOWN</span><h3>${commercial?'Contract position by currency':'Project position by currency'}</h3></div></div><div class="po-currency-grid">${Object.entries(groups).map(([currency,v])=>commercial?`<div class="po-currency-tile"><b>${esc(currency)}</b><strong>${money(v.contract_value,currency)}</strong><small>Contract value · ${number(v.contracts,0)} contracts</small><div>Retention <b>${money(v.retention_held,currency)}</b></div><div>Advance balance <b>${money(v.advance_balance,currency)}</b></div></div>`:`<div class="po-currency-tile"><b>${esc(currency)}</b><strong>${money(v.budget,currency)}</strong><small>Approved budget · ${number(v.projects,0)} projects</small><div>Forecast cost <b>${money(v.forecast_cost,currency)}</b></div><div>Available budget <b>${money(v.available_budget,currency)}</b></div></div>`).join('')}</div></section>`;
  }
  function tablePanel(key, rows) {
    if (!Array.isArray(rows) || !rows.length) return '';
    const preferred = ['title','project_name','name','project','task_code','status','health','priority','rating','severity','due_date','planned_finish','planned_date','target_date','financial_impact','approved_budget','forecast_overrun','variance_days','assignee','owner','supplier','currency'];
    const all = [...new Set(rows.flatMap(row=>Object.keys(row||{}).filter(k=>!k.startsWith('_'))))];
    const keys = preferred.filter(k=>all.includes(k)).slice(0,6);
    for (const key of all) if (keys.length<6 && !keys.includes(key)) keys.push(key);
    if (!keys.length) return '';
    return `<section class="po-card po-table-card"><div class="po-card-head"><div><span class="po-kicker">DETAIL REGISTER</span><h3>${esc(human(key))}</h3></div><span class="po-row-count">${rows.length} records</span></div><div class="po-table-scroll"><table><thead><tr>${keys.map(k=>`<th>${esc(human(k))}</th>`).join('')}</tr></thead><tbody>${rows.slice(0,12).map(row=>`<tr class="${row._doctype&&row.name?'po-clickable-row':''}" data-doctype="${esc(row._doctype||'')}" data-name="${esc(row.name||'')}">${keys.map(k=>{const value=row[k]; const output= /status|health|rating|severity|priority|result/i.test(k) ? `<span class="po-status ${badgeClass(value)}">${esc(value||'Unspecified')}</span>` : /date|_on$/.test(k) ? dateText(value) : numeric(value) ? number(value,2) : esc(value??'—'); return `<td>${output}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>${rows.length>12?`<div class="po-table-foot">Showing 12 of ${rows.length} records</div>`:''}</section>`;
  }
  function financialSummary(payload) {
    const totals=payload.portfolio_totals;
    if (!totals) return '';
    const currency=totals.currency||'';
    const fields=['approved_budget','actual_cost','open_commitments','estimate_to_complete','estimate_at_completion','forecast_variance','recognised_revenue'];
    const available=fields.filter(k=>totals[k]!==undefined);
    if(!available.length)return '';
    return `<section class="po-card po-financial-summary"><div class="po-card-head"><div><span class="po-kicker">FINANCIAL POSITION</span><h3>Portfolio financial summary</h3></div><span class="po-currency-tag">${esc(currency)}</span></div><div class="po-financial-grid">${available.map(k=>`<div><small>${esc(human(k))}</small><b>${money(totals[k],currency)}</b></div>`).join('')}</div></section>`;
  }
  function renderDashboard(main, id, result, meta) {
    const def=DEFINITIONS.find(x=>x.id===id); if(!def)return;
    const payload=result||{}; const kpis=payload.kpis||{};
    const currency=(payload.portfolio_totals&&payload.portfolio_totals.currency)||'';
    const bars=Object.entries(payload).filter(([key,val])=>/distribution|status|rating|category|type|variance/.test(key)&&val&&typeof val==='object'&&!Array.isArray(val)).map(([k,v])=>barPanel(k,v)).join('');
    const tables=Object.entries(payload).filter(([key,val])=>Array.isArray(val)&&val.length).map(([k,v])=>tablePanel(k,v)).join('');
    const hasCurrencyGroups=payload.currency_groups&&Object.keys(payload.currency_groups).length>0;
    const hasData=Object.values(kpis).some(v=>numeric(v)&&Number(v)!==0)||bars||tables||hasCurrencyGroups;
    const provenance=meta&&meta.provenance?Object.entries(meta.provenance):[];
    main.innerHTML=`<header class="po-dash-hero"><div class="po-hero-copy"><div class="po-eyebrow">PROJECTONE <span> / </span>${esc(def.group.toUpperCase())}</div><h1>${esc(def.title)}</h1><p>${esc(def.subtitle)}</p></div><div class="po-hero-actions"><span class="po-live-indicator"><i></i> Live read model</span><button type="button" class="po-btn po-btn-light po-export">Export</button><button type="button" class="po-btn po-btn-primary po-refresh">↻ Refresh</button></div></header>
      <div class="po-dashboard-meta"><span>Company scoped</span><span>Permission filtered</span><span>Read only · No accounting postings</span>${meta&&meta.scope&&meta.scope.project?`<span>Project: ${esc(meta.scope.project)}</span>`:''}</div>
      ${hasData&&Object.keys(kpis).length?`<div class="po-metric-grid">${Object.entries(kpis).map(([k,v],i)=>metricCard(k,v,currency,i)).join('')}</div>`:''}
      ${financialSummary(payload)}
      ${hasCurrencyGroups?currencyPanel(payload.currency_groups):''}
      ${bars?`<div class="po-dashboard-grid">${bars}</div>`:''}
      ${tables?`<div class="po-register-grid">${tables}</div>`:''}
      ${!hasData?`<section class="po-empty-state"><div class="po-empty-icon">${esc(def.icon)}</div><h3>No dashboard records are available</h3><p>There are currently no records in the permitted data scope for this dashboard, or the relevant source adapters have not been connected. No sample figures have been substituted.</p><div class="po-empty-tags">${(meta&&meta.permission_denied_collections||[]).length?`<span>${meta.permission_denied_collections.length} restricted collections omitted</span>`:'<span>Awaiting authorised source data</span>'}</div></section>`:''}
      <footer class="po-dash-footer"><span>ProjectOne analytics · Read-only projection</span><span>${provenance.length?provenance.map(([k,v])=>`${esc(k)}: ${esc(v.status||'available')}`).join(' · '):'Source provenance not supplied'}</span></footer>`;
  }
  function csvFor(payload) {
    const lines=[];
    Object.entries(payload||{}).filter(([,v])=>Array.isArray(v)&&v.length).forEach(([name,rows])=>{
      lines.push(name.toUpperCase()); const cols=[...new Set(rows.flatMap(r=>Object.keys(r||{})))]; lines.push(cols.map(csvCell).join(','));
      rows.forEach(row=>lines.push(cols.map(k=>csvCell(row[k])).join(','))); lines.push('');
    });
    return lines.join('\r\n');
  }
  function csvCell(value){const s=value==null?'':typeof value==='object'?JSON.stringify(value):String(value);return '"'+s.replace(/"/g,'""')+'"';}
  function mount(root, options) {
    if(!root)throw new Error('Dashboard root element is required.');
    const opts=options||{}; let selected=opts.initialDashboard||'portfolio'; let filters=Object.assign({},opts.filters||{}); let currentPayload={}; let currentMeta={}; let busy=false;
    root.classList.add('po-dashboard-app');
    root.innerHTML=`<div class="po-dashboard-shell"><aside class="po-dashboard-sidebar"><div class="po-brand"><div class="po-brand-mark">P</div><div><b>ProjectOne</b><small>Management Intelligence</small></div></div><div class="po-side-label">WORKSPACES</div><nav class="po-dashboard-nav" aria-label="ProjectOne dashboards">${DEFINITIONS.map(d=>`<button type="button" data-dashboard="${d.id}" class="${d.id===selected?'active':''}"><span class="po-nav-icon">${d.icon}</span><span>${esc(d.title)}</span><i>›</i></button>`).join('')}</nav><div class="po-sidebar-foot"><span class="po-sidebar-dot"></span> Enterprise analytics</div></aside><section class="po-dashboard-content"><div class="po-dashboard-topbar"><div><span class="po-topbar-label">ANALYTICS WORKSPACE</span><strong>Dashboard Studio</strong></div><div class="po-topbar-right"><span class="po-topbar-user">${esc((window.frappe&&frappe.session&&frappe.session.user)||'Authenticated user')}</span></div></div><div class="po-dashboard-filterbar"><label>Project<input name="project_id" type="text" placeholder="All permitted projects" value="${esc(filters.project_id||'')}"></label><label>Status<select name="status"><option value="">All statuses</option>${['Draft','Open','In Progress','On Hold','Completed','Cancelled','Blocked','Approved','Pending'].map(x=>`<option ${filters.status===x?'selected':''}>${x}</option>`).join('')}</select></label><label>From<input name="start_date" type="date" value="${esc(filters.start_date||'')}"></label><label>To<input name="end_date" type="date" value="${esc(filters.end_date||'')}"></label><button type="button" class="po-btn po-btn-primary po-apply">Apply filters</button><button type="button" class="po-btn po-btn-ghost po-clear">Clear</button></div><main class="po-dashboard-main"><div class="po-dashboard-loading"><div class="po-spinner"></div><b>Preparing your dashboard</b><span>Retrieving authorised project information…</span></div></main></section></div>`;
    const main=root.querySelector('.po-dashboard-main');
    async function load(id){
      if(busy)return; busy=true; selected=id; root.querySelectorAll('[data-dashboard]').forEach(b=>b.classList.toggle('active',b.dataset.dashboard===id));
      main.innerHTML='<div class="po-dashboard-loading"><div class="po-spinner"></div><b>Loading '+esc(DEFINITIONS.find(d=>d.id===id).title)+'</b><span>Applying your access permissions and filters…</span></div>';
      try{
        let response;
        if(typeof opts.dataProvider==='function') response=await opts.dataProvider(id,Object.assign({},filters));
        else {
          const csrf=(window.frappe&&frappe.csrf_token)||window.csrf_token||'';
          const res=await fetch(opts.endpoint||'/api/projectone/dashboards/live',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json',...(csrf?{'X-Frappe-CSRF-Token':csrf}:{})},body:JSON.stringify({project_id:filters.project_id||null,filters,limit:500})});
          const raw=await res.json(); if(!res.ok)throw new Error((raw&&raw.detail)||`Dashboard request failed (${res.status}).`); response=raw;
        }
        const envelope=response&&response.dashboards?response:(response&&response.message?response.message:response||{});
        currentPayload=(envelope.dashboards&&envelope.dashboards[id])||envelope.payload||envelope;
        currentMeta=envelope;
        renderDashboard(main,id,currentPayload,currentMeta);
        const refresh=main.querySelector('.po-refresh'); if(refresh)refresh.addEventListener('click',()=>load(id));
        main.querySelectorAll('.po-clickable-row').forEach(row=>row.addEventListener('click',()=>{if(window.frappe&&typeof frappe.set_route==='function')frappe.set_route('Form',row.dataset.doctype,row.dataset.name);}));
        const exportButton=main.querySelector('.po-export'); if(exportButton)exportButton.addEventListener('click',()=>{const csv=csvFor(currentPayload);if(!csv){return;}const blob=new Blob([csv],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`projectone-${id}-dashboard.csv`;a.click();URL.revokeObjectURL(url);});
      }catch(error){main.innerHTML=`<section class="po-error-state"><div>!</div><h3>Dashboard could not be loaded</h3><p>${esc(error.message||'The dashboard service is unavailable.')}</p><button type="button" class="po-btn po-btn-primary po-retry">Try again</button></section>`;main.querySelector('.po-retry').addEventListener('click',()=>load(id));}
      finally{busy=false;}
    }
    root.querySelectorAll('[data-dashboard]').forEach(button=>button.addEventListener('click',()=>load(button.dataset.dashboard)));
    root.querySelector('.po-apply').addEventListener('click',()=>{filters={};root.querySelectorAll('.po-dashboard-filterbar input,.po-dashboard-filterbar select').forEach(input=>{if(input.value)filters[input.name]=input.value;});load(selected);});
    root.querySelector('.po-clear').addEventListener('click',()=>{filters={};root.querySelectorAll('.po-dashboard-filterbar input,.po-dashboard-filterbar select').forEach(input=>input.value='');load(selected);});
    load(selected);
    return {refresh:()=>load(selected),select:load,setFilters:next=>{filters=Object.assign({},next||{});return load(selected);},dashboards:DEFINITIONS.map(d=>d.id)};
  }
  window.VeloraProjectOneDashboards={mount,definitions:DEFINITIONS};
  if(window.frappe&&frappe.pages){
    frappe.pages['projectone-dashboards']=frappe.pages['projectone-dashboards']||{};
    frappe.pages['projectone-dashboards'].on_page_load=function(wrapper){
      const page=frappe.ui.make_app_page({parent:wrapper,title:'ProjectOne Dashboard Studio',single_column:true});
      const host=document.createElement('div');host.className='projectone-dashboard-host';page.main.appendChild(host);mount(host,{endpoint:'/api/projectone/dashboards/live'});
    };
  }
})();
