/* ProjectOne Agile board. Story changes are delegated to host-authorised actions. */
(function () {
  "use strict";
  if (!window.Velora || !window.Velora.registerFormComponent || !window.React) {
    console.warn("ProjectOne Agile board not registered: Velora custom-form bridge unavailable.");
    return;
  }
  const React = window.React, h = React.createElement;
  const lanes = ["Backlog", "Ready", "In Progress", "In Review", "Done"];
  const laneFor = s => ({Draft:"Backlog",Open:"Backlog",Ready:"Ready","In Progress":"In Progress","In Review":"In Review",Done:"Done",Blocked:"In Progress",Cancelled:"Backlog"}[s] || "Backlog");
  function AgileBoard({doc, readOnly, onTransition}) {
    const stories = Array.isArray(doc.stories) ? doc.stories : [];
    const [filter, setFilter] = React.useState("All");
    const [query, setQuery] = React.useState("");
    const columns = lanes.map(name => ({name, items:stories.filter(s => laneFor(s.status) === name)
      .filter(s => filter === "All" || s.priority === filter)
      .filter(s => !query || `${s.story_key||s.story_id} ${s.title} ${s.assignee||""}`.toLowerCase().includes(query.toLowerCase()))}));
    const total = stories.reduce((n,s)=>n+Number(s.story_points||0),0);
    const accepted = stories.filter(s=>s.status === "Done" && s.accepted === true).reduce((n,s)=>n+Number(s.story_points||0),0);
    return h("div",{className:"p1-agile"},
      h("header",{className:"p1-agile-head"},h("div",null,h("span",{className:"p1-eyebrow"},"AGILE DELIVERY"),h("h2",null,doc.title||"Sprint board"),h("p",null,doc.sprint_name||"Product backlog and sprint execution")),
        h("div",{className:"p1-agile-kpis"},h("div",null,h("b",null,stories.length),h("small",null,"Stories")),h("div",null,h("b",null,total),h("small",null,"Planned points")),h("div",null,h("b",null,accepted),h("small",null,"Accepted points")))),
      h("div",{className:"p1-agile-tools"},h("input",{type:"search",placeholder:"Search stories or assignees",value:query,onChange:e=>setQuery(e.target.value)}),
        h("select",{value:filter,onChange:e=>setFilter(e.target.value)},["All","Critical","High","Normal","Low"].map(x=>h("option",{key:x,value:x},x==="All"?"All priorities":x)))),
      h("div",{className:"p1-agile-board"},columns.map(col=>h("section",{className:"p1-agile-lane",key:col.name},
        h("div",{className:"p1-agile-lane-head"},h("b",null,col.name),h("span",null,col.items.length)),
        col.items.map(story=>h("article",{className:"p1-agile-card",key:story.story_key||story.story_id},
          h("div",{className:"p1-agile-card-meta"},h("small",null,story.story_key||story.story_id),h("span",{"data-priority":story.priority||"Normal"},story.priority||"Normal")),
          h("strong",null,story.title),h("p",null,story.assignee||"Unassigned"),
          h("div",{className:"p1-agile-card-foot"},h("span",null,`${story.story_points||0} points`),story.status==="Blocked"?h("em",null,"Blocked"):null),
          !readOnly && typeof onTransition === "function" && story.status !== "Done" && story.status !== "Cancelled"
            ? h("button",{type:"button",onClick:()=>onTransition(story,story.status==="In Progress"?"In Review":story.status==="In Review"?"Done":story.status==="Ready"?"In Progress":"Ready")},"Advance") : null
        ))
      ))),
      h("p",{className:"p1-agile-note"},"Board is a view of persisted story records. Moving a story invokes the host workflow and must pass the Definition of Ready / Done and permission checks."));
  }
  window.Velora.registerFormComponent("Project Agile Board",AgileBoard,"velora_projectone");
})();
