# Changelog

History before this repository was started is archived outside it. Each release has its own `RELEASE-NOTES-*` file at the project root.

## 1.19.2 / ERP 2.106.1 (2026-11-28)
- Framework: Company Administration review. Creating or duplicating a company with VeloraERP works (apps that need each other are installed together); Duplicate copies tick-box setup sections; a failed duplicate removes the half-made company; Grant access checks roles per company and no longer pre-fills System Manager. Copy setup and Data Import read scripts, automations, workflow definitions and permissions once per DocType (12.2 s to 3.4 s for 704 records).
- ERP: wheel includes the sample print formats.

## 1.19.1 / ERP 2.106.0 (2026-11-28)
- Framework: Update Centre fixed (no `python -m velora`; checks the wheels before maintenance; offline pip; no per-app reinstall and restarts; truthful stop message); ERP wheel now carries its print formats. Publish on top of GitHub (shows files added, changed and removed; adds one commit after the repository's history; no force-push); Install / Update from GitHub for app profiles (clone or fast-forward with the saved token, install in the profile's company, packages, restart; refuses when the server copy has changes or the histories differ); profiles for apps that are only on GitHub so far.

## 1.19.0 / ERP 2.106.0 (2026-11-28)
- Framework: errors that help (advice with hint, links and field on every refusal; app rules via `error_advice`); `velora.warn()` notes that never block; built-in `workflow_state` on every submittable DocType; People & Access API (one-step add with checked roles, change, remove; company System Manager may manage their own company); fixed platform role grants and removals that did not reach the company database.
- Desk: People & Access page; Quick approval row in the simple workflow designer, which no longer picks a business status as the approval field; error box with How to fix it, buttons and Go to the field; notes shown as dismissible messages.
- ERP: advice rules for the common finance refusals; access profiles (Accountant, Finance Manager, Auditor, Sales, Purchasing, Store and inventory, HR, Payroll, Projects, Support desk, Employee); stale exchange rate is a note, a missing one is refused with a link; the five sample workflows that needed Customize Form now use the built-in Workflow State.

## 1.18.0 / ERP 2.105.0 (2026-11-28)
- ERP: actions from a Fixed Asset (Revalue, Dispose, Impairment Test, Transfer, Adjust Component) that open the action document pre-filled and unsaved; disposal and revaluation require depreciation to be up to date (IAS 16); foreign-currency entries whose lines round separately post the cent difference to a new Exchange Rounding Account (they were refused before); Create From flows routed through one table instead of six stacked versions; attendance and SLA time zones no longer assume Lagos; deprecated utcnow calls replaced.
- Admin: Service Feedback can be read by System Manager and Administration Manager (it had no permissions).
- Governance: Sustainability Report Publication and Export Template had no permissions (the workspace shortcut opened nothing); they now follow Sustainability Report.
- Framework: Create From may answer with an unsaved pre-filled form; workflow provider failures are logged.

## 1.17.9 / ERP 2.104.0 (2026-11-28)
- ERP: module audit and standardisation. Realised exchange differences on foreign settlements (IAS 21.28) fixed; no hard-coded currency (the base currency comes from the installation); period-end Foreign Currency Revaluation (IAS 21.23) with automatic reversal; Expected Credit Loss Assessment (IFRS 9); Provision Entry (IAS 37); new account types Loss Allowance and Provision; six sample approval workflows (offered, installed switched off on request) for Stock Entry, Purchase Receipt, Delivery Note, Sales Order, Purchase Order and Salary Slip; Treasury wording made currency-neutral.
- Framework: no code change; packaged with ERP 2.104.0 (tutorial version updated).

## 1.17.8 / ERP 2.103.0 (2026-11-28)
- ERP: Debt & Treasury: lenders, facilities, drawdowns with repayment schedules, interest accrual, repayments with withholding tax on interest, facility amendments that reprice floating loans, covenant tests, 12 reports, adviser and AI advisor, daily refresh job.
- Desk: Debt & Treasury hub and Treasury Centre (debt position, maturity ladder, headroom, cash runway, covenants, lenders, currency exposure).
- Docs: VeloraERP user manual rewritten for 2.103.0 (Tax Management, Debt & Treasury, hubs and centres, honest test status).

## 1.17.7 / ERP 2.102.0 (2026-11-28)
- ERP: Tax Report Library cleaned up: 60 duplicate or misleading names removed (125 distinct reports remain); the catalogue lists only reports that run; fixed a division by zero on empty books; every report tested on empty books and with every filter.

