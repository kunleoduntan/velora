# Velora Governance v4.5.0 Release Notes

## New services

- `governance_operations_dashboard`: operational KPI aggregation and priority queue.
- `governance_automation_monitor`: execution history summary and retry candidate selection.
- `governance_configuration_center`: validation of rules, templates, schedules and routing configuration.
- `governance_release_qualification`: evidence-driven release gates.

## Safety and architecture

- Services consume permission-scoped datasets; host runtime remains responsible for access control.
- Retry selection does not dispatch actions.
- Approval routing must use the native workflow engine.
- Qualification is evidence-gated and cannot self-certify production.

## Test result

71 tests passed in the full test suite.
