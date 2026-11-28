# Velora ProjectOne 2.25.2

Project, programme and portfolio management for Velora: one Project record shared with VeloraERP, with planning, resources, budgets, risk, change control, Agile delivery, dashboards and a mobile app.

## What it is

- **One Project doctype.** ProjectOne owns `Project`; every VeloraERP document that carries a project (journal lines, budgets, payments, reports) links to this same record. Nothing in ProjectOne carries a company field.
- **Runs on Velora.** Records are ordinary Velora documents, so list views, forms, permissions, field access, row policies, link search, track changes and the Workflow Designer all apply. `velora_projectone/velora_host.py` is the single place that connects ProjectOne's services to the framework (documents, permissions, transactions, audit, repeat-request protection, workflow and source data).
- **Permissions like ERPNext.** Every doctype has per-role rows (read, write, create, delete, report, export, import, print, email, share) for System Manager, Project Manager, Project User and Auditor; child tables follow their parent.
- **Reads, never posts.** Actual cost and recognised revenue come from the VeloraERP ledger; ProjectOne reads them and never writes a ledger entry.

## Install

Install `velora-erp` and `velora-projectone` together (each requires the other), then `velora upgrade`. On install ProjectOne adds a **Projects** workspace.

## Mobile

`mobile/` holds the Expo app (Home, Projects, Approvals, Timesheet helper, More). It signs in with Velora, then reads `/api/projectone/*`. Run `npm ci && npm run ci:verify` there.

## Documents

`docs/ARCHITECTURE.md`, `docs/INTEGRATION_CONTRACTS.md`, `docs/SECURITY-AND-ACCOUNTING-CONTROLS.md`, `docs/PRODUCT_ROADMAP.md`, and the user and administrator guide `velora_projectone/docs/PROJECTONE-GUIDE-v2.25.2.html`.
