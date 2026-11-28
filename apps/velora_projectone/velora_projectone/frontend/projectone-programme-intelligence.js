/* Programme Intelligence: risk simulation, calendar schedule and governed action hand-off. */
(function () {
  'use strict';
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = v => Number(v || 0).toLocaleString(undefined, {maximumFractionDigits:2});
  function mount(root) {
    root.classList.add('po-programme-intelligence');
    root.innerHTML = `<header class="po-exec-header"><div><div class="po-exec-eyebrow">VELORA PROJECTONE · PROGRAMME CONTROLS</div><h2>Programme Intelligence</h2><p>Calendar-aware delivery analysis, risk simulation and governed intervention hand-off.</p></div></header>
      <section class="po-exec-panel"><h3>Programme analysis</h3><div class="po-programme-controls"><label>Programme ID<input id="po-pi-programme" required placeholder="Programme reference"></label><label>Project start date<input id="po-pi-start" type="date"></label><label>Simulation iterations<select id="po-pi-iterations"><option>100</option><option selected>1000</option><option>5000</option><option>10000</option></select></label><button id="po-pi-run" type="button">Run analysis</button></div><div id="po-pi-status" class="po-exec-muted">Select a programme to load authorised host data.</div><div id="po-pi-results"></div></section>
      <section class="po-exec-panel"><h3>Submit corrective action for approval</h3><div class="po-programme-controls"><label>Exception ID<input id="po-pi-exception" required></label><label>Action title<input id="po-pi-title" required></label><label>Owner<input id="po-pi-owner" required></label><label>Due date<input id="po-pi-due" type="date"></label><button id="po-pi-submit" type="button">Submit for approval</button></div><div id="po-pi-action-status" class="po-exec-muted">Submission requires the configured Velora host workflow adapter.</div></section>`;
    const byId = id => root.querySelector('#'+id);
    byId('po-pi-run').addEventListener('click', async () => {
      const programme = byId('po-pi-programme').value.trim();
      if (!programme) { byId('po-pi-status').textContent = 'Programme ID is required.'; return; }
      byId('po-pi-status').textContent = 'Loading authorised programme data and calculating…';
      byId('po-pi-results').innerHTML = '';
      try {
        const post = async (url, body) => { const r = await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(body)}); const j=await r.json(); if(!r.ok) throw new Error(j.detail || j.message || `Request failed (${r.status})`); return j; };
        const start = byId('po-pi-start').value;
        const [schedule, risk, position] = await Promise.all([
          post('/api/projectone/programmes/calendar-schedule',{programme_id:programme,project_start:start || null}),
          post('/api/projectone/programmes/risk-simulation',{programme_id:programme,iterations:Number(byId('po-pi-iterations').value),seed:17}),
          post('/api/projectone/programmes/cost-resource-position',{programme_id:programme})
        ]);
        const milestones = (schedule.activities||[]).map(x=>`<tr><td>${esc(x.name||x.id)}</td><td>${esc(x.early_start_date)}</td><td>${esc(x.early_finish_date)}</td><td>${fmt(x.total_float)}</td><td>${x.critical?'Critical':'Non-critical'}</td></tr>`).join('');
        const costs = Object.entries(position.currency_totals||{}).map(([c,v])=>`<tr><td>${esc(c)}</td><td>${fmt(v.budget)}</td><td>${fmt(v.actual)}</td><td>${fmt(v.forecast)}</td></tr>`).join('');
        const resources = Object.entries(position.resource_totals||{}).map(([id,v])=>`<tr><td>${esc(id)}</td><td>${fmt(v.demand_hours)}</td><td>${fmt(v.capacity_hours)}</td><td>${fmt(v.overload_hours)}</td></tr>`).join('');
        byId('po-pi-results').innerHTML = `<div class="po-exec-cards"><article><span>Programme finish</span><strong>${esc(schedule.project_finish)}</strong></article><article><span>Critical activities</span><strong>${fmt((schedule.activities||[]).filter(x=>x.critical).length)}</strong></article><article><span>Schedule P80</span><strong>${fmt(risk.schedule_days?.p80)} days</strong></article><article><span>Cost P80</span><strong>${fmt(risk.cost?.p80)}</strong></article></div><h4>Calendar schedule and float</h4><div class="po-exec-table-wrap"><table><thead><tr><th>Activity</th><th>Early start</th><th>Early finish</th><th>Float</th><th>Path</th></tr></thead><tbody>${milestones||'<tr><td colspan="5">No activity rows returned.</td></tr>'}</tbody></table></div><h4>Cost position by currency</h4><div class="po-exec-table-wrap"><table><thead><tr><th>Currency</th><th>Budget</th><th>Actual</th><th>Forecast</th></tr></thead><tbody>${costs||'<tr><td colspan="4">No cost rows returned.</td></tr>'}</tbody></table></div><h4>Resource position</h4><div class="po-exec-table-wrap"><table><thead><tr><th>Resource</th><th>Demand hours</th><th>Capacity hours</th><th>Overload</th></tr></thead><tbody>${resources||'<tr><td colspan="4">No resource rows returned.</td></tr>'}</tbody></table></div><p class="po-exec-footnote">Monte Carlo: ${fmt(risk.iterations)} iterations · seed ${fmt(risk.seed)} · ${esc(risk.limitations||'')}.</p>`;
        byId('po-pi-status').textContent = 'Analysis complete. Results reflect the host provider snapshot and selected assumptions.';
      } catch(e) { byId('po-pi-status').textContent = e.message || 'Programme analysis unavailable.'; }
    });
    byId('po-pi-submit').addEventListener('click', async () => {
      const exception = byId('po-pi-exception').value.trim();
      const payload = {title:byId('po-pi-title').value.trim(),owner:byId('po-pi-owner').value.trim(),due_date:byId('po-pi-due').value};
      const status = byId('po-pi-action-status');
      if (!exception || !payload.title || !payload.owner) { status.textContent='Exception, title and owner are required.'; return; }
      status.textContent='Submitting through the host approval adapter…';
      try { const r=await fetch(`/api/projectone/management/interventions/${encodeURIComponent(exception)}/submit`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(payload)}); const j=await r.json(); if(!r.ok) throw new Error(j.detail||j.message||`Request failed (${r.status})`); status.textContent='Host workflow accepted the submission.'; }
      catch(e) { status.textContent=e.message||'Submission unavailable; no local action was created.'; }
    });
    return {refresh:()=>byId('po-pi-run').click()};
  }
  window.VeloraProjectOneProgrammeIntelligence = {mount};
  if (window.frappe && frappe.pages) {
    frappe.pages['projectone-programme-intelligence'] = frappe.pages['projectone-programme-intelligence'] || {};
    frappe.pages['projectone-programme-intelligence'].on_page_load = function(wrapper) {
      const page=frappe.ui.make_app_page({parent:wrapper,title:'Programme Intelligence',single_column:true});
      const host=document.createElement('div'); page.main.appendChild(host); mount(host);
    };
  }
})();
