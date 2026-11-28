# Velora 1.19.2: Company Administration review

## Fixed
- **Create company (and Duplicate) with VeloraERP failed.** Apps were installed in the order given, and VeloraERP and ProjectOne need each other, so either order stopped with "requires ... install it first". Company creation now installs dependencies first and apps that need each other together, exactly as `velora install-app` does.
- **Duplicate company** asked for DocType names typed in dependency order. It now offers the same tick-box setup sections as Copy setup (chart of accounts, finance, inventory, payroll, HR and support masters, workflows, permissions, finance policy), copied parents first. The typed list is still there under Advanced.
- **A duplicate whose copy failed left a half-made company behind** (status failed, database kept). The new company is now removed again; if it cannot be removed it stays marked failed.
- **Grant access** pre-filled "System Manager" for every company ticked, and accepted any role text. Roles are now checked in each company (with "did you mean ..." for a typo) before anything is granted, the person must exist, and nothing is pre-filled.

## Faster
- Copying setup into a company: **12.2 s to 3.4 s** for 704 records (600 accounts, 100 cost centres, 4 groups) on SQLite, measured on the same data. Each copied record used to look up server scripts, automations and workflow definitions about 7 times (once per document event), some 10,000 queries that found nothing. Inside a bulk copy or a Data Import these are now read once per document type (roles and permissions too). Single saves outside an import are unchanged.
- The same applies to every **Data Import**.

Measured, not changed: creating a company with VeloraERP takes about 5 s on SQLite, most of it creating some 450 tables.
