# Velora Governance v1.2.0

## Sustainability Executive Dashboard & Workflow Integration Foundation

### Delivered
- Executive reporting dashboard aggregation expanded with framework rollups, disclosure readiness, owner task accountability, and enhanced gap metadata.
- Dashboard API filters for governance entity, reporting period, and framework.
- Framework-filtered disclosure and collection-task reporting.
- Sustainability workspace expanded with reporting dashboard entry point, reporting runs, task accountability, gap analysis, and additional KPI cards.
- Dashboard outputs include reporting-period, framework, owner, review queue, task, report, and disclosure-gap summaries.

### Workflow architecture
- No approval process hardcoded. Review and approval routing remains configured through the Velora Workflow Engine.
- This release provides review queue/dashboard visibility, not a replacement workflow engine.

### Qualification
- Pytest suite passed: 15 tests (7 dashboard tests and 8 sustainability-reporting tests).
- Metadata validation and Python compilation passed.
- Framework runtime install, real database persistence, live API execution, full UI/browser testing, PostgreSQL qualification and permission matrix testing remain outstanding.
- The workspace uses native framework workspace widgets and list shortcuts. A dedicated custom graphical dashboard page with charts is not yet implemented.
