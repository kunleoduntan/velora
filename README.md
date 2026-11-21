# Velora

A metadata-driven business application framework (Python · PostgreSQL or SQLite · React). Define a DocType in JSON and get the table, the API, permissions, workflows,
printing, files, notifications and a Desk UI for free. Every company gets its own database; one folder holds the whole installation.

**Status: Velora 1.13.0 with VeloraERP 2.89.0.** See `CHANGELOG.md`, the `RELEASE-NOTES-*` files and `docs/README.md`.

## One command
```bash
bash install-dev.sh --workspace ~/my-erp --email you@company.com     # any Linux or macOS, no root: installs Velora, creates everything, starts it
```
Already installed? `velora quickstart my-erp --email you@company.com` does the same. It creates the workspace folder, the control plane, a first company with its own
database, a sample app and the administrator, then starts the server. Open <http://localhost:8000>, sign in, and a welcome page explains what was set up
(`/tutorial` explains the rest). Next time: `cd my-erp && velora start`. Starting also upgrades anything that needs it and repairs permissions: there is nothing else to remember.
Servers: `sudo bash deploy/install.sh --email you@company.com` (Ubuntu or Debian; PostgreSQL, a service, optional HTTPS).

## One folder, six places
```
my-erp/
  apps/        code      your apps and installed apps (the only folder you edit or put in version control)
  config/      settings  which apps are on, installation settings, a plain history of installs and updates
  platform/    system    sign-in, people, companies (control.db), the master key, one database file per SQLite company
  files/       uploads   everything people attached, one folder per company
  backups/     backups   encrypted workspace backups and the safety copy before every update
  logs/        logs      logs and evidence (restore rehearsals)
```
The folder is **relocatable** (move, rename, copy or restore it anywhere and it opens its own data), everything except `apps/` is readable only by its owner, and the generated
`.gitignore` means `git add .` can never publish a key or a database. `velora layout` shows it with real sizes and repairs it. Full guide: `docs/file-structure.md`.

## The commands you need
The complete reference, every command and every option, is `docs/commands.md` (generated from the real command line). Installing and updating from GitHub: `docs/install-from-github.md`.

| Command | Does |
|---|---|
| `velora quickstart DIR --email E` | everything above, in one step |
| `velora start` | run it (also upgrades and tidies by itself) |
| `velora doctor` | check the installation, say how to fix anything wrong |
| `velora update` | new versions: code, migrations and restart, in one step |
| `velora install-app NAME_OR_URL` / `uninstall-app` | add or remove an app in every company |
| `velora ops backup` / `ops restore-workspace BACKUP --into DIR` | encrypted backup, and recovery on a machine that has nothing |
| `velora import-data DOCTYPE FILE --dry-run` | load any DocType's data from Excel, CSV or JSON (checks first, saves nothing) |
| `velora layout [--fix]` | the folder structure with sizes; repair permissions and old layouts |

## Building apps
```bash
velora new-app accounting                                           # scaffold an app (apps/accounting)
velora new-doctype "Journal Entry" --app accounting --submittable   # JSON + controller + client scripts
velora install-app accounting                                       # validates, creates tables, runs after_install: atomically, in every company
```
An app is `apps/<app>/<app>/<module>/doctype/<name>/{json,py,js,_list.js}`. The older one-database-per-site mode (`velora init`, `new-site`) is still supported; see `docs/multicompany.md`.

## Which computers
Python 3.10+ and (for a server) PostgreSQL 13+. Ubuntu 22.04, 24.04, 26.04 and Debian 12/13 work as they are; Ubuntu 20.04 and Debian 11 work too (the installer brings a private
Python and the official PostgreSQL repository); Ubuntu 18.04 is end of life, so use `bash install-dev.sh` for development only. See `docs/compatibility.md`.

Develop the framework itself:
```bash
pip install -e ".[postgres,dev]" && pip install -e apps/velora_demo
pytest                                   # SQLite;  VELORA_TEST_PG_URL=... VELORA_TEST_PG_ROOT_PASSWORD=... pytest  adds PostgreSQL
cd frontend && npm install && npm test   # 70 tests;  npm run dev  (proxies /api to :8000)
sh scripts/build-desk.sh                 # rebuild the Desk into velora/desk before building a wheel
```
Single-site library mode still works: `velora.init()` with `VELORA_DB_URL` / `VELORA_APPS` / `VELORA_DEVELOPER_MODE`.

