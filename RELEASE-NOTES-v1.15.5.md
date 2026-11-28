# Velora Framework 1.15.5

## New: Server Console (Company Administration, platform administrators only)
- **Files.** Browse the framework and installed-app folders beside `apps`, `files`, `backups` and `logs`. Edit in place, paste over a file, upload, copy, rename, delete, download. Replaced or deleted files are kept in `backups/file-history` (newest 25 each) and can be restored. A `.py` file with a syntax error or a `.json` file that does not parse is refused.
- **Database.** Browse any table of a company; run SQL. Reads run in a read-only transaction. Changes are two steps, *Preview* (runs and rolls back, shows the rows affected) then *Apply* (only that exact statement, after an automatic company backup).
- **Stuck documents.** Mark cancelled, reopen as draft, or delete a document with its table rows, after typing its name to confirm.
- **Security.** Reading is open to platform administrators; changing code or data needs a password (and authenticator code) unlock lasting ten minutes, tied to that sign-in session, throttled after five failures. Paths are confined, symbolic links and secret-looking files refused, one statement at a time, statements reaching outside company data refused, everything audited. `VELORA_SERVER_CONSOLE=off` disables it.

## New: Date & Number Format (Settings)
Per company: dates as `2026-12-31`, `31/12/2026`, `12/31/2026`, `31-Dec-2026` or `31 Dec 2026`; numbers as `1,234.56`, `1.234,56`, `1 234,56` or `1'234.56`. Lists, reports and read-only values follow it.

## Fixed: apps that need each other
VeloraERP and ProjectOne require each other (the Project record lives in ProjectOne). Before, a site that had VeloraERP but not ProjectOne stopped with "Link target 'Project' is not a DocType", and a fresh install of either could not start.
- `install-app` installs apps that need each other together, in one validated step.
- `velora upgrade` (and the automatic upgrade at start) now installs any app that an installed app requires but the site lacks, before anything else; `--dry-run` lists it as a schema change.
- Until that upgrade has run, such a site loads empty instead of failing, so the upgrade can run.

## Replaces
The File Explorer is now the Files tab of the Server Console.

## Limits, stated plainly
- The browser's date picker in forms follows the browser's own setting.
- A schema change cannot be previewed on SQLite; statements beginning with WITH run only as reads.
- Stuck-document repair does not reverse postings or links made from the document.
- Code edits take effect after the service is restarted.
