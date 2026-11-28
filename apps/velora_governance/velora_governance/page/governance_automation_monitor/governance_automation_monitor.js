frappe.pages['governance-automation-monitor'].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({parent: wrapper, title: __('Governance Automation Monitor'), single_column: true});
    const root = $('<div class="governance-automation-monitor"></div>').appendTo(page.main);
    const method = 'velora_governance.api.get_governance_automation_execution_history_page';
    const retryMethod = 'velora_governance.api.retry_governance_automation_execution';
    const esc = value => frappe.utils.escape_html(String(value ?? ''));
    let status = '';
    let offset = 0;
    const pageSize = 50;
    let total = 0;

    function badge(value) {
        const cls = ({Queued: 'blue', Running: 'orange', Completed: 'green', Failed: 'red', 'Retry Pending': 'yellow', Cancelled: 'grey'})[value] || 'grey';
        return `<span class="gae-status gae-${cls}">${esc(value)}</span>`;
    }
    function render(payload) {
        const data = payload.rows || [];
        total = Number(payload.total || 0);
        const counts = {Queued: 0, Running: 0, Completed: 0, Failed: 0, 'Retry Pending': 0};
        data.forEach(row => { if (counts[row.execution_status] !== undefined) counts[row.execution_status]++; });
        root.html(`<div class="gae-toolbar">
            <div class="gae-kpis">
              <div class="gae-kpi"><span>${__('Queued')}</span><strong>${counts.Queued}</strong></div>
              <div class="gae-kpi"><span>${__('Running')}</span><strong>${counts.Running}</strong></div>
              <div class="gae-kpi"><span>${__('Completed')}</span><strong>${counts.Completed}</strong></div>
              <div class="gae-kpi gae-alert"><span>${__('Failed')}</span><strong>${counts.Failed}</strong></div>
              <div class="gae-kpi gae-warning"><span>${__('Retry Pending')}</span><strong>${counts['Retry Pending']}</strong></div>
            </div>
            <div class="gae-controls"><select class="form-control gae-filter"><option value="">${__('All statuses')}</option>
              ${Object.keys(counts).map(s => `<option value="${esc(s)}" ${status === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}
            </select><button class="btn btn-primary gae-refresh">${__('Refresh')}</button></div>
          </div>
          <div class="text-muted small" style="margin-bottom:8px">${__("Counts are based on the latest 200 permission-visible records loaded for this view.")}</div><div class="gae-table-wrap"><table class="table table-bordered table-hover"><thead><tr>
            <th>${__('ID')}</th><th>${__('Action')}</th><th>${__('Status')}</th><th>${__('Attempts')}</th><th>${__('Actor')}</th><th>${__('Next Retry')}</th><th>${__('Error')}</th><th>${__('Actions')}</th>
          </tr></thead><tbody>${data.length ? data.map(row => `<tr>
            <td><a class="gae-open" data-name="${esc(row.name)}">${esc(row.name)}</a></td><td>${esc(row.action_type)}</td><td>${badge(row.execution_status)}</td>
            <td>${esc(row.attempts)}</td><td>${esc(row.actor || '—')}</td><td>${esc(row.next_retry_at || '—')}</td><td class="gae-error">${esc(row.last_error || '—')}</td>
            <td>${['Failed', 'Retry Pending'].includes(row.execution_status) ? `<button class="btn btn-xs btn-default gae-retry" data-name="${esc(row.name)}">${__('Retry')}</button>` : '—'}</td>
          </tr>`).join('') : `<tr><td colspan="8" class="text-muted text-center">${__('No automation execution records found.')}</td></tr>`}</tbody></table></div><div class="gae-pagination"><span class="text-muted">${__('Showing')} ${data.length ? offset + 1 : 0}–${offset + data.length} ${__('of')} ${total}</span><div><button class="btn btn-default gae-prev" ${offset <= 0 ? 'disabled' : ''}>${__('Previous')}</button> <button class="btn btn-default gae-next" ${offset + data.length >= total ? 'disabled' : ''}>${__('Next')}</button></div></div>`);
        root.find('.gae-filter').on('change', function () { status = $(this).val(); offset = 0; load(); });
        root.find('.gae-refresh').on('click', () => { offset = 0; load(); });
        root.find('.gae-prev').on('click', () => { offset = Math.max(0, offset - pageSize); load(); });
        root.find('.gae-next').on('click', () => { if (offset + data.length < total) { offset += pageSize; load(); } });
        root.find('.gae-open').on('click', function () { frappe.set_route('Form', 'Governance Automation Execution', $(this).data('name')); });
        root.find('.gae-retry').on('click', function () {
            const name = $(this).data('name');
            frappe.confirm(__('Queue this automation execution for retry?'), () => frappe.call({
                method: retryMethod, args: {name}, freeze: true, freeze_message: __('Queueing retry...'),
                callback: () => load()
            }));
        });
    }
    function load() {
        root.html(`<div class="text-muted text-center">${__('Loading automation execution history...')}</div>`);
        frappe.call({method, args: {status: status || null, limit: pageSize, offset}, callback: r => render(r.message || {rows: [], total: 0}),
            error: () => root.html(`<div class="alert alert-danger">${__('Unable to load automation history. Check permissions and server logs.')}</div>`)});
    }
    page.set_primary_action(__('Refresh'), load);
    load();
};
