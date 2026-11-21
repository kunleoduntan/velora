<!-- Generated from velora/layout.py by `velora layout --write-docs`. Do not edit by hand: a test fails if this file differs from the generated text. -->
# The Velora file structure

A Velora installation is **one folder**, called a *workspace*. It has six places, each with one job:

```
my-erp/
  apps/       # code
  config/     # settings
  platform/   # system
  files/      # uploads
  backups/    # backups
  logs/       # logs
```

| Place | What it is | What is in it | Who can read it | In `velora ops backup` |
|---|---|---|---|---|
| `apps/` | code | Your apps and every app you install: one folder per app. This is the only part you write, edit or keep in version control. | normal | yes |
| `config/` | settings | Settings for the whole installation: apps.txt (the apps that are switched on), common.json (installation settings) and lifecycle.json (a plain-language history of installs and updates). | owner only | yes |
| `platform/` | system | The system itself: control.db (sign-in, people, companies and what they may do), master.key (encrypts the passwords Velora stores: keep it safe and never share it) and companies/ (one database file per SQLite company). Do not edit these by hand. | owner only | yes |
| `files/` | uploads | Everything people attached to documents, in one folder per company, kept apart so one company can never see another's. | owner only | yes |
| `backups/` | backups | Encrypted workspace backups (`velora ops backup`) and the safety copy taken before every update. | owner only | no |
| `logs/` | logs | Logs, and evidence such as restore rehearsals. | owner only | no |
| `sites/` | legacy | Only for the older one-database-per-site mode (`velora new-site`). New installations do not have this folder. | owner only | yes |

## Making one
One command creates the whole thing, with a first company and an administrator, and starts it:

```
velora quickstart my-erp --email you@company.com
```

After that, `velora start` (inside the folder) runs it. Starting also upgrades anything that needs upgrading and repairs permissions, so there is nothing else to remember.

## Moving, copying and restoring
The folder is **relocatable**: nothing inside it records where the folder is. You can rename it, move it to another disk or server, copy it, or restore a backup into a new folder, and it opens its own data.
* Backup: `velora ops backup` writes one encrypted file containing `apps, config, platform, files, sites`. If your uploaded files are very large they are left out and the backup **says so**; back `files/` up with your usual file backup.
* Restore on a machine that has nothing: `velora ops restore-workspace BACKUP --into NEWFOLDER`. It never overwrites an existing folder.
* PostgreSQL companies keep their data in PostgreSQL, not in this folder. Back those up with `velora backup` (they are not in the workspace backup).

## What belongs in version control
Only `apps/` (your code). The generated `.gitignore` ignores everything else, including any folder added later, so `git add .` can never publish `platform/master.key` or a database.

## Permissions
Everything except `apps/` is readable only by the user that runs Velora (`700` for folders, `600` for databases, keys and uploads). `velora start` repairs this each time, and `velora layout --fix` does it on demand.

## Older installations
Versions before this layout kept three settings files in `sites/`. They are moved once, automatically, the first time the workspace is started or upgraded (nothing is copied or left behind):

| Was | Now |
|---|---|
| `sites/apps.txt` | `config/apps.txt` |
| `sites/common_site_config.json` | `config/common.json` |
| `sites/lifecycle_log.json` | `config/lifecycle.json` |

Uploads kept in `company_files/` are renamed to `files/`. SQLite company databases recorded with an absolute path are made relative. Everything keeps working while that is pending.

## Seeing it
```
velora layout          the structure with real sizes, and anything that needs attention
velora layout --fix    apply the repairs (moves, permissions, README and .gitignore)
```
