# Data import and export (any DocType)

Load data into any DocType from **Excel (.xlsx), CSV or JSON**, and export it again in the same layout, so data can be moved between companies and servers.

## In the Desk
Open a list and press **Import**.
1. **Template**: download an Excel or CSV template (right headings, required ones starred, an Instructions sheet), or bring your own file.
2. **Options**: create new / update existing / create-or-update; the order of day and month in dates; *submit after creating* (submittable DocTypes, if you may submit); *all or nothing*; *keep the IDs in the file* (migration; System Managers only).
3. **Check file** runs the real validation and **saves nothing**; **Import** saves. Problems are listed with the line, the column and the reason, and **Download the failed rows** gives a CSV (your columns plus an Error column) to correct and import again.

## The file
* Columns are matched by **label or fieldname**, ignoring case, spaces and the `*`, in **any order**. Unknown columns are ignored and listed.
* **ID** column: blank to create; filled to update. (On a plain insert the naming series decides the ID.)
* **Child tables**: headed `Table.Field`, for example `Items.Description`. A document's first child row sits on the document's own line; further rows go on the lines **under** it, with the document's own cells left blank.
* **Values**: dates as `2026-03-02`, `02/03/2026` (day first by default, or month first), `2 Mar 2026` or a real Excel date; numbers may contain thousands commas and currency signs, and `(100)` means -100; yes/no as `yes/no/1/0/true/false`; Select values are matched ignoring case; a Link must name an existing document (found by ID, then ignoring case, then by its title; an ambiguous title is refused).
* **Calculated (read-only) fields** are never imported: totals recompute themselves.
* **Empty cells never erase** existing data on update. Updating child-table columns **replaces** that table's rows.
* Submitted or cancelled documents cannot be updated.
* **JSON** is a list of objects (optionally inside `{"data": [...]}`), with child tables as nested lists. Exports use this shape.

## How it behaves
* Each document is saved on its own: one bad row never stops or half-applies the others. With *all or nothing*, the first failure undoes the whole import.
* **Check file** really runs the import and then rolls it back, so it reports exactly what the real import would do, including duplicates inside the file and your own validation rules, and it uses no naming-series numbers.
* Everything goes through the normal Document engine as the signed-in user: permissions, validation, naming, hooks, version history and notifications all apply. Importing needs *create* (and *write* to update, *submit* to submit); exporting needs *read* and *export*.
* Limits: 10 MB and 2,000 documents per upload in the Desk; the command line has no such limit (200,000 by default).
* Every import and export is recorded (who, what, how many) in the export log.

## From the command line
```
velora import-template "Sales Order" --format xlsx
velora import-data "Customer" customers.xlsx --dry-run          # check; saves nothing
velora import-data "Customer" customers.xlsx --report failed.csv   # import; failed rows to fix
velora import-data "Customer" changes.csv --mode update            # or --mode upsert, --match FIELD, --atomic, --submit, --date-format MDY
velora export-data "Customer" --format json --out customers.json   # also csv, xlsx; --filters '[["status","=","Active"]]'
```

## Moving a DocType's data to another company or server
1. On the source: `velora export-data "Customer" --out customers.json`.
2. On the destination (the DocType must exist, and anything it links to must be loaded first): `velora import-data "Customer" customers.json --keep-names --dry-run`, then again without `--dry-run`.

Load DocTypes in dependency order (a Customer Group before the Customers that link to it). Dates created/modified and owners are not carried over, and a submitted document arrives as a draft unless you add `--submit`.


## Company file attachments and migration packages (v0.10)

The standard per-DocType import/export remains unchanged. For multi-DocType migration, the package export endpoint accepts `include_attachments: true` to include files linked to the exported records. Attachments are included with SHA-256 checksums and imported only for records included in the package.

File storage is private and company-isolated. Configure `VELORA_FILE_ROOT` to a durable private volume in production. Velora appends a company-specific namespace when running in platform mode. Back up the company database and its corresponding file directory together.

See `docs/v0_10.md` for the file API, size limits and operational details.
