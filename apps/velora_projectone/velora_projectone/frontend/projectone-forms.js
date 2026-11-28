/* Velora ProjectOne v1.3.0 — native Desk form components. */
(function () {
  "use strict";
  if (!window.Velora || !window.Velora.registerFormComponent || !window.React) {
    console.warn("ProjectOne forms were not registered: Velora custom-form bridge is unavailable."); return;
  }
  const React=window.React, h=React.createElement;
  const field=(label,name,value,props,type,options)=>h("label",{className:"p1-field",key:name},h("span",null,label),
    type==="select"?h("select",{value:value??"",disabled:props.readOnly,onChange:e=>props.onChange(name,e.target.value)},(options||[]).map(v=>h("option",{key:v,value:v},v))):
    type==="textarea"?h("textarea",{value:value??"",readOnly:props.readOnly,rows:3,onChange:e=>props.onChange(name,e.target.value)}):
    h("input",{type:type||"text",value:value??"",readOnly:props.readOnly,onChange:e=>props.onChange(name,type==="number"?(e.target.value===""?null:Number(e.target.value)):e.target.value)}));
  const section=(title,children,hint)=>h("section",{className:"p1-section",key:title},h("div",{className:"p1-section-head"},h("h3",null,title),hint?h("p",null,hint):null),h("div",{className:"p1-grid"},children));
  function ProjectForm({doc,readOnly,onChange}){
    const p={readOnly,onChange},status=doc.status||"Draft",progress=Math.max(0,Math.min(100,Number(doc.progress_percent||0)));
    return h("div",{className:"p1-form p1-project"},
      h("header",{className:"p1-hero"},h("div",null,h("span",{className:"p1-eyebrow"},"PROJECT CONTROL"),h("h2",null,doc.title||"New Project"),h("p",null,`${doc.project_code||"Project code pending"} · ${doc.methodology||"Waterfall"} methodology`)),h("span",{className:"p1-status","data-status":status.toLowerCase().replace(/[^a-z]+/g,"-")},status)),
      h("div",{className:"p1-progress"},h("div",{className:"p1-progress-meta"},h("strong",null,"Delivery progress"),h("b",null,`${progress.toFixed(0)}%`)),h("div",{className:"p1-progress-track"},h("span",{style:{width:`${progress}%`}}))),
      section("Project identity",[field("Project name","title",doc.title,p),field("Project code","project_code",doc.project_code,p),field("Project type","project_type",doc.project_type,p),field("Portfolio","portfolio",doc.portfolio,p),field("Programme","programme",doc.programme,p),field("Methodology","methodology",doc.methodology,p,"select",["Waterfall","Agile","Hybrid","Kanban","Custom"]),field("Project manager","project_manager",doc.project_manager,p),field("Project status","status",doc.status,p,"select",["Draft","Open","In Progress","On Hold","Completed","Cancelled"]),field("Sponsor","sponsor",doc.sponsor,p),field("Customer","customer",doc.customer,p)]),
      section("Schedule & delivery",[field("Planned start","start_date",doc.start_date,p,"date"),field("Planned finish","end_date",doc.end_date,p,"date"),field("Actual start","actual_start_date",doc.actual_start_date,p,"date"),field("Actual finish","actual_end_date",doc.actual_end_date,p,"date"),field("Progress (%)","progress_percent",doc.progress_percent,p,"number"),field("Department","department",doc.department,p),field("Project health","health",doc.health,p,"select",["Not Assessed","Green","Amber","Red"])]),
      section("Financial control",[field("Currency","currency",doc.currency,p),field("Approved budget","approved_budget",doc.approved_budget,p,"number")],"Project financial values are planning and monitoring dimensions. Accounting remains the posting authority."),
      section("Governance & context",[field("Project description","description",doc.description,p,"textarea"),field("Scope statement","scope_statement",doc.scope_statement,p,"textarea"),field("Success criteria","success_criteria",doc.success_criteria,p,"textarea")]));
  }
  function PortfolioForm({doc,readOnly,onChange}){const p={readOnly,onChange};return h("div",{className:"p1-form"},h("header",{className:"p1-hero"},h("div",null,h("span",{className:"p1-eyebrow"},"PORTFOLIO GOVERNANCE"),h("h2",null,doc.portfolio_name||doc.title||"New Portfolio"),h("p",null,"Strategic investment grouping and prioritisation"))),section("Portfolio profile",[field("Portfolio name","portfolio_name",doc.portfolio_name,p),field("Portfolio owner","portfolio_owner",doc.portfolio_owner,p),field("Strategic theme","strategic_theme",doc.strategic_theme,p),field("Status","status",doc.status,p,"select",["Draft","Open","In Progress","On Hold","Completed","Cancelled"]),field("Approved budget","portfolio_budget",doc.portfolio_budget,p,"number")]),section("Strategic mandate",[field("Portfolio description","description",doc.description,p,"textarea")]));}
  function ProgrammeForm({doc,readOnly,onChange}){const p={readOnly,onChange};return h("div",{className:"p1-form"},h("header",{className:"p1-hero"},h("div",null,h("span",{className:"p1-eyebrow"},"PROGRAMME DELIVERY"),h("h2",null,doc.programme_name||doc.title||"New Programme"),h("p",null,"Coordinated delivery of related projects and benefits"))),section("Programme profile",[field("Programme name","programme_name",doc.programme_name,p),field("Portfolio","portfolio",doc.portfolio,p),field("Programme manager","programme_manager",doc.programme_manager,p),field("Status","status",doc.status,p,"select",["Draft","Open","In Progress","On Hold","Completed","Cancelled"]),field("Start date","start_date",doc.start_date,p,"date"),field("End date","end_date",doc.end_date,p,"date")]),section("Benefits & outcomes",[field("Benefits statement","benefits_statement",doc.benefits_statement,p,"textarea")]));}
  window.Velora.registerFormComponent("Project",ProjectForm,"velora_projectone");
  window.Velora.registerFormComponent("Project Portfolio",PortfolioForm,"velora_projectone");
  window.Velora.registerFormComponent("Project Programme",ProgrammeForm,"velora_projectone");
})();

