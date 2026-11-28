/* Velora ProjectOne executive portfolio workspace. Source data is read from
 * the authenticated, tenant-scoped native integration endpoint. */
(function () {
  'use strict';
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => Number(value || 0).toLocaleString(undefined, {maximumFractionDigits: 2});
  const panel = (title, body, extra='') => `<section class="po-exec-panel ${extra}"><h3>${esc(title)}</h3>${body}</section>`;
  function render(root, data) {
    const currencies = data.financial_by_currency || [];
    const sourceRows = Object.entries((data.source_health || {}).sources || {});
    const issues = (data.data_quality || {}).issues || [];
    const sourceTable = sourceRows.length ? `<div class="po-exec-table-wrap"><table><thead><tr><th>Source</th><th>Status</th><th>Records</th><th>Collections</th></tr></thead><tbody>${sourceRows.map(([name,s])=>`<tr><td>${esc(name)}</td><td><span class="po-exec-status ${s.status==='connected'?'is-connected':'is-missing'}">${esc(s.status)}</span></td><td>${number(s.records)}</td><td>${esc((s.collections||[]).join(', '))}</td></tr>`).join('')}</tbody></table></div>` : '<p class="po-exec-muted">No source permissions or adapters are available.</p>';
    const finance = currencies.length ? `<div class="po-exec-table-wrap"><table><thead><tr><th>Currency</th><th>Approved budget</th><th>Actual cost</th><th>Commitments</th><th>Budget exposure</th><th>Available budget</th><th>Recognised revenue</th><th>Contribution</th></tr></thead><tbody>${currencies.map(r=>`<tr><td><strong>${esc(r.currency)}</strong></td><td>${number(r.approved_budget)}</td><td>${number(r.actual_cost)}</td><td>${number(r.open_commitments)}</td><td>${number(r.budget_exposure)}</td><td>${number(r.available_budget)}</td><td>${number(r.recognised_revenue)}</td><td>${number(r.contribution_after_cost)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="po-exec-muted">Financial data is not connected or no financial rows were returned. No zero-value financial position is inferred.</p>';
    const quality = issues.length ? `<div class="po-exec-table-wrap"><table><thead><tr><th>Severity</th><th>Collection</th><th>Code</th><th>Finding</th></tr></thead><tbody>${issues.slice(0,30).map(i=>`<tr><td>${esc(i.severity)}</td><td>${esc(i.collection)}</td><td>${esc(i.code)}</td><td>${esc(i.message)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="po-exec-good">No structural data-quality issues were detected in the returned records.</p>';
    root.innerHTML = `<header class="po-exec-header"><div><div class="po-exec-eyebrow">VELORA PROJECTONE · EXECUTIVE CONTROL</div><h2>Portfolio Executive Workspace</h2><p>Authoritative, information from connected Velora applications.</p></div><button type="button" class="po-exec-refresh">Refresh data</button></header><div class="po-exec-cards"><article><span>Connected sources</span><strong>${number(data.source_health?.connected_count)} / ${number(data.source_health?.source_count)}</strong></article><article><span>Data-quality findings</span><strong>${number(data.data_quality?.issue_count)}</strong></article><article><span>High-severity findings</span><strong>${number(data.data_quality?.high_count)}</strong></article><article><span>Collections returned</span><strong>${number(Object.keys(data.record_counts||{}).length)}</strong></article></div>${panel('Financial position by currency',finance)}${panel('Upstream integration health',sourceTable)}${panel('Data quality and reconciliation exceptions',quality)}<p class="po-exec-footnote">${esc(data.metadata?.source_of_truth || 'Upstream applications remain authoritative.')} · ${esc(data.metadata?.currency_policy || 'No implicit currency conversion.')} · Read-only workspace.</p>`;
    root.querySelector('.po-exec-refresh').addEventListener('click', () => load(root));
  }
  async function load(root) {
    root.innerHTML = '<div class="po-exec-loading">Loading portfolio information…</div>';
    try {
      const response = await fetch('/api/projectone/portfolio/executive-workspace', {method:'GET', credentials:'same-origin', headers:{'Accept':'application/json'}});
      if (!response.ok) throw new Error(`Workspace request failed (${response.status}).`);
      const result = await response.json();
      render(root, result);
    } catch (error) {
      root.innerHTML = `<div class="po-exec-error"><strong>Executive workspace unavailable</strong><p>${esc(error.message || 'Unable to retrieve portfolio information.')}</p><p>Check the authenticated session, portfolio permission and native source adapters.</p><button type="button" class="po-exec-retry">Retry</button></div>`;
      root.querySelector('.po-exec-retry').addEventListener('click', () => load(root));
    }
  }
  function mount(root) { if (!root) throw new Error('Executive workspace root is required.'); root.classList.add('po-executive-workspace'); load(root); return {refresh:()=>load(root)}; }
  window.VeloraProjectOneExecutive = {mount};
  if (window.frappe && frappe.pages) {
    frappe.pages['projectone-executive-workspace'] = frappe.pages['projectone-executive-workspace'] || {};
    frappe.pages['projectone-executive-workspace'].on_page_load = function(wrapper) {
      const page = frappe.ui.make_app_page({parent:wrapper,title:'Portfolio Executive Workspace',single_column:true});
      const host = document.createElement('div'); page.main.appendChild(host); mount(host);
    };
  }
})();
