# Disaster recovery

What to back up, how to restore it on a machine that has nothing, and how to **prove** the backups work. Everything here is a command; none of it needs a workspace to exist, because after a disaster there is only a backup file and a new server.

## The two kinds of backup
| What | Contains | Made by | Restored by |
|---|---|---|---|
| **Workspace snapshot** (`.vbackup`) | apps, `config/`, `platform/` (control plane, keys), every **SQLite** company database | `velora ops backup` | `velora ops restore-workspace` |
| **PostgreSQL company databases** | each company's data | `velora backup` / `pg_dump -Fc` | `velora restore` / `pg_restore` |

A PostgreSQL company's data is **not** inside the workspace snapshot: back it up separately, and rehearse it (below).

## Workspace snapshots
```
export VELORA_BACKUP_PASSWORD='a long passphrase'      # at least 12 characters; or you are asked
velora ops backup                                       # -> backups/workspace-<time>.vbackup (mode 600)
velora ops verify backups/workspace-....vbackup         # decrypts and checks it, on any machine
velora ops restore-workspace workspace-....vbackup --into /srv/velora-recovered
cd /srv/velora-recovered && velora doctor && velora start
```
* **Encrypted and tamper-evident.** The file is scrypt (N=2**17) + Fernet (AES + HMAC): a wrong password and a damaged file are indistinguishable, and any changed byte is detected. The key-derivation settings are stored in the file's header (bounded, so a crafted file cannot demand gigabytes of memory); backups made by earlier versions (N=2**14) still open.
* **Consistent databases.** Each SQLite database is captured with SQLite's own backup API (a consistent snapshot, including recent writes still in its write-ahead log), never by copying a file that may be mid-write. Logs, earlier backups, VCS metadata and `.env` files are excluded.
* **`verify` looks inside**: the archive must read end to end, contain `sites/`, and **every SQLite database in it must pass SQLite's `integrity_check`**.
* **`restore-workspace` is deliberately cautious.** It restores only into a **new or empty** directory (never over a live workspace), extracts only plain files and folders under the known top-level names (`apps`, `sites`, `config`, `platform`), and refuses a backup containing `..`, absolute paths, symbolic or hard links, devices, duplicate entries or a size beyond 32 GB, *before writing anything*. Keys and credentials come back owner-only whatever the archive said; setuid bits are never restored. If anything fails, nothing is left at the destination.
* **Limit:** the whole snapshot is held in memory while it is encrypted or decrypted (about three times its size).

## Rehearsing a PostgreSQL restore (and what the evidence means)
A backup you have never restored is a hope. A rehearsal restores a real dump into a disposable database, then **checks that every table the archive lists exists in the result**, then drops it:
```
velora ops postgres-rehearse /backups/company-A.dump           # uses VELORA_POSTGRES_REHEARSAL_URL or --database-url
velora ops recovery-assurance                                  # what the evidence says today
```
Needs `pg_restore`, `createdb`, `dropdb` and (for the verification) `psql`. Run it against a recovery-test server, not production: it creates and drops a database named `velora_rehearsal_<id>` there.

* **Failures are recorded too.** The log (`logs/recovery-rehearsals.jsonl`) keeps failed rehearsals as well as passed ones, so the report can say *failing*.
* **`assurance`** is one of: `none` (no passed rehearsal), `failing` (the latest one failed), `stale` (the last pass is older than 35 days), `unverified` (it passed but `psql` was missing, so the result was not inspected), or `current`.
* **`measured_rto_seconds` is the slowest of the last five passes** (create + restore + verify, on this machine), not the luckiest. It does **not** include noticing the failure, deciding, or repointing users.
* **RPO is not measured.** How much data a failure would lose needs the backup's transaction watermark; it is never inferred from restore time.
* It always drops the scratch database, even after a failure or a timeout, and the child programs never receive `VELORA_MASTER_KEY` or other `VELORA_*` secrets.

Run it on a schedule (for example weekly from cron) and alert when `assurance` is not `current`.