/* Read-only Gantt projection. Schedule mutations go through validated server commands. */
(function () {
  "use strict";
  if (!window.Velora || !window.Velora.registerFormComponent || !window.React) return;
  const h = window.React.createElement;
  function GanttView({doc}) {
    const rows = doc.gantt_rows || [];
    const maxDay = Math.max(1, ...rows.map(r => Number(r.bar_offset_days || 0) + Math.max(1, Number(r.bar_duration_days || 0))));
    return h("div", {className:"p1-gantt"},
      h("header", {className:"p1-hero"}, h("div", null,
        h("span", {className:"p1-eyebrow"}, "SCHEDULE CONTROL"),
        h("h2", null, doc.title || "Project Gantt"),
        h("p", null, `${doc.project_start || ""} — ${doc.project_finish || ""} · ${rows.length} activities`))),
      h("div", {className:"p1-gantt-legend"},
        h("span", null, h("i", {className:"p1-gantt-bar"}), " Planned task"),
        h("span", null, h("i", {className:"p1-gantt-bar p1-critical"}), " Critical task"),
        h("span", null, h("i", {className:"p1-milestone"}), " Milestone")),
      h("div", {className:"p1-gantt-scroll"},
        h("table", {className:"p1-gantt-table"},
          h("thead", null, h("tr", null,
            h("th", null, "Activity"), h("th", null, "Start"), h("th", null, "Finish"),
            h("th", null, "Float"), h("th", {className:"p1-timeline-head"}, "Working-day timeline"))),
          h("tbody", null, rows.map(row => h("tr", {key:row.id},
            h("td", null, h("strong", null, row.name || row.id), row.wbs ? h("small", null, row.wbs) : null),
            h("td", null, row.early_start_date), h("td", null, row.early_finish_date),
            h("td", null, `${row.total_float}d`),
            h("td", {className:"p1-timeline-cell"},
              h("div", {className:"p1-timeline-track", style:{"--p1-days":maxDay}},
                row.milestone
                  ? h("span", {className:"p1-milestone", style:{left:`${(row.bar_offset_days/maxDay)*100}%`}, title:row.name || row.id})
                  : h("span", {className:`p1-gantt-bar${row.critical ? " p1-critical" : ""}`,
                      style:{left:`${(row.bar_offset_days/maxDay)*100}%`,width:`${(row.bar_duration_days/maxDay)*100}%`},
                      title:`${row.name || row.id}: ${row.early_start_date} to ${row.early_finish_date}`})))))))));
  }
  window.Velora.registerFormComponent("Project Gantt View", GanttView, "velora_projectone");
})();