## 1.17.6 / ERP 2.101.0 (2026-11-28)
- ERP: Tax Report Library, one report running 185 tax reports (VAT, WHT, income tax, deferred tax, compliance, liabilities, credits, analytics, data quality, audit trail, executive summary); catalogue status now shows 203 of 460 runnable and the rest as specification only.
- Desk: Report Library panel in the Tax Centre.

## 1.17.5 / ERP 2.100.0 (2026-11-27)
- ERP: Tax Journal (customer and supplier withholding tax, settles invoices, reverses on cancel); Account tax treatment; Income Tax Computation (ledger profit, add-backs, losses, levies, minimum tax, WHT credits); Tax Adviser and two AI advisors; four reports; Tax Settings defaults.
- ERP: Tax Journal rows for dividends, interest and other income received or paid; federal/state level; automatic WHT/VAT deadlines, penalty exposure, reminders; WHT All Sources report; investment WHT tagged with a rule code; sample Receipt, Official Receipt and Payment Voucher print formats.
- Framework: amount in words in print formats; fixed Tax routes that broke the OpenAPI document and the tax catalogue file that broke a metadata test (both from 1.17.4).
- Desk: Tax Centre screen and hub entries.

## 1.17.4 / ERP 2.99.0 (2026-11-27)
- ERP: Tax Management module (rules, ledger read from the GL, returns, obligations, reports, hub); invoice lines follow approved tax codes. Review of the supplied tax package in TAX-MANAGEMENT-REVIEW.md. Payroll tax unchanged.

## 1.17.3 / Governance 11.12.0 (2026-11-27)
- Governance: NCCG 2018 recommended practices (342 paraphrased practices under the 28 principles) answered per assessment; SASB industry-metric structure with Excel template and import (no licensed content shipped), adoption and responses linked to the IFRS S2.32 line; Inline XBRL now carries data-point figures and report-section narrative; desk screens for IFRS S1/S2 readiness, code assessment and SASB metrics.
- Framework: registry proxy refuses attribute patching (a leaked test patch caused the "DocType 'Customer' does not exist" cascade in full-suite runs); two tests fixed to patch the Registry class.

## 1.17.2 / Governance 11.11.0 (2026-11-27)
- Governance: ERP spend-based emissions feed, IFRS S1/S2 requirement checklist, structured double materiality, climate scenario analysis, climate target detail, Inline XBRL export engine.
- Desk: hub routing for the new doctypes.

## 1.17.1 / Governance 11.10.0 (2026-11-27)
- Governance: GHG accounting by gas with GWP sets, Scope 2 both methods, Scope 3 categories, inventory roll-up; assurance controls with period locking; NCCG 2018 apply-and-explain assessment.
- Framework: child rows added during validate are now linked and saved.

## 1.17.0 / VeloraERP 2.98.0 (2026-11-27)
- Fix: Purchase Invoice from a Purchase Receipt lost the UOM conversion factor and rate, leaving a balance on Stock Received But Not Billed.
- Print formats designed in Frappe/Jinja now render (sandboxed Jinja2); PDF keeps tables.
- Header warehouse fills item lines; batch picker by item/warehouse (first expiry, then first received); "+" opens a new tab; email to many recipients with a message; Preview Entry.

## Velora 1.16.4
- Fix: `velora install-app <name>` now works for an app added with pip (for example velora_admin). See `RELEASE-NOTES-v1.16.4.md`.

## Velora 1.16.3
- Fix: opening a how-to guide gave an internal server error on a multi-company server. See `RELEASE-NOTES-v1.16.3.md`.

## Velora 1.16.2 / VeloraERP 2.95.4 / ProjectOne 2.25.2 / Velora Admin 1.9.2
- A how-to guide for every application, opened from the App Hub and the Welcome page (`/guide/<app>`), each with a welcome introduction; new Velora Admin guide.
- Simple and weighted average purchase cost as separate pricing methods; Explain Pricing now tells the story of how a price was reached.
- See `RELEASE-NOTES-v1.16.2.md`, `RELEASE-NOTES-VELORAERP-v2.95.4.md`, `RELEASE-NOTES-PROJECTONE-v2.25.2.md`, `RELEASE-NOTES-ADMIN-v1.9.2.md`.