## Financial engine (legacy app)
`apps/velora_accounts`: an immutable double-entry ledger with **Receipts, Payments, General Journal and Journal Voucher** (no Payment Entry / Journal Entry), WHT, gateway-safe receipts, period locking and a Trial Balance. See `docs/accounting.md`.

## VeloraERP (integrated accounting and business core)
`apps/velora_erp` is independently released and owns its Account Ledger Record. On Velora 0.85.0+, the Financial Report Designer and statement drill-down can consume that ledger through the installed-app financial reporting provider contract. VeloraERP's Finance workspace, Trial Balance, Account Ledger, Income Statement and Statement of Financial Position are integrated into the native Desk. See `docs/financial-reporting-provider.md` and `apps/velora_erp/README.md`.

## Accounts (financial engine)
`apps/velora_accounts`: immutable double-entry ledger, **Receipts / Payments / General Journal** (no Payment Entry or Journal Entry), Journal Voucher, and three batch documents
(Batch Bank Transaction, Expense Batch, Bank Transaction Processor) with Excel import, duplicate protection, statement proof and amortisation, plus Customer/Supplier masters, Sales/Purchase Invoices settled per invoice, and General Ledger / aged reports. See `docs/accounts.md` (including what is not built yet).

## Designer, grids and DocType Creator
A drag-and-drop **form layout designer** (12-column rows, widths, sections, tabs; phone-friendly), **Frappe-style child-table grids** (any number of fields per row, configurable columns, row reordering) and a **DocType Creator** that accepts Velora JSON *or a Frappe DocType export*. See `docs/designer.md`.

## Install, update, add and remove: one command each
```bash
sudo bash install.sh --email you@co.com     # everything: PostgreSQL, service, first company, notifications + search
sudo velora update                          # new code + packages + backup + upgrade every company + restart (undoes itself on failure)
sudo velora install-app <name|git URL|folder>   # fetch, packages, install on every company, restart
sudo velora uninstall-app <name>            # back up, remove from every company (data kept)
sudo bash uninstall.sh                      # remove the server (your data is kept unless --purge)
```
After an install or update the Desk opens a **welcome page** that explains what just happened, and `/tutorial` is a full, offline, printable HTML tutorial. Give a company its own address with `sudo velora domain add erp.acme.com COMP-001`.

Details and honest limits: `docs/lifecycle.md`.

## Enterprise settings governance
Velora 0.85.0 adds a reusable, company-local settings governance engine: typed catalogue definitions, explicit scope, effective dates, maker-checker and critical dual approval, immutable versions, audit history and checksum-verified configuration packages. Package imports are staged as Draft changes and cannot publish automatically. See `docs/settings-governance.md`.

## Notifications, worker and optional packages
A bundled **notification system** (`velora_notify`: rules, safe conditions and templates, in-app/email/webhook channels, an outbox with retries, quiet hours, digests, escalation), a **scheduler and `velora worker`**, and **optional extras** (`pip install "velora[all]"`, `velora deps`). See `docs/notifications.md` and `docs/extras.md`.

## PostgreSQL
On PostgreSQL the **database enforces the ledger** (entries can never be edited or deleted, vouchers must balance, no overlapping fiscal years, via triggers and constraints), reports gain true subtotals (`ROLLUP`), medians/percentiles, per-measure filters and gap-filled time series, and `velora pg status` advises on the server (PITR, extensions, slow-query tracking). See `docs/postgresql.md`.

## Moving data in and out
Any DocType's data can be imported from Excel, CSV or JSON and exported again in the same layout: `velora import-template`, `velora import-data DOCTYPE FILE --dry-run` (checks with the real validation and saves nothing), `velora export-data`. In the Desk: **Import** on any list. See `docs/data-import.md`.

## Which computers
Python 3.10+ and (for a server) PostgreSQL 13+. Ubuntu 22.04, 24.04, 26.04 and Debian 12/13 work as they are; Ubuntu 20.04 and Debian 11 work too (the installer brings a private Python and the official PostgreSQL repository); Ubuntu 18.04 is end of life, so use `bash install-dev.sh` for development only. See `docs/compatibility.md`.

## Install and upgrade
```bash
pip install velora && velora quickstart          # one command to a running, signed-in system
velora doctor                                    # check an installation
velora update --check                            # exit code 10 = updates available
velora update                                    # new code (git / pip) + data upgrade; rolls everything back on failure
velora upgrade                                   # data upgrade only (after an image swap / manual pip upgrade)
```
Everything about updates, patches, rollback and hosting recipes: `docs/upgrading.md`.

