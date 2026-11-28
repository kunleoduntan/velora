/* ProjectOne interactive Gantt workspace. Dragging a task creates a server-side
 * what-if preview only; committing a date requires the governed host workflow. */
(function () {
  'use strict';
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const sample = [
    {id:'T-100',name:'Requirements and scope',duration:5,dependencies:[]},
    {id:'T-110',name:'Solution design',duration:6,dependencies:[{predecessor:'T-100',type:'FS',lag:0}]},
    {id:'T-120',name:'Build and configuration',duration:12,dependencies:[{predecessor:'T-110',type:'FS',lag:0}]},
    {id:'T-130',name:'Testing and acceptance',duration:5,dependencies:[{predecessor:'T-120',type:'FS',lag:0}]},
    {id:'M-100',name:'Go-live milestone',duration:0,dependencies:[{predecessor:'T-130',type:'FS',lag:0}]}
  ];
  function mount(root) {
    if (!root) throw new Error('Schedule workspace root is required.');
    root.classList.add('po-schedule-workspace');
    let activities = sample, schedule = null, dragging = null, dragOffsetX = 0, lastPreview = null, baselineRows = null, liveMode = false, activeWorkingWeekdays = [0,1,2,3,4], activeHolidays = [];
    const selectedWorkingWeekdays = () => $('.po-week').value ? $('.po-week').value.split(',').map(Number) : activeWorkingWeekdays;
    root.innerHTML = `<header class="po-schedule-head"><div><div class="po-schedule-eyebrow">VELORA PROJECTONE · DELIVERY CONTROL</div><h2>Project Schedule Workspace</h2><p>Review CPM dates, critical path, float and baseline variance. Drag a task to preview a later start.</p></div><button type="button" class="po-schedule-reset">Reset example</button></header>
      <section class="po-schedule-config"><label>Project ID <input class="po-project-id" placeholder="Enter authorised project ID"></label><label>Project start <input class="po-project-start" type="date" value="2026-12-01"></label><label>Working calendar <select class="po-week"><option value="">Use project calendar</option><option value="0,1,2,3,4">Override: Monday–Friday</option><option value="0,1,2,3,4,5">Override: Monday–Saturday</option><option value="0,1,2,3,4,5,6">Override: All days</option></select></label><button type="button" class="po-schedule-live">Load live project</button><button type="button" class="po-schedule-load">Calculate example / JSON</button></section>
      <details class="po-schedule-input"><summary>Schedule data (JSON)</summary><p>Enter task IDs, durations in working days and dependency relationships (FS, SS, FF or SF).</p><textarea class="po-activities" spellcheck="false"></textarea><label>Optional baseline task snapshots (JSON) <textarea class="po-baseline" spellcheck="false" placeholder='[{"id":"T-100","start_date":"2026-12-01","finish_date":"2026-12-07"}]'></textarea></label></details>
      <section class="po-dependency-editor"><div><h3>Dependency editor</h3><p>Create or revise task links. The server checks the full dependency graph and rejects cycles.</p></div><div class="po-dependency-fields"><label>Predecessor <select class="po-dep-predecessor"></select></label><label>Successor <select class="po-dep-successor"></select></label><label>Relationship <select class="po-dep-type"><option>Finish to Start</option><option>Start to Start</option><option>Finish to Finish</option><option>Start to Finish</option></select></label><label>Lag (working days) <input class="po-dep-lag" type="number" value="0" step="1"></label><label>Edit existing link <select class="po-dep-existing"><option value="">Create new link</option></select></label><button type="button" class="po-dep-save" disabled>Save dependency</button></div><div class="po-dependency-list"></div></section>
      <div class="po-schedule-message" role="status">Enter a project ID and calculate the schedule. Example task data is preloaded.</div>
      <div class="po-schedule-kpis"></div><section class="po-schedule-chart"><div class="po-schedule-chart-title"><h3>Interactive Gantt chart</h3><span>Drag a task bar horizontally to preview its start constraint.</span></div><div class="po-gantt-rows"><p class="po-schedule-empty">No schedule calculated yet.</p></div></section>
      <section class="po-schedule-impact"><h3>Schedule change impact</h3><div class="po-schedule-impact-body">No proposed changes.</div><div class="po-schedule-request"><label>Change title <input class="po-change-title" placeholder="Reason for schedule adjustment"></label><label>Business justification <textarea class="po-change-reason" rows="3" placeholder="Explain the reason, impact and supporting context (minimum 10 characters)."></textarea></label><button type="button" class="po-submit-change" disabled>Submit schedule change for approval</button></div></section>
      <p class="po-schedule-boundary">Live project mode reads native Velora records. A drag creates a preview only. Approved changes are applied through a separate, version-checked operation; baselines are never silently amended.</p>`;
    const $ = selector => root.querySelector(selector);
    $('.po-activities').value = JSON.stringify(activities, null, 2);
    $('.po-schedule-reset').addEventListener('click', () => { liveMode=false; baselineRows=null; lastPreview=null; $('.po-submit-change').disabled=true; activities = sample; $('.po-activities').value = JSON.stringify(sample,null,2); $('.po-baseline').value=''; schedule=null; render(); message('Example restored. Calculate to display it.'); });
    $('.po-schedule-load').addEventListener('click', load);
    $('.po-schedule-live').addEventListener('click', loadLive);
    $('.po-submit-change').addEventListener('click', submitChange);
    $('.po-dep-save').addEventListener('click', saveDependency);
    $('.po-dep-existing').addEventListener('change', loadDependencyEditor);
    function message(text, bad=false) { const el=$('.po-schedule-message'); el.textContent=text; el.classList.toggle('is-error',bad); }
    function parseInput() {
      activities = JSON.parse($('.po-activities').value);
      if (!Array.isArray(activities) || !activities.length) throw new Error('Provide a non-empty task array.');
      const baselineText=$('.po-baseline').value.trim();
      return baselineText ? JSON.parse(baselineText) : null;
    }
    async function request(url, options={}) {
      const response=await fetch(url,{credentials:'same-origin',headers:{'Accept':'application/json',...(options.body?{'Content-Type':'application/json'}:{})},...options});
      const data=await response.json().catch(()=>({detail:'The server returned an unreadable response.'}));
      if(!response.ok) throw new Error(data.detail || data.message || `Request failed (${response.status}).`);
      return data;
    }
    const post=(url,payload)=>request(url,{method:'POST',body:JSON.stringify(payload)});
    async function loadLive() {
      try {
        const project=$('.po-project-id').value.trim();
        if(!project) throw new Error('Enter a project ID to load its authorised native records.');
        const days=$('.po-week').value;
        const query=days?`?working_weekdays=${encodeURIComponent(days)}`:'';
        const result=await request(`/api/projectone/schedule/projects/${encodeURIComponent(project)}/live${query}`);
        activities=result.activities; baselineRows=result.baseline||null; liveMode=true; lastPreview=null; activeWorkingWeekdays=result.calendar?.working_weekdays||[0,1,2,3,4]; activeHolidays=result.calendar?.holidays||[]; $('.po-submit-change').disabled=true;
        populateDependencyEditor(result.dependencies||[]);
        $('.po-project-start').value=result.project.start_date;
        $('.po-activities').value=JSON.stringify(activities,null,2);
        $('.po-baseline').value=baselineRows?JSON.stringify(baselineRows,null,2):'';
        schedule=result.schedule; lastPreview=null; liveMode=true; $('.po-submit-change').disabled=true; $('.po-dep-save').disabled=false; render();
        message(`Loaded ${activities.length} native tasks using ${result.calendar?.calendar_name||'the project calendar'} (${(result.calendar?.working_weekdays||[]).join(', ')}). ${result.calendar?.holidays?.length||0} holidays applied. ${result.baseline_name?`Current baseline: ${result.baseline_name}.`:'No current approved baseline was found.'}`);
      } catch(error) { message(error.message || 'Unable to load the native project schedule.',true); }
    }
    async function submitChange() {
      try {
        if(!liveMode || !lastPreview) throw new Error('Load a live project and create a drag preview before submitting a change.');
        const title=$('.po-change-title').value.trim(), reason=$('.po-change-reason').value.trim();
        if(!title || reason.length<10) throw new Error('Enter a change title and a justification of at least 10 characters.');
        const result=await post('/api/projectone/schedule/change-requests',{
          project_id:$('.po-project-id').value.trim(),task_id:lastPreview.task_id,
          proposed_start_offset:lastPreview.proposed_start_offset,reason,title,
          idempotency_key:(window.crypto&&crypto.randomUUID?crypto.randomUUID():`sched-${Date.now()}-${Math.random().toString(16).slice(2)}`),...( $('.po-week').value ? {working_weekdays:$('.po-week').value.split(',').map(Number)} : {} )
        });
        $('.po-submit-change').disabled=true;
        message(`Schedule change ${result.change_request.name} submitted. Approval status: ${result.change_request.approval_status}. Task dates have not yet been changed.`);
      } catch(error) { message(error.message || 'Unable to submit schedule change.',true); }
    }
    let dependencyRows = [];
    function populateDependencyEditor(rows) {
      dependencyRows = rows;
      const options = activities.map(a=>`<option value="${esc(a.id)}">${esc(a.name||a.id)} (${esc(a.id)})</option>`).join('');
      $('.po-dep-predecessor').innerHTML=options; $('.po-dep-successor').innerHTML=options;
      $('.po-dep-existing').innerHTML='<option value="">Create new link</option>'+rows.map(d=>`<option value="${esc(d.name)}">${esc(d.predecessor)} → ${esc(d.successor)} · ${esc(d.relationship)}</option>`).join('');
      $('.po-dep-save').disabled=!liveMode || activities.length<2;
      $('.po-dependency-list').innerHTML=rows.length?`<div class="po-schedule-table-wrap"><table><thead><tr><th>Predecessor</th><th>Successor</th><th>Type</th><th>Lag</th><th>Active</th></tr></thead><tbody>${rows.map(d=>`<tr><td>${esc(d.predecessor)}</td><td>${esc(d.successor)}</td><td>${esc(d.relationship)}</td><td>${esc(d.lag_days||0)}</td><td>${d.active?'Yes':'No'}</td></tr>`).join('')}</tbody></table></div>`:'<p>No dependency records found.</p>';
    }
    function loadDependencyEditor() {
      const row=dependencyRows.find(d=>d.name===$('.po-dep-existing').value);
      if(!row)return;
      $('.po-dep-predecessor').value=row.predecessor; $('.po-dep-successor').value=row.successor;
      $('.po-dep-type').value=row.relationship; $('.po-dep-lag').value=row.lag_days||0;
    }
    async function saveDependency() {
      try {
        if(!liveMode)throw new Error('Load a live project before editing dependencies.');
        const predecessor=$('.po-dep-predecessor').value, successor=$('.po-dep-successor').value;
        if(!predecessor||!successor||predecessor===successor)throw new Error('Choose two different tasks.');
        const lag=Number($('.po-dep-lag').value); if(!Number.isInteger(lag))throw new Error('Lag must be a whole number of working days.');
        const existing=dependencyRows.find(d=>d.name===$('.po-dep-existing').value);
        const fields={predecessor,successor,relationship:$('.po-dep-type').value,lag_days:lag,active:1};
        if(existing) await request(`/api/projectone/schedule/dependencies/${encodeURIComponent(existing.name)}`,{method:'PUT',body:JSON.stringify({expected_version:existing.version,changes:fields})});
        else await post(`/api/projectone/schedule/projects/${encodeURIComponent($('.po-project-id').value.trim())}/dependencies`,{...fields,idempotency_key:(window.crypto&&crypto.randomUUID?crypto.randomUUID():`dep-${Date.now()}`)});
        message('Dependency saved. Reloading the live schedule…'); await loadLive();
      } catch(error){message(error.message||'Unable to save dependency.',true);}
    }
    async function load() {
      try {
        const baseline=parseInput();
        if (!$('.po-project-id').value.trim()) throw new Error('Enter the project ID to enforce project-level access.');
        const first=activities[0];
        const result=await post('/api/projectone/schedule/preview-change',{
          project_id:$('.po-project-id').value.trim(),activities,project_start:$('.po-project-start').value,
          working_weekdays:selectedWorkingWeekdays(),holidays:activeHolidays,task_id:String(first.id),
          proposed_start_offset:Number(first.planned_start_offset||0),baseline
        });
        schedule=result.schedule; lastPreview=null; render();
        if (baseline) message('Schedule calculated. Baseline snapshots are loaded for comparison when you preview a change.');
        else message('Schedule calculated. Drag any task bar to the right to preview a later start.');
      } catch(error) { message(error.message || 'Unable to calculate schedule.',true); }
    }
    async function preview(taskId, offset) {
      try {
        const baseline=parseInput();
        const result=await post('/api/projectone/schedule/preview-change',{
          project_id:$('.po-project-id').value.trim(),activities,project_start:$('.po-project-start').value,
          working_weekdays:selectedWorkingWeekdays(),holidays:activeHolidays,task_id:taskId,
          proposed_start_offset:offset,baseline
        });
        lastPreview=result; schedule=result.schedule; render();
        $('.po-submit-change').disabled=!liveMode;
        message(`Preview calculated: ${result.changed_task_count} task(s) affected. No records were changed.`);
      } catch(error) { message(error.message || 'Unable to preview schedule change.',true); }
    }
    function render() {
      if(!schedule) return;
      const rows=schedule.gantt_rows||[]; const max=Math.max(1,...rows.map(r=>r.early_start+r.duration));
      const width=Math.max(420,max*22+24);
      $('.po-schedule-kpis').innerHTML=`<article><span>Planned finish</span><strong>${esc(schedule.project_finish)}</strong></article><article><span>Working-day duration</span><strong>${schedule.duration}</strong></article><article><span>Critical activities</span><strong>${(schedule.critical_activities||[]).length}</strong></article><article><span>Schedule state</span><strong>${lastPreview?'Preview':'Calculated'}</strong></article>`;
      $('.po-gantt-rows').innerHTML=`<div class="po-gantt-scale"><span>Task / dependency</span><div style="width:${width}px">${Array.from({length:Math.ceil(max/5)+1},(_,i)=>`<i style="left:${i*110}px">Day ${i*5}</i>`).join('')}</div></div>${rows.map(r=>`<div class="po-gantt-row"><div class="po-gantt-task"><b>${esc(r.name)}</b><small>${esc(r.id)} · ${esc(r.status||'Not Started')} · ${r.duration} wd</small><small>Float: ${r.total_float} wd · ${esc((r.predecessors||[]).map(p=>`${p.id} ${p.type}`).join(', ')||'No predecessor')}</small></div><div class="po-gantt-track" data-track="${esc(r.id)}" style="width:${width}px"><div class="po-gantt-bar ${r.critical?'is-critical':''} ${r.milestone?'is-milestone':''}" draggable="true" data-task="${esc(r.id)}" title="${esc(r.early_start_date)} to ${esc(r.early_finish_date)}" style="left:${r.early_start*22}px;width:${r.milestone?12:Math.max(12,r.duration*22-4)}px">${r.milestone?'◆':''}</div></div></div>`).join('')}`;
      $('.po-gantt-rows').querySelectorAll('.po-gantt-bar').forEach(bar=>{
        bar.addEventListener('dragstart',e=>{dragging=bar.dataset.task;dragOffsetX=e.clientX-bar.getBoundingClientRect().left;e.dataTransfer.setData('text/plain',dragging);e.dataTransfer.effectAllowed='move';});
      });
      $('.po-gantt-rows').querySelectorAll('.po-gantt-track').forEach(track=>{
        track.addEventListener('dragover',e=>{e.preventDefault();e.dataTransfer.dropEffect='move';});
        track.addEventListener('drop',e=>{e.preventDefault();const id=e.dataTransfer.getData('text/plain')||dragging;if(!id)return;const rect=track.getBoundingClientRect();const offset=Math.max(0,Math.round((e.clientX-rect.left-dragOffsetX)/22));preview(id,offset);});
      });
      const impact=lastPreview;
      $('.po-schedule-impact-body').innerHTML=impact?`<div class="po-schedule-kpis"><article><span>Previous finish</span><strong>${esc(impact.previous_project_finish)}</strong></article><article><span>Proposed finish</span><strong>${esc(impact.proposed_project_finish)}</strong></article><article><span>Finish variance</span><strong>${impact.project_finish_variance_calendar_days} calendar days</strong></article><article><span>Affected tasks</span><strong>${impact.changed_task_count}</strong></article></div>${impact.impacts.length?`<div class="po-schedule-table-wrap"><table><thead><tr><th>Task</th><th>Previous start</th><th>Proposed start</th><th>Previous finish</th><th>Proposed finish</th></tr></thead><tbody>${impact.impacts.map(i=>`<tr><td>${esc(i.task_id)}</td><td>${esc(i.previous_start)}</td><td>${esc(i.proposed_start)}</td><td>${esc(i.previous_finish)}</td><td>${esc(i.proposed_finish)}</td></tr>`).join('')}</tbody></table></div>`:'<p>No downstream dates changed under this constraint.'} <p class="po-schedule-boundary">Approval required before commit: ${impact.approval_required_before_commit?'Yes':''}. Persisted: No. Baseline modified: No.</p>`:'No proposed changes.';
    }
    render();
    return {refresh:load};
  }
  window.VeloraProjectOneSchedule={mount};
  if(window.frappe&&frappe.pages){frappe.pages['projectone-schedule-workspace']=frappe.pages['projectone-schedule-workspace']||{};frappe.pages['projectone-schedule-workspace'].on_page_load=function(wrapper){const page=frappe.ui.make_app_page({parent:wrapper,title:'Project Schedule Workspace',single_column:true});const host=document.createElement('div');page.main.appendChild(host);mount(host);};}
})();