## VeloraERP 2.95.3 (Velora 1.16.1, ProjectOne 2.25.1, Velora Admin 1.9.1)
- Cost Used for Pricing policy (last, average of last 3-5, FIFO, highest) at Settings / Item Group / Item level, and a Minimum Profit % floor. See `RELEASE-NOTES-VELORAERP-v2.95.3.md`.

## VeloraERP 2.95.2 (Velora 1.16.1, ProjectOne 2.25.1, Velora Admin 1.9.1)
- Pay basis policy: Fixed Monthly or Attendance Based by company default, staff category or employee; attendance days feed Payroll Preparation. See `RELEASE-NOTES-VELORAERP-v2.95.2.md`.

## Velora 1.16.1 / VeloraERP 2.95.1 / ProjectOne 2.25.1 / Velora Admin 1.9.1
- Payroll Automation Settings, Employee Rent Declaration (rent relief into PAYE), Payroll Preparation (profiles, assignments, draft run, attention list).
- Faster link lookups; styled dialogs replace browser pop-ups.
- See `RELEASE-NOTES-v1.16.1.md`, `RELEASE-NOTES-VELORAERP-v2.95.1.md`, `RELEASE-NOTES-PROJECTONE-v2.25.1.md`.

## Velora 1.16.0 / VeloraERP 2.95.0 / ProjectOne 2.25.0 / Velora Admin 1.9.0
- App Hub; merged Projects sidebar; faster link search; modern dialogs; Velora Admin without the "Administrative" prefix.
- Payment/Receipt single line; Purchase Receipt policy per item; non-stock item form; reports from records; asset repairs report; document signing.
- Reports: row search, fitted columns, dd/mm/yyyy, redesigned Excel export; print opens with the right company.
- See `RELEASE-NOTES-v1.16.0.md`, `RELEASE-NOTES-VELORAERP-v2.95.0.md`, `RELEASE-NOTES-PROJECTONE-v2.25.0.md`.

## Velora 1.15.5 / VeloraERP 2.94.1 / ProjectOne 2.24.1
- Apps that require each other (VeloraERP, ProjectOne) install together; `velora upgrade` installs a required app a site lacks (fixes "Link target 'Project' is not a DocType").
- Server Console: framework and app folders, file edit/paste/copy with history, database browser, SQL with preview, stuck-document repair; password unlock, audited.
- Date & Number Format per company.
- Project field on Purchase Order, Sales Order, Stock Entry, Fixed Asset; ProjectOne forecast cost and all six sources connected.
- See `RELEASE-NOTES-v1.15.5.md`, `RELEASE-NOTES-VELORAERP-v2.94.1.md`, `RELEASE-NOTES-PROJECTONE-v2.24.1.md`.

## Velora 1.15.3 / VeloraERP 2.93.0 / ProjectOne 2.23.0
- One Project record (ProjectOne's); VeloraERP links to it. No doctype carries a company field.
- ProjectOne installs and runs on a real site beside VeloraERP: controllers, Velora binding, permissions, mobile fixes.
- ERPNext-style permission rows on every DocType.
- Link search for roles that fill but cannot list a master; currency boxes show money as money; Employee Name with LAST NAME in capitals.
- Existing Finance projects are carried into ProjectOne by an upgrade patch; programme intelligence and corrective actions run on real records.
- One guide per audience: VeloraERP User Manual, ProjectOne Guide, and the framework manual for administrators and developers.
- See earlier notes in the repository history.


## Velora 1.15.1 / VeloraERP 2.91.0 / ProjectOne 2.21.1
- Gross Pay on the Employee, shown (never calculated from) on the Salary Structure Assignment.
- Menu search; HR & People and Applications regrouped; sidebar restyled; Create menu on forms.
- ProjectOne field types fixed; five blockers to installing it are listed in its notes.
- Link search, Role & Field Permissions, report column resizing, GUI-only workflows (1.15.0 / 2.90.0).
- See `RELEASE-NOTES-v1.15.1.md`, `RELEASE-NOTES-VELORAERP-v2.91.0.md`, `RELEASE-NOTES-PROJECTONE-v2.21.1.md`.

## Velora 1.13.0 / VeloraERP 2.89.0
- Cancel works like ERPNext for every document: the posting is deleted, dependants are unlinked or named, amend or duplicate to repost.
- Reversal-style correction removed (Reversal event, `reverse_financial_posting`, Account Correction).
- See `RELEASE-NOTES-v1.13.0.md` and `RELEASE-NOTES-VELORAERP-v2.89.0.md`.
