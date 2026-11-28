# Velora Governance v2.5.0 — Executive Governance Command Centre

This consolidated batch delivers service-layer milestones v2.1.0 through v2.5.0.

## v2.1.0 — Governance Task Automation Runtime
- Deterministic automation action planning
- Configurable reminder/escalation rules and templates
- Idempotency keys to suppress duplicate action plans
- Runtime deliberately does not dispatch messages; native notification/workflow services must perform delivery

## v2.2.0 — Board & Committee Action Accountability
- Open/completed/overdue/due-soon/unassigned rollups
- Completion rate
- Owner and committee workload distribution
- Attention-item list

## v2.3.0 — Governance Risk and Control Integration
- Risk-to-control mapping
- Control test result rollups
- Failed/ineffective controls
- Overdue testing and controls needing tests
- Risk-control coverage metric

## v2.4.0 — Regulatory Compliance Intelligence
- Obligation status rollups
- Overdue and due-soon obligations
- Missing-owner detection
- Authority/status breakdowns and compliance rate

## v2.5.0 — Executive Governance Command Centre
- Aggregates task, board action, risk, control and compliance intelligence
- Unified executive priority queue
- Critical/high risk and overdue compliance/control indicators

## Qualification
Pure service-layer tests are included. Native Velora runtime persistence, scheduler/notification dispatch, permissions, workflow integration, UI dashboard wiring, browser testing and UAT remain pending qualification. No new DocTypes were added in this batch, avoiding schema migrations until the native runtime integration pass.
