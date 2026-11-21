# File Explorer

**Company Administration → File Explorer** in the Desk (platform administrators only). It works like the file manager you would use on the server: browse folders, upload, edit text files, rename, delete and download.

## What you can reach

| Folder | See | Upload / create / edit | Delete |
|---|---|---|---|
| `apps` | yes | yes | yes |
| `files` | yes | yes | yes |
| `backups` | yes | no (download only) | yes |
| `logs` | yes | no (download only) | yes |

Nothing else in the workspace is reachable (not `config`, not `platform`, not the keys). Names that look like secrets (`.env*`, `*.key`, `*.pem`, anything with `password`, `secret`, `credential`) are not even listed.

## Using it
- **Upload:** the *Upload files* button, drag files onto the page, or paste files (Ctrl/Cmd+V) while the page is focused. An existing name asks before it is replaced.
- **Edit:** click a text file (up to 512 KB). *Save* is refused if someone changed the file after you opened it, so edits are never silently overwritten.
- **Delete:** always asks. Deleting a folder removes everything inside it.
- Works on a phone: the list collapses to name and actions.

## Safety (enforced on the server, not the screen)
Paths are confined to the folders above; `..`, absolute paths and symbolic links are refused; writes are atomic; uploads are limited to 100 MB; downloads are always sent as attachments. Every upload, edit, create, rename, delete and download is recorded in the audit log (`file.*`).

## PostgreSQL administrator login for creating companies
Creating or dropping a company from the Desk uses the server's PostgreSQL administrator login. The installer saves it, so nothing needs typing. To check or set it:

    velora pg admin
    velora pg admin-set --user velora_root --password-file /srv/velora/.db-root-password
