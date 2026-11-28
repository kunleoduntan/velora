/* ProjectOne Resource Management forms and capacity overview. */
(function () {
  "use strict";
  if (!window.Velora || !window.Velora.registerFormComponent || !window.React) {
    console.warn("ProjectOne resource forms unavailable: Velora custom-form bridge not loaded.");
    return;
  }
  const React = window.React, h = React.createElement;
  const input = (label, name, doc, onChange, type="text", options=[]) => h("label", {className:"p1-field", key:name},
    h("span",null,label), type === "select" ? h("select",{value:doc[name]||"",onChange:e=>onChange(name,e.target.value)},
      options.map(x=>h("option",{key:x,value:x},x))) : h("input",{type,value:doc[name]??"",onChange:e=>onChange(name,type==="number"?(e.target.value===""?null:Number(e.target.value)):e.target.value)}));
  const panel = (title, fields) => h("section",{className:"p1-section"},h("h3",null,title),h("div",{className:"p1-grid"},fields));
  function ResourceProfile({doc,readOnly,onChange}) {
    const change=(key,value)=>onChange(key,value);
    return h("div",{className:"p1-form"},h("header",{className:"p1-hero"},h("div",null,
      h("span",{className:"p1-eyebrow"},"RESOURCE MANAGEMENT"),h("h2",null,doc.display_name||"New Resource"),
      h("p",null,"Enterprise resource pool and capacity profile"))),
      panel("Resource identity",[
        input("Resource ID","resource_id",doc,change),input("Display name","display_name",doc,change),
        input("Resource type","resource_type",doc,change,"select",["Employee","Consultant","Contractor","Equipment","Facility"]),
        input("Employee link","employee",doc,change),input("Department","department",doc,change),
        input("Job title","job_title",doc,change),input("Resource manager","manager",doc,change)]),
      panel("Capacity and commercial rates",[
        input("Daily capacity (hours)","daily_capacity_hours",doc,change,"number"),input("Cost rate","cost_rate",doc,change,"number"),
        input("Billing rate","billing_rate",doc,change,"number"),input("Active from","active_from",doc,change,"date"),
        input("Active to","active_to",doc,change,"date")]),
      panel("Skills and availability",[
        h("p",{className:"p1-resource-hint"},"Maintain verified skills in Resource Skill records. Availability is calculated from the resource calendar, exceptions and approved allocations.")])
    );
  }
  function Timesheet({doc,readOnly,onChange}) {
    const change=(key,value)=>onChange(key,value);
    return h("div",{className:"p1-form"},h("header",{className:"p1-hero"},h("div",null,
      h("span",{className:"p1-eyebrow"},"TIME CAPTURE"),h("h2",null,doc.name||"Project Timesheet"),
      h("p",null,"Submit daily project hours for independent approval"))),
      panel("Timesheet header",[
        input("Employee","employee",doc,change),
        input("Project","project",doc,change),input("Week ending","week_ending",doc,change,"date"),
        input("Total hours","total_hours",doc,change,"number"),input("Billable hours","billable_hours",doc,change,"number")]),
      h("p",{className:"p1-resource-hint"},"Daily entry lines are recorded in Project Timesheet Entry. Submitted records require an independent approver. Approved entries may be sent to the HRMS/Payroll integration inbox; ProjectOne does not calculate payroll or post to the General Ledger."),
      panel("Approval status",[input("Status","approval_status",doc,change,"select",["Draft","Pending Approval","Approved","Rejected"])])
    );
  }
  window.Velora.registerFormComponent("Resource Profile",ResourceProfile,"velora_projectone");
  window.Velora.registerFormComponent("Project Timesheet",Timesheet,"velora_projectone");
})();