## Theme and reports
```bash
velora --company COMP-001 doctypes                          # reports live in <app>/<module>/report/<name>/ (JSON, + .py for script reports)
curl .../api/theme                                           # compiled tokens, CSS, WCAG audit, Excel palette
curl -X POST .../api/report/Sales%20by%20Customer%20Group/export -d '{"filters":{"from_date":"2026-01-01"}}' > report.xlsx
```
Desk: **Reports** in the sidebar (plus **＋ New report** - the report builder - and **My reports**), **Settings → Theme** for System Managers (preset gallery, brand colour, density, corners, font, live light/dark preview, contrast audit),
**Appearance** menu for personal light/dark and density. Full details: `docs/theme-and-reports.md`.

## Platform mode: sign-in once, many companies, one database each
```bash
velora platform init --admin-email you@corp.com                      # control plane (SQLite for dev; --db-root-password ... for PostgreSQL)
velora tenant create "Enterprise Group"
velora company create "Velora Technologies" --tenant TEN-001 --apps accounting --db-root-password ...   # creates role + database, installs apps
velora user create alice@corp.com --name Alice
velora user grant alice@corp.com COMP-001 --roles "System Manager"
velora user grant alice@corp.com COMP-002 --roles "Sales User"       # different role in another company
velora start                                                        # sign-in required; Desk shows the ACTIVE COMPANY switcher
velora --company COMP-001 install-app inventory | doctypes | backup  # operate on one company
velora migrate --all-companies                                       # roll a framework upgrade through every company database
velora platform audit | status ; velora company list | suspend | activate | drop
```
Company credentials are never stored in the registry (encrypted `secret_ref`); every request re-validates the user's access; the company is chosen per browser tab; roles are per company. See `docs/multicompany.md`.

## Frontend engine (`frontend/`)
Look and feel follows an enterprise (Fluent/D365-style) design system: ribbon action bars with icon buttons, dense grids with a check column and
highlighted selection, switch toggles for Check fields, collapsible form sections, column group headings, red-outlined required fields, light/dark themes.

