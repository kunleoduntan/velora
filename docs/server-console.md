# Server Console

**Company Administration → Server Console** (platform administrators only). Three things in one place: the server's files, the database, and SQL.

## Unlocking
Reading is free. Changing framework or installed-app code, or changing data, asks for your password again (and your authenticator code if you use one). The unlock lasts ten minutes, is tied to that one sign-in session, and is signed with a key derived from the master key, so it works across server processes and cannot be forged or moved. Five wrong passwords block unlocking for ten minutes. Unlocks, failures, file edits and every SQL statement go to the audit log.

## Files
| Folder | Allowed |
|---|---|
| `apps`, `files` | read, edit, upload, copy, rename, delete |
| `backups`, `logs` | read, download, delete |
| `framework`, `installed` | read; edit, copy and upload need the unlock; no rename or delete |

* A `.py` file with a syntax error or a `.json` file that does not parse is refused.
* The previous version of any replaced or deleted file is kept in `backups/file-history` (newest 25 per file); **Earlier versions** restores one.
* After editing code, restart the service.
* Paths are confined to the folders above; `..`, absolute paths and symbolic links are refused; files that look like secrets are never listed or opened.

## Database and SQL
* **Browse** any table of a company (columns, key, 50 rows a page).
* **Run** reads inside a read-only transaction (15-second limit, 500 rows).
* **Change** data in two steps: *Preview* runs the statement and rolls it back, showing the rows it would affect; *Apply* runs only that exact statement (a signed plan ties them together), after an automatic backup of the company.
* One statement at a time. Statements that reach outside the company's data (attach, copy, extensions, roles, grants, server files and settings) are refused. A schema change cannot be previewed on SQLite.
* **Stuck document**: mark as cancelled, reopen as draft, or delete a document with its table rows. The document's name must be typed to confirm. Postings and links made from it are not reversed.

## Switching it off
`VELORA_SERVER_CONSOLE=off` in the service environment refuses every console action.

## Date and number format
Not part of the console: **Settings → Date & Number Format** chooses how each company shows dates (`2026-12-31`, `31/12/2026`, `12/31/2026`, `31-Dec-2026`, `31 Dec 2026`) and numbers (`1,234.56`, `1.234,56`, `1 234,56`, `1'234.56`).
