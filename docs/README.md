# Velora documentation

## Start here
* [Every command, with every option](commands.md): generated from the real command line, so it cannot be wrong
* [Installing and updating from your GitHub repository](install-from-github.md)
* [The file structure](file-structure.md): one folder, six places, what each is for, moving and restoring it (generated from `velora/layout.py`)
* [Install, update, add apps, uninstall](lifecycle.md): one command each
* [What Velora runs on](compatibility.md): Python, PostgreSQL and operating systems

## Run it
* [Hosting Velora](hosting.md), [Installing and upgrading](upgrading.md)
* [Disaster recovery](disaster-recovery.md): encrypted backups, restoring on a new machine, restore rehearsals
* [Using PostgreSQL properly](postgresql.md)
* [Database-per-company architecture](multicompany.md), [Tenant security boundary](tenant-security-v028.md), [Row-level security](row-security-v038.md)

## Build on it
* [Form designer, grids and the DocType Creator](designer.md)
* [Data import and export for any DocType](data-import.md)
* [Workflow, dashboards, printing and the public website](workflows-dashboards-website.md)
* [Background jobs and automation](jobs.md), [Notifications](notifications.md), [Integrations](integrations.md)
* [Server Script limits](server-scripts-limits.md), [Theme engine and reports](theme-and-reports.md), [Optional Python packages](extras.md)
* [Database connections](connections.md): the PostgreSQL connection budget and what to do when slots run out
* [Server Console](server-console.md): files, framework and app code, database browser, SQL and stuck-document repair, behind a password unlock
* [Publish to GitHub](publish-to-github.md): push apps and the project from the Desk
* [Conditional fields](conditional-fields.md): `depends_on` and friends, Frappe-compatible
* [Velora Accounts](accounts.md): the financial engine (cancel, amend, submit)

## Release history

Release history lives in the `RELEASE-NOTES-*` files at the project root (current framework and ERP only; older notes are kept outside this repository).