**Form** (`FormView`): renders from `/api/meta/{doctype}`; tabs, collapsible sections, column headings (a Column Break's label), every field type, Link autocomplete,
child-table grid (+ New / Delete selected), Save / Submit / Cancel / Delete gated by the caller's permissions, optimistic locking, server errors shown verbatim.

**Report-view grid** (Frappe v16 / D365-style): scrollable with any number of columns; **Insert columns** dialog (search, tick, reorder; new columns land right after the one you clicked);
right-click or chevron menu per header (sort A→Z / Z→A, insert columns, remove, pin, reset width); drag a header edge to **resize**; **pinned (sticky) columns**; a **Totals** row summed server-side over *all* matching rows;
**Copy to clipboard** of selected rows as Excel-pasteable text.

**List view** (`ListView`) - the Frappe feature set:
- **Filters**: inline *standard filters* (`in_standard_filter` in the DocType JSON), an advanced **filter builder** (field / condition / value, typed per field; contains, not contains, equals, is one of, >, <, between, is set / not set), removable filter chips, title-field search, URL filters (`#/app/Sales Order?customer=CUST-0001`).
- **Sort** by header click (asc → desc → default) or the Sort menu; **Columns** picker (show / hide / reorder / reset); **rows-per-page** (20/50/100/500) with counts and paging.
- **Group-by sidebar** with live counts per value (Select/Link/Check, Status, Created By); click to filter.
- **Saved views** (filters + columns + sort, per user and DocType, stored in the browser) and remembered column / sort / page-size preferences.
- **Selection**: row checkboxes, shift-click ranges, select page, "select all N" across pages; **bulk actions**: Delete, Submit, Cancel, Edit field value - each document in its own transaction, with a per-record failure report (failed rows stay selected).
- **List scripts**: `velora.listview_settings[dt] = { add_fields, get_indicator(doc) }`.

**Excel export** (server-side, `POST /api/export/{doctype}`; button + "Export selected…"):
| Choice | Options |
|---|---|
| Columns | **Current view** - exactly the visible columns, in order · **All fields** - every field + system fields, and **each child table on its own sheet** keyed to its parent |
| Rows | Selected rows · all rows matching the current filters (up to 50,000) · this page only |
| Headers | Friendly labels · field names (best for re-import) |

Real Excel types (numbers, dates, number formats), styled header, frozen top row, auto-filter, auto column widths, plus an *Export info* sheet (filters, row count, who/when).
Safeguards: needs the DocType's **`export` permission** (separate from `read`), text is always written as text (no formula injection), 50,000-row cap, and every export is recorded in `velora_export_log`.

**Client scripts**: `<doctype>.js` / `<doctype>_list.js` next to the DocType JSON, served by the backend and run with only the `velora` object:
`velora.ui.form.on("Customer", { refresh(frm){}, <fieldname>(frm){}, validate(frm){} })`; `frm.doc`, `set_value`, `add_button`, `set_intro`,
`set_read_only`, `toggle_hidden`, `is_new`; `velora.msgprint`, `velora.navigate`. Scripts are trusted app code, never database-stored.

**API**: `GET /api/doctypes`, `/api/meta/{dt}` (incl. caller's permissions), `/api/count/{dt}`, `/api/group_by/{dt}?field=`, `/api/client_script/{dt}`,
`POST /api/export/{dt}`, `POST /api/bulk/{dt}`; filter operators `= != > < >= <= like, not like, in, not in, between, is set/not set` with typed (date/number) coercion on both databases.

## App layout (auto-discovered from VELORA_APPS)
```
<app>/<module>/doctype/<name>/<name>.json   metadata (source of truth)
<app>/<module>/doctype/<name>/<name>.py     controller: class PascalName(Document)
<app>/hooks.py                              doc_events = {"Customer": {"validate": "pkg.mod.fn"}, "*": {...}}
```

## DocType JSON spec (v1)
| Key | Meaning |
|---|---|
| `name`, `module` | identity |
| `autoname` | omitted/`hash` · `prompt` · `field:<fieldname>` · `series:PREFIX-.####` |
| `istable` | child table (rows live in own table, linked by parent/parenttype/parentfield/idx) |
| `is_submittable` | enables docstatus 0 → 1 → 2 (draft / submitted / cancelled) |
| `track_changes` | writes field-level audit rows to `velora_version` |
| `title_field`, `sort_field`, `sort_order` | UI hints |
| `permissions[]` | `{role, read, write, create, delete, submit, cancel, export}` |
| `fields[]` | `fieldname, fieldtype, label, options, required, unique, default, read_only, hidden, in_list_view, in_standard_filter, length` |

Field types: `Data Text Int Float Currency Check Date Datetime Select Link JSON Table` + layout
`Section Break · Column Break · Tab Break`. `Select.options` is a list; `default` accepts `"Today"`/`"Now"`.
System columns on every table: `name owner creation modified modified_by docstatus idx`.
Validation reports *all* metadata errors at once and cross-checks Link/Table targets at load time.

## Lifecycle contract (one DB transaction; any exception rolls everything back)
```
insert : perm(create) → defaults+coercion → before_insert → naming → before_validate → validate → before_save
         → field checks → DB write → after_insert → on_update → after_save
save   : perm(write) → row lock + optimistic-lock check → … same as insert, no naming/after_insert … → track_changes
submit : perm(submit) → lock → docstatus=1 → before_validate → validate → before_submit → checks → write → on_update → on_submit → after_save
cancel : perm(cancel) → lock → docstatus=2 → before_cancel → write → on_update → on_cancel → after_save
delete : perm(delete) → before_delete → link-integrity check → delete → after_delete
```
Controller method runs first, then app `doc_events` handlers. (The earlier draft's `on_trash` was dropped as a duplicate of `before_delete`.)

## Decisions made in this slice (and why)
- **PostgreSQL first, Oracle later.** SQLAlchemy *Core* only (no ORM, no Alembic for DocTypes). Identifiers are capped at 63 chars
  with a hash suffix, and empty strings are normalised to NULL, so an Oracle adapter will behave the same.
- **Schema sync is additive.** It creates tables/columns/indexes; it never drops or retypes anything automatically.
- **Controllers are trusted code** from installed packages, never evaluated from database content.
- **Permissions are enforced in the Document engine**, so no route can bypass them. Trusted scripts/CLI run as Administrator; the API always sets a per-request session.
- **Series numbers are gap-free and concurrency-safe** (row-locked counter in the same transaction as the insert).
- **Optimistic locking**: clients send back `modified`; a stale write returns 409.

## Frappe v16 list/report parity (from Frappe's public v16 / v16.50 announcements; I found no notes for "16.73")
| Frappe v16 feature | Velora |
|---|---|
| Scrollable list, unlimited columns, resizable columns | Done |
| Sticky columns (report view) | Done for the list/report grid; **not yet for child tables** |
| Saved filters / list layouts | Done as *Saved views* (filters + columns + sort), stored in the browser |
| Copy selected rows to clipboard | Done |
| Quick filters customisable per user | Partial: standard filters come from the DocType JSON; no per-user customisation yet |
| Total row | Done (server-side) |
| Role-based field masking, custom permission types | Not built (export is the only extra permission type) |
| Custom print formats for reports, background report download | Not built (synchronous Excel export only) |
| Kanban / Calendar / Gantt / Map / Image / Dashboard views | Not built |
| Better data import, DocType Settings page, assign/tags/comments/likes | Not built |
| Right sidebar | Frappe v16 *removed* it; Velora keeps the (toggleable) group-by sidebar |

## Known limits / next work (in order)
0. Not yet built from the platform plan: marketplace, Velora Cloud signup/billing, website builder, print designer, workflow, report builder, scheduler/background jobs, group consolidation engine.
1. Authentication exists in platform mode; still missing: MFA/SSO, password-reset email, per-IP rate limiting, a per-request session cache, row-level and field-level permissions (incl. Frappe-style field masking), and an admin UI (the control plane is CLI-only).
2. Type-change and column-removal policy in schema sync (currently only reports additions); metadata cache invalidation.
3. Per-company customization beyond the theme: Custom Field / Property Setter layer, per-company workflows, print formats; patches (`patches.txt`) and fixtures.
4. Workflow engine, job queue (RQ/Arq), notifications, PDF/CSV report export, scheduled/emailed reports, charts, print/PDF (WeasyPrint).
5. Financial engine (immutable GL, period locking) - the prerequisite for group consolidation.
6. Child-row changes are not yet included in `track_changes`; `allow_on_submit` fields not yet supported.
7. UI gaps: no Dynamic Link/Attach/Signature/rich-text fields yet; list has no report builder, dashboards, Kanban/Calendar, import, or CSV/PDF export; sticky columns do not yet apply to child tables;
   saved views and column preferences live in the browser (not yet synced per user on the server); the child grid is a plain editable table (swap in AG Grid when needed);
   Datetime shows server UTC as-is (no timezone conversion).
8. **Not yet seen in a real browser.** The UI is covered by jsdom tests, a production build and an end-to-end run against PostgreSQL, but the sandbox had no browser, so
   the Desk's visual design (spacing, colours, dark mode, sticky/resizable columns, theme page, report viewer) has not been eyeballed; only the Excel output was rendered and viewed. Expect to tweak CSS after the first real look.


## Developer Studio (v0.20)

The Developer Studio provides a read-only application catalogue, DocType metadata inspector, generic REST endpoint explorer, and visibility into installed-app document hooks, background job handlers, scheduler declarations, and database-object declarations. It requires Developer Mode and System Manager access. It does not execute code from the inspection screen or expose database credentials.

The generic DocType REST API and installed-app hooks remain the supported programmatic extension points. Company-specific Custom Fields and Property Setters are not yet exposed as operational metadata extensions; they require a dedicated schema and document-persistence design before they can be safely enabled.


## Application packaging (v0.24)

```bash
velora validate-app my_app
velora export-app my_app --output dist/my_app.zip
# On another workspace:
velora import-app-package dist/my_app.zip
velora validate-app my_app
velora --site company.local install-app my_app
```

Exported app archives contain a SHA-256 manifest. Import validates archive paths and
file hashes, then adds source to the workspace; it does **not** install the app on
a company database. App installation remains a separate, explicit operation.

## v0.26 Enterprise Application Administration

See `docs/v0_26.md` and `velora/static/tutorial-v0.26.html`. This release added tenant-scoped application catalog primitives; they were never wired into the application and were removed later (see `docs/v0_26.md`).

## Tenant security boundary (v0.28)
Authenticated platform requests now pass through `velora.tenant_security.resolve_tenant_company()` before the selected company database is bound. The boundary rechecks company membership, tenant/company active status and optional tenant pinning, then returns an immutable tenant/company/roles context. See `docs/tenant-security-v028.md`. Existing authenticator-app TOTP remains available; OIDC/SAML and passkeys are not part of this release.

## v0.11.0 additions

Sales Return and Purchase Return provide controlled invoice-linked financial reversals. Landed Cost Voucher provides validated allocation calculations; valuation posting is deferred until inventory valuation is implemented. See `velora_erp/docs/RETURNS-LANDED-COST-v0.11.0.md`.
