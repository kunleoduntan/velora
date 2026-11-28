frappe.pages['governance-exception-centre'].on_page_load = function(wrapper) {
  const page = frappe.ui.make_app_page({parent: wrapper, title: 'Governance Exception Centre', single_column: true});
  page.add_field({fieldname:'status', label:'Status', fieldtype:'Select', options:'\nOpen\nAssigned\nIn Progress\nEscalated\nPending Evidence\nResolved\nClosed', change:()=>load()});
  page.add_field({fieldname:'severity', label:'Severity', fieldtype:'Select', options:'\nLow\nMedium\nHigh\nCritical', change:()=>load()});
  page.add_field({fieldname:'assigned_to', label:'Owner', fieldtype:'Link', options:'User', change:()=>load()});
  const body = $('<div class="governance-exception-centre"></div>').appendTo(page.main);
  const listArea = $('<div class="governance-exception-list-area"></div>').appendTo(body);
  page.add_inner_button('Export Management Report', () => exportReport(), 'Download');
  page.add_inner_button('Print Report', () => printReport(), 'Download');
  let offset=0, limit=50, selected=new Set();
  const dashboard=$('<div class="governance-exception-dashboard"></div>').appendTo(body);
  function renderBars(container,title,counts){
    const values=Object.entries(counts||{}).sort((a,b)=>b[1]-a[1]); const max=Math.max(1,...values.map(v=>Number(v[1]||0)));
    const box=$('<div class="exception-analytics-card"></div>').appendTo(container); $('<h4></h4>').text(title).appendTo(box);
    values.forEach(([label,value])=>{const row=$('<div class="exception-bar-row"></div>').appendTo(box); $('<span class="exception-bar-label"></span>').text(label).appendTo(row); const track=$('<div class="exception-bar-track"></div>').appendTo(row); $('<div class="exception-bar-fill"></div>').css('width',Math.max(2,Number(value||0)/max*100)+'%').appendTo(track); $('<span class="exception-bar-value"></span>').text(value).appendTo(row);});
  }
  function loadDashboard(){
    dashboard.empty().append('<div class="text-muted">Loading analytics…</div>');
    const filters={status:page.fields_dict.status.get_value()||null,severity:page.fields_dict.severity.get_value()||null,assigned_to:page.fields_dict.assigned_to.get_value()||null};
    frappe.call({method:'governance.api.get_governance_exception_analytics',args:{filters},callback:r=>{
      const a=r.message||{}; dashboard.empty(); const cards=$('<div class="exception-kpi-grid"></div>').appendTo(dashboard);
      [['Total',a.total],['Active',a.active],['Overdue',a.overdue_active],['Critical Active',a.critical_active],['Unassigned',a.unassigned_active],['Escalated',a.escalated]].forEach(([label,value])=>{const card=$('<div class="exception-kpi-card"></div>').appendTo(cards); $('<div class="exception-kpi-label"></div>').text(label).appendTo(card); $('<div class="exception-kpi-value"></div>').text(value||0).appendTo(card);});
      const charts=$('<div class="exception-analytics-grid"></div>').appendTo(dashboard); renderBars(charts,'By Severity',a.severity_counts); renderBars(charts,'By Status',a.status_counts); renderBars(charts,'Owner Workload',a.owner_counts); renderBars(charts,'Aging (Active)',a.aging_buckets);
      const sla=$('<div class="alert alert-warning"></div>').appendTo(dashboard); sla.text(`SLA integration: ${((a.sla||{}).integration_state)||'not connected'} — SLA metrics are only displayed when supplied by the existing SLA engine.`);
    },error:()=>dashboard.empty().append('<div class="text-muted">Analytics unavailable. Exception list remains available.</div>')});
  }
  function showTimeline(row){
    frappe.call({method:'governance.api.get_governance_exception_timeline',args:{name:row.name,limit:150},callback:r=>{
      const entries=r.message||[]; const dlg=new frappe.ui.Dialog({title:`Activity Timeline — ${row.name}`,fields:[{fieldname:'html',fieldtype:'HTML'}],primary_action_label:'Add Comment',primary_action(){
        const commentDlg=new frappe.ui.Dialog({title:'Add Exception Comment',fields:[{fieldname:'details',fieldtype:'Small Text',label:'Comment',reqd:1},{fieldname:'evidence_reference',fieldtype:'Data',label:'Evidence Reference'}],primary_action_label:'Save',primary_action(v){commentDlg.hide();frappe.call({method:'governance.api.add_governance_exception_activity',args:{name:row.name,details:v.details,evidence_reference:v.evidence_reference,activity_type:v.evidence_reference?'Evidence Added':'Comment'},callback:()=>showTimeline(row)});}});commentDlg.show();
      }});
      let html='<div style="max-height:55vh;overflow:auto">'; entries.forEach(e=>{html+=`<div class="border-bottom" style="padding:8px 0"><b>${frappe.utils.escape_html(e.activity_type||'')}</b><div>${frappe.utils.escape_html(e.details||'')}</div><small>${frappe.utils.escape_html(e.actor||'System')} · ${e.activity_datetime||''}</small>${e.evidence_reference?`<div>Evidence: ${frappe.utils.escape_html(e.evidence_reference)}</div>`:''}</div>`;}); html+='</div>'; dlg.fields_dict.html.$wrapper.html(html); dlg.show();
    }});
  }
  function load(){
    listArea.empty().append('<div class="text-muted">Loading exceptions…</div>'); loadDashboard();
    frappe.call({method:'governance.api.get_governance_exception_centre', args:{status:page.fields_dict.status.get_value()||null,severity:page.fields_dict.severity.get_value()||null,assigned_to:page.fields_dict.assigned_to.get_value()||null,limit,offset}, callback:r=>{
      const d=r.message||{}; listArea.empty(); const k=d.kpis||{};
      const cards=$('<div class="row"></div>').appendTo(listArea);
      [['Total',k.total||0],['Active',k.active||0],['Overdue',k.overdue_active||0],['Critical',k.critical_active||0]].forEach(x=>cards.append(`<div class="col-sm-3"><div class="card" style="padding:14px;margin-bottom:12px"><div class="text-muted">${x[0]}</div><h2>${x[1]}</h2></div></div>`));
      frappe.call({method:'governance.api.get_governance_exception_workload',callback:w=>{
        const m=w.message||{}; const box=$('<div class="alert alert-info"></div>').appendTo(listArea);
        box.text(`Workload: ${m.active||0} active · ${m.escalated||0} escalated · ${m.unassigned||0} unassigned`);
      }});
      const table=$('<table class="table table-bordered"><thead><tr><th><input type="checkbox" class="select-page"></th><th>Title</th><th>Source</th><th>Severity</th><th>Status</th><th>Due</th><th>Overdue</th><th>Owner</th><th>Action</th></tr></thead><tbody></tbody></table>').appendTo(listArea);
      const pageNames=[];
      (d.rows||[]).forEach(row=>{
        pageNames.push(row.name); const tr=$('<tr></tr>').appendTo(table.find('tbody'));
        const select=$('<td><input type="checkbox"></td>').appendTo(tr);
        select.find('input').prop('checked',selected.has(row.name)).on('change',e=>{if(e.target.checked)selected.add(row.name);else selected.delete(row.name);updateBulk();});
        tr.append(`<td>${frappe.utils.escape_html(row.title||'')}</td><td>${frappe.utils.escape_html(row.source_doctype||'')} / ${frappe.utils.escape_html(row.source_name||'')}</td><td>${frappe.utils.escape_html(row.severity||'')}</td><td>${frappe.utils.escape_html(row.status||'')}</td><td>${row.due_date||''}</td><td>${row.overdue_days||0}</td><td>${frappe.utils.escape_html(row.assigned_to||'')}</td>`);
        const action=$('<td></td>').appendTo(tr);
        $('<button class="btn btn-xs btn-default">Open</button>').appendTo(action).on('click',()=>frappe.set_route('Form','Governance Exception',row.name));
        $('<button class="btn btn-xs btn-info" style="margin-left:4px">Timeline</button>').appendTo(action).on('click',()=>showTimeline(row));
      });
      table.find('.select-page').on('change',e=>{pageNames.forEach(n=>e.target.checked?selected.add(n):selected.delete(n));table.find('tbody input[type=checkbox]').prop('checked',e.target.checked);updateBulk();});
      const bulk=$('<div class="mb-3"></div>').prependTo(listArea);
      const assignButton=$('<button class="btn btn-primary btn-sm">Assign Selected</button>').appendTo(bulk).prop('disabled',selected.size===0);
      assignButton.on('click',()=>{
        const dlg=new frappe.ui.Dialog({title:'Bulk Assign Exceptions',fields:[{fieldname:'user',label:'Assign To',fieldtype:'Link',options:'User',reqd:1}],primary_action_label:'Assign',primary_action(values){
          dlg.hide(); frappe.call({method:'governance.api.bulk_assign_governance_exceptions',args:{exception_names:Array.from(selected),user:values.user},callback:r=>{
            const result=r.message||{}; frappe.msgprint(`${result.count||0} exceptions assigned. ${(result.failed||[]).length} failed.`); selected.clear(); load();
          }});
        }}); dlg.show();
      });
      $('<button class="btn btn-default btn-sm" style="margin-left:8px">Configuration</button>').appendTo(bulk).on('click',()=>frappe.set_route('Form','Governance Exception Configuration'));
      function updateBulk(){assignButton.prop('disabled',selected.size===0);}
      const nav=$('<div class="flex justify-between"></div>').appendTo(listArea);
      $('<button class="btn btn-default">Previous</button>').appendTo(nav).prop('disabled',offset<=0).on('click',()=>{offset=Math.max(0,offset-limit);load();});
      $('<span></span>').text(`Showing ${offset+1}–${offset+(d.rows||[]).length} of ${d.total||0}`).appendTo(nav);
      $('<button class="btn btn-default">Next</button>').appendTo(nav).prop('disabled',!d.has_more).on('click',()=>{offset+=limit;load();});
    }});
  }

  function currentFilters(){return {status:page.fields_dict.status.get_value()||null,severity:page.fields_dict.severity.get_value()||null,assigned_to:page.fields_dict.assigned_to.get_value()||null};}
  function exportReport(){
    frappe.call({method:'governance.api.get_governance_exception_report',args:{filters:currentFilters(),limit:5000},callback:r=>{
      const rows=(r.message||{}).rows||[]; if(!rows.length){frappe.msgprint('No exception records match the selected filters.');return;}
      const cols=['name','title','source_doctype','source_name','exception_type','severity','status','assigned_to','due_date','overdue_days','risk_score','route','routing_status','modified'];
      const csv=[cols.join(',')].concat(rows.map(row=>cols.map(k=>{const v=row[k]===null||row[k]===undefined?'':String(row[k]);return '"'+v.replace(/"/g,'""')+'"';}).join(','))).join('\r\n');
      const blob=new Blob([csv],{type:'text/csv;charset=utf-8;'}); const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url;a.download='governance-exception-management-report.csv';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
    }});
  }
  function printReport(){
    frappe.call({method:'governance.api.get_governance_exception_report',args:{filters:currentFilters(),limit:5000},callback:r=>{
      const rows=(r.message||{}).rows||[];const esc=v=>frappe.utils.escape_html(String(v===undefined||v===null?'':v));
      const html=`<html><head><title>Governance Exception Management Report</title><style>body{font-family:Arial,sans-serif;padding:24px}h1{font-size:22px}table{width:100%;border-collapse:collapse;font-size:10px}th,td{border:1px solid #ccc;padding:5px;text-align:left}th{background:#eee}</style></head><body><h1>Governance Exception Management Report</h1><p>Generated: ${esc(frappe.datetime.now_datetime())}</p><p>Records: ${rows.length}</p><table><thead><tr><th>Title</th><th>Source</th><th>Severity</th><th>Status</th><th>Owner</th><th>Due</th><th>Overdue</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${esc(x.title)}</td><td>${esc(x.source_doctype)} / ${esc(x.source_name)}</td><td>${esc(x.severity)}</td><td>${esc(x.status)}</td><td>${esc(x.assigned_to)}</td><td>${esc(x.due_date)}</td><td>${esc(x.overdue_days)}</td></tr>`).join('')}</tbody></table></body></html>`;
      const win=window.open('','_blank');if(!win){frappe.msgprint('Please allow pop-ups to print the report.');return;}win.document.write(html);win.document.close();win.focus();win.print();
    }});
  }
  load(); page.set_primary_action('Refresh',()=>{loadDashboard();load();});
};
