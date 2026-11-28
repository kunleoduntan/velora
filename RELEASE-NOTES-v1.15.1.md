# Velora Framework v1.15.1 — Stabilisation and Integration

## New in 1.15.1
- **Menu search** at the top of the sidebar: type to show only matching menu links, in their groups; Escape clears it.
- **HR & People** now holds everything about people and pay: Employee 360, Leave, Governance, My HR Services, My Performance, Team Performance, every HR document and the payroll, salary and employee-finance documents that live in the Finance module.
- **Applications** now holds the former Tools group (Operational Centre, Bank Reconciliation, Budget Workbench, Dashboards, Workflows, Notification Centre and the rest). The separate Tools group and the second "Application Workspace" link are gone.
- Sidebar restyled (dark brand bar, line icons, chevron groups open only on the current page, "Configure Features" at the bottom). The form toolbar has one **Create** menu for create-from-another-document actions.
- The Desk is rebuilt from source (`velora/desk`), type-checked, and the frontend test suite restored (it was missing from the 1.15.0 source package). A type error in the Role & Field Permissions page is fixed.

## From 1.15.0

### 1. Link autocomplete performance and correctness
- Replaced broad, multi-column global search for Link autocomplete with a bounded exact/prefix/title-field search path.
- Search fields are restricted to readable title/list fields; DocType read, row, company, sharing and User Permission checks remain delegated to the normal `get_list` authorization path.
- Results are ranked exact, prefix, then contains and are capped at the requested limit.
- Frontend ignores one-character queries, debounces typing, cancels stale requests and times out a Link request after eight seconds.
- Hidden title fields fall back to the record name rather than failing the Link lookup.

### 2. Frappe-style Role & Field Permissions
- Added role administration endpoints for roles, DocType permission metadata, role permissions and field-access overrides.
- Added company-local Role & Field Permissions page.
- Permission actions now include read, write, create, delete, submit, cancel, amend, report, export, import, print, email and share.
- Role grants are configured per DocType and `permlevel`; optional per-role field overrides can further restrict a field to read-only or hidden.
- A role referenced by installed DocType metadata can be selected and provisioned into the company-local role permission registry on first use.
- The server remains authoritative; the UI is not a substitute for API-side checks.

### 3. Internal server reads and field permissions
- Explicit trusted server-side `get_list(..., ignore_permissions=True)` calls may read/filter internal fields needed by controllers and scheduled operations.
- Public resource APIs do not expose this bypass. Normal user reads, filters, lists and Link lookups continue to enforce field permission levels.
- Added explicit trusted-field support for server-maintained approval fingerprints.

### 4. Report and workflow workspace
- Report grid headings support drag-to-resize, minimum/maximum widths, horizontal scrolling and per-user/per-report width persistence.
- Workflow administration is organised into tabs and scopes the designer, governance and monitoring views to one selected DocType.
- Workflow definitions are company-authored in the GUI. The Framework no longer receives DocType-specific starter workflow templates from VeloraERP.

## Compatibility
- Framework: 1.15.1
- VeloraERP: 2.91.0 (`>=1.15.0,<1.16.0`)
- ProjectOne: 2.21.0 (`>=1.15.0,<1.16.0`)
