# Velora Governance v1.3.0 — Sustainability Dashboard UI & Operational Workflow

## Delivered

- Dedicated Sustainability Executive Dashboard Desk Page.
- KPI cards: overall readiness, applicable disclosures, ready disclosures, disclosure gaps, task totals, completed tasks, overdue tasks, reports and pending reviews.
- Framework readiness progress bars.
- Task accountability by owner.
- Reporting-period progress table.
- Disclosure gap table with framework, status, readiness, owner, due date and gap summary.
- Entity, reporting period and framework filters.
- Refresh and clear-filter controls.
- Responsive layout for tablet/mobile and horizontally scrollable data tables.
- Dashboard page linked from Sustainability workspace.
- Dashboard data continues to use existing permission-aware API.

## Architecture

- The page uses the existing dashboard API and aggregation service.
- The application does not introduce its own workflow or approval routing. Approval routing, levels, conditions, delegation and escalation remain configured in the Velora workflow engine.
- KPI and chart content is derived from API results; no demo metrics are hard-coded.

## Qualification

- Focused tests cover dashboard page assets, API method reference, filters, sections, responsive styling and workspace route.
- Browser-level interaction, framework-native page loading, live API/database access, PostgreSQL and accessibility testing remain pending because the Velora runtime is not available in this build environment.
- Wheel is manually assembled from source because standard build dependencies/runtime are unavailable. It is a test artifact pending framework-native installation qualification.
