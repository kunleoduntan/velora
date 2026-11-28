frappe.pages['sustainability-executive-dashboard'].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __('Sustainability Executive Dashboard'),
        single_column: true
    });
    const root = $('<div class="velora-esg-dashboard"></div>').appendTo(page.main);
    const filters = {};
    const dashboardMethod = 'velora_governance.api.get_sustainability_reporting_dashboard';

    const esc = (value) => frappe.utils.escape_html(String(value ?? ''));
    const pct = (value) => `${Number(value || 0).toFixed(1)}%`;

    function card(label, value, sub, accent) {
        return `<div class="esg-kpi-card ${accent || ''}">
            <div class="esg-kpi-label">${esc(label)}</div>
            <div class="esg-kpi-value">${esc(value)}</div>
            <div class="esg-kpi-sub">${esc(sub || '')}</div>
        </div>`;
    }

    function barRows(items, labelField, valueField, maxValue) {
        if (!items || !items.length) return '<div class="esg-empty">No data available for the selected filters.</div>';
        const max = Math.max(Number(maxValue || 0), ...items.map(x => Number(x[valueField] || 0)), 1);
        return items.map(item => {
            const value = Number(item[valueField] || 0);
            const width = Math.max(0, Math.min(100, value / max * 100));
            return `<div class="esg-bar-row"><div class="esg-bar-label" title="${esc(item[labelField])}">${esc(item[labelField])}</div>
                <div class="esg-bar-track"><div class="esg-bar-fill" style="width:${width}%"></div></div>
                <div class="esg-bar-value">${esc(value)}</div></div>`;
        }).join('');
    }

    function render(data) {
        const ready = Number(data.disclosures_ready || 0);
        const total = Number(data.disclosures_total || 0);
        const gaps = Number(data.disclosures_with_gaps || 0);
        const tasksTotal = Number(data.tasks_total || 0);
        const tasksCompleted = Number(data.tasks_completed || 0);
        const readiness = Number(data.readiness_percent || 0);
        const frameworks = data.framework_summary || [];
        const owners = data.owner_summary || [];
        const periods = data.period_summary || [];
        const missing = data.missing_disclosures || [];

        const gapRows = missing.length ? missing.map(row => `<tr>
            <td>${esc(row.disclosure)}</td><td>${esc(row.framework || 'Unmapped')}</td>
            <td><span class="esg-status">${esc(row.status || 'In Progress')}</span></td>
            <td>${esc(pct(row.readiness_percent))}</td><td>${esc(row.owner || 'Unassigned')}</td>
            <td>${esc(row.due_date || '—')}</td><td>${esc(row.gap_summary || 'No gap details supplied')}</td>
        </tr>`).join('') : '<tr><td colspan="7" class="esg-empty">No disclosure gaps found for these filters.</td></tr>';

        const periodRows = periods.length ? periods.map(row => `<tr>
            <td>${esc(row.period_name || row.name)}</td><td>${esc(row.period_status || '')}</td>
            <td>${esc(row.disclosures_ready)} / ${esc(row.disclosures_total)}</td><td>${esc(pct(row.readiness_percent))}</td>
            <td>${esc(row.tasks_completed)} / ${esc(row.tasks_total)}</td><td>${esc(row.tasks_overdue)}</td><td>${esc(row.owner || 'Unassigned')}</td>
        </tr>`).join('') : '<tr><td colspan="7" class="esg-empty">No reporting periods found.</td></tr>';

        root.html(`<div class="esg-dashboard-content">
            <div class="esg-filter-panel">
                <div class="esg-filter-heading">Reporting filters</div>
                <div class="esg-filter-grid"><div id="esg-entity-filter"></div><div id="esg-period-filter"></div><div id="esg-framework-filter"></div>
                    <div class="esg-filter-actions"><button class="btn btn-primary btn-sm" id="esg-refresh">${__('Refresh')}</button>
                    <button class="btn btn-default btn-sm" id="esg-clear">${__('Clear')}</button></div></div>
            </div>
            <div class="esg-kpi-grid">
                ${card('Overall Readiness', pct(readiness), `${ready} of ${total} applicable disclosures ready`, 'primary')}
                ${card('Applicable Disclosures', total, `${gaps} currently have gaps`)}
                ${card('Ready Disclosures', ready, `${total ? pct(ready / total * 100) : '0.0%'} ready`)}
                ${card('Disclosure Gaps', gaps, 'Requires attention', 'warning')}
                ${card('Data Collection Tasks', tasksTotal, `${tasksCompleted} completed`)}
                ${card('Overdue Tasks', Number(data.tasks_overdue || 0), 'Past due date', 'danger')}
                ${card('Reports', Number(data.reports_total || 0), 'Reporting period reports')}
                ${card('Reviews Pending', Number(data.reviews_pending || 0), `${Number(data.reviews_returned || 0)} returned`, 'warning')}
            </div>
            <div class="esg-chart-grid">
                <section class="esg-panel"><h4>${__('Framework Readiness')}</h4><div class="esg-framework-bars">${barRows(frameworks, 'framework', 'readiness_percent', 100)}</div></section>
                <section class="esg-panel"><h4>${__('Task Accountability by Owner')}</h4><div class="esg-owner-bars">${barRows(owners, 'owner', 'tasks_total')}</div></section>
            </div>
            <section class="esg-panel"><h4>${__('Reporting Period Progress')}</h4><div class="esg-table-wrap"><table class="table table-bordered table-hover esg-table"><thead><tr>
                <th>${__('Period')}</th><th>${__('Status')}</th><th>${__('Disclosures Ready')}</th><th>${__('Readiness')}</th><th>${__('Tasks Complete')}</th><th>${__('Overdue')}</th><th>${__('Owner')}</th></tr></thead><tbody>${periodRows}</tbody></table></div></section>
            <section class="esg-panel"><h4>${__('Disclosure Gap Analysis')}</h4><div class="esg-table-wrap"><table class="table table-bordered table-hover esg-table"><thead><tr>
                <th>${__('Disclosure')}</th><th>${__('Framework')}</th><th>${__('Status')}</th><th>${__('Readiness')}</th><th>${__('Owner')}</th><th>${__('Due Date')}</th><th>${__('Gap Summary')}</th></tr></thead><tbody>${gapRows}</tbody></table></div></section>
            <div class="esg-dashboard-footer">${__('Dashboard data reflects permission-filtered records.')} <span class="text-muted">${__('Last refreshed')} ${esc(frappe.datetime.now_datetime())}</span></div>
        </div>`);
        bindFilters(data);
    }

    function bindFilters(data) {
        const entity = frappe.ui.form.make_control({parent: root.find('#esg-entity-filter'), df: {fieldtype:'Link', fieldname:'governance_entity', label:__('Governance Entity'), options:'Governance Entity', placeholder:__('All entities')}, render_input:true});
        const period = frappe.ui.form.make_control({parent: root.find('#esg-period-filter'), df: {fieldtype:'Link', fieldname:'reporting_period', label:__('Reporting Period'), options:'Sustainability Reporting Period', placeholder:__('All periods')}, render_input:true});
        const framework = frappe.ui.form.make_control({parent: root.find('#esg-framework-filter'), df: {fieldtype:'Link', fieldname:'framework', label:__('Framework'), options:'Sustainability Framework', placeholder:__('All frameworks')}, render_input:true});
        entity.set_value(filters.governance_entity || ''); period.set_value(filters.reporting_period || ''); framework.set_value(filters.framework || '');
        $('#esg-refresh').on('click', () => {
            filters.governance_entity = entity.get_value() || null;
            filters.reporting_period = period.get_value() || null;
            filters.framework = framework.get_value() || null;
            load();
        });
        $('#esg-clear').on('click', () => { filters.governance_entity = null; filters.reporting_period = null; filters.framework = null; load(); });
    }

    function load() {
        root.html('<div class="esg-loading"><span class="spinner"></span> '+__('Loading sustainability dashboard…')+'</div>');
        frappe.call({method: dashboardMethod, args: filters, callback: (r) => {
            if (r.exc) { root.html(`<div class="alert alert-danger">${__('Dashboard could not be loaded. Please verify your access and try again.')}</div>`); return; }
            render(r.message || {});
        }, error: () => root.html(`<div class="alert alert-danger">${__('Dashboard request failed. Please retry.')}</div>`) });
    }

    page.set_primary_action(__('Refresh'), load, 'refresh');
    load();
};
