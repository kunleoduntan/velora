# Velora framework completion roadmap

The following work is intentionally split into independently testable releases. Existing application metadata and company data must remain backward compatible.

## Batch 3 — Frappe feature parity and graphical object management
- Complete field metadata: fetch-from, allow-on-submit, permission levels, depends-on validation and additional field behaviours.
- Document lifecycle parity: naming, autoname patterns, amend/cancel rules, child table lifecycle, default values and fetch logic.
- Form builder: visual field designer, sections, tabs, columns, conditional rules, preview and versioned metadata changes.
- Object catalogue: DocTypes, reports, workflows, scripts, print formats, notifications, dashboards, workspaces and website/portal objects.
- Object history, compare, export/import, restore and dependency impact analysis.
- Explicit distinction between app-owned objects and company-owned overrides.

## Batch 4 — Application Lifecycle Manager
- Graphical app catalogue with create, install, disable, upgrade, uninstall and dependency views.
- Semantic versioning, compatibility declarations, dependency lock data and preflight checks.
- Migration preview, dry-run, execution log, backup gate, rollback plan and health checks.
- App package manifest, integrity checks, install permissions and audit trail.
- Site/company-aware deployment so an app can be enabled for selected company databases without mixing their metadata or records.

## Batch 5 — React production bundle and UI extension ecosystem
- Standard production React toolchain with TypeScript, Vite, deterministic builds, code splitting, lazy routes, hashed assets and manifest generation.
- Environment-specific build configuration, source-map policy, asset validation and reproducible package output.
- UI extension catalogue with typed extension points, dependency declarations, version compatibility and permission scopes.
- Extension sandboxing, lifecycle hooks, error boundaries, extension diagnostics and rollback.
- UI package testing, linting, type checking and build verification in CI.

## Batch 6 — Deployment orchestration and marketplace
- Deployment targets/environments, deployment plans, approvals, maintenance windows and deployment logs.
- Staged rollout, health checks, automatic rollback and backup/restore integration.
- Signed application packages, publisher identity, package provenance, vulnerability checks and compatibility metadata.
- Private and public marketplace catalogues, discovery, installation, updates, licensing hooks and publisher workflows.
- Tenant/company policy controls and auditable distribution.

## Release gates
- No destructive schema changes without explicit migration plans.
- Every new metadata feature requires backend and frontend tests.
- Every release must pass Python tests, frontend typecheck/build, migration tests and a clean install/upgrade test.
- No marketplace package or extension may execute arbitrary code without an explicit trust and permission boundary.
