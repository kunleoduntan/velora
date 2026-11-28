# ProjectOne Product Completion Roadmap

This roadmap defines the full product scope. Status is explicit as of **v1.0.0**; delivered domain services must not be confused with a deployed frontend or production integration.

| Domain | Scope | 0.1.0 status |
|---|---|---|
| Portfolio | Portfolio, programme, strategic theme, business case, prioritisation, stage gates, scenario planning | Core records and portfolio/executive read models delivered; scenario UI remains |
| Initiation | Proposal, feasibility, charter, stakeholder register, approvals | Core records delivered; workflow templates specified |
| Planning | WBS, task, dependency, milestone, baseline, calendars, schedule versions | Metadata, four-link CPM and calendar-aware forward-pass schedule delivered; full backward-pass/float and Gantt UI remain |
| Execution | Task boards, work queues, checklists, recurring work, comments, notifications, deliverable acceptance | Core task and deliverable records delivered; collaboration UI specified |
| Agile | Backlog, stories, sprints, Scrum ceremonies, Kanban WIP, velocity, releases | Metadata, sprint validation and accepted-story metrics delivered; interactive boards and ceremonies UI remain |
| Resources | Skills, roles, capacity, availability, allocations, workload heatmaps, equipment | Capacity, skill matching and greedy levelling services delivered; heatmaps and advanced optimiser remain |
| Financials | Budgets, revisions, commitments, actuals, billing, revenue recognition, profitability, EVM | Budget, EVM, forecast, commitment, contract and billing controls delivered; source adapters and revenue recognition integration remain |
| Procurement/contracts | Requisitions, PO links, contracts, variations, supplier scorecards, retention | Commitment reconciliation and contract/billing validation delivered; live Procurement adapters and workflows remain |
| Governance | Risk, issue, change request, approvals, audit, escalation | Risk/change/quality validation and authorization primitives delivered; durable host workflows/audit and enforcement remain |
| Quality | Quality plans, inspections, tests, defects, corrective action, acceptance | Inspection metadata delivered; full quality workflow specified |
| Collaboration | Meetings, decisions, actions, files, versioning, communications | Meeting/document register metadata delivered; native document integration specified |
| Reporting | Executive, project manager, finance, resource, risk and portfolio dashboards; drill-through | Portfolio and executive read models delivered; host query, drill-through and dashboard UI remain |
| AI | Planning, risk, finance, schedule, resource, reporting and portfolio advisors | Advisory-only explainable project insight service delivered; provider-backed agents and governed retrieval remain |
| Closure | Financial reconciliation, asset handover, lessons learned, benefits realisation | Closure metadata delivered; validation workflow specified |
| Enterprise | Multi-currency, role-scoped access, audit, performance, accessibility | Framework contracts identified; full qualification outstanding |

## Completion gates
1. Finish all DocType relationships, controllers, validations and lifecycle rules.
2. Complete project row-scope security and permission tests.
3. Complete calendar-aware CPM scheduler, Gantt UI, baselines and resource levelling.
4. Complete project finance source adapters and reconciliation against Accounting.
5. Complete resource capacity, timesheets and payroll costing integration.
6. Complete procurement, contract, quality, collaboration and closure workflows.
7. Complete dashboards, report drill-through and export.
8. Add methodology templates and industry starter kits.
9. Add read-only AI advisors with human approval boundaries.
10. Run unit, integration, migration, security, concurrency, performance, accessibility and browser UAT.

The v1.0.0 package is a domain/API milestone, not a production certification. No production-ready claim is permitted until these gates pass in a real Velora staging environment.
