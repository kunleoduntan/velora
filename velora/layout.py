"""THE layout of a Velora workspace: one folder, six places, each with one job.

This table is the single source of truth. The workspace README, the `.gitignore`, the documentation page (docs/file-structure.md), `velora layout`, the `velora doctor`
check, the permission repair and the backup contents are all generated from or checked against it, so they cannot drift apart. To change the layout, change it here.

    my-erp/
    |-- apps/        CODE      your apps and installed apps (the only folder you edit or version-control)
    |-- config/      SETTINGS  which apps are active, installation settings, a plain history of installs and updates
    |-- platform/    SYSTEM    sign-in, people and companies (control.db), the master key, and one database file per SQLite company
    |-- files/       UPLOADS   everything people attached, one folder per company
    |-- backups/     BACKUPS   encrypted workspace backups and the safety copies taken before updates
    `-- logs/        LOGS      logs and evidence (restore rehearsals ...)

A workspace is RELOCATABLE: move, rename, copy or restore the folder anywhere and it opens its own data (no absolute paths are stored).
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------------------------------------------------------------------------------------
# What lives where
# --------------------------------------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    path: str                 # relative to the workspace; a trailing / means a folder
    kind: str                 # code | settings | system | uploads | backups | logs | legacy | document
    purpose: str              # plain language, shown in the README, the docs and `velora layout`
    private: bool = False     # only the owner may read it (secrets, databases, customers' files)
    backed_up: bool = True    # included in `velora ops backup`
    always: bool = True       # created with the workspace (False: appears when first needed)
    versioned: bool = False   # belongs in version control (only code does)


LAYOUT: tuple[Entry, ...] = (
    Entry("apps/", "code", "Your apps and every app you install: one folder per app. This is the only part you write, edit or keep in version control.", versioned=True),
    Entry("config/", "settings", "Settings for the whole installation: apps.txt (the apps that are switched on), common.json (installation settings) and lifecycle.json "
                                 "(a plain-language history of installs and updates).", private=True),
    Entry("platform/", "system", "The system itself: control.db (sign-in, people, companies and what they may do), master.key (encrypts the passwords Velora stores: "
                                 "keep it safe and never share it) and companies/ (one database file per SQLite company). Do not edit these by hand.", private=True,
          always=False),
    Entry("files/", "uploads", "Everything people attached to documents, in one folder per company, kept apart so one company can never see another's.", private=True,
          always=False),
    Entry("backups/", "backups", "Encrypted workspace backups (`velora ops backup`) and the safety copy taken before every update.", private=True, backed_up=False),
    Entry("logs/", "logs", "Logs, and evidence such as restore rehearsals.", private=True, backed_up=False),
    Entry("sites/", "legacy", "Only for the older one-database-per-site mode (`velora new-site`). New installations do not have this folder.", private=True, always=False),
    Entry("README.md", "document", "A short explanation of this folder (generated).", backed_up=True),
    Entry(".gitignore", "document", "Keeps secrets and data out of version control: only apps/ is committed (generated).", backed_up=True),
)

# Files that used to live somewhere else (versions before this layout). Moved, never copied, the first time a workspace is upgraded or started.
LEGACY_MOVES: tuple[tuple[str, str], ...] = (
    ("sites/apps.txt", "config/apps.txt"),
    ("sites/common_site_config.json", "config/common.json"),
    ("sites/lifecycle_log.json", "config/lifecycle.json"),
)

README_FIRST_LINE = "# Velora workspace"
OLD_README = ("# Velora workspace\n\n```\nvelora new-site erp.local\nvelora new-app myapp\nvelora --site erp.local install-app myapp\nvelora start\n```\n")
OLD_GITIGNORE = "sites/*/\nsites/currentsite.txt\nlogs/\nbackups/\n__pycache__/\n*.pyc\n.env\n"


def folders() -> list[Entry]:
    return [e for e in LAYOUT if e.path.endswith("/")]


def entry_for(top: str) -> Entry | None:
    top = top.rstrip("/")
    return next((e for e in LAYOUT if e.path.rstrip("/") == top), None)


def backed_up_folders() -> list[str]:
    """Folders `velora ops backup` includes (the single list the backup code uses)."""
    return [e.path.rstrip("/") for e in folders() if e.backed_up]


# --------------------------------------------------------------------------------------------------------------------------------------------------------
# Generated text
# --------------------------------------------------------------------------------------------------------------------------------------------------------
def render_gitignore() -> str:
    """Ignore EVERYTHING except the code and these two documents, so a new data folder is safe by default and `git init` + `git add .` can never publish master.key or a database."""
    keep = [e.path.rstrip("/") for e in LAYOUT if e.versioned or e.kind == "document"]
    lines = ["# Velora: only your apps (code) belong in version control.", "# Everything else is data or secrets (master.key, databases, uploads, backups) and is ignored by default.", "/*"]
    lines += [f"!/{k}" for k in keep]
    lines += ["", "__pycache__/", "*.pyc", ".env"]
    return "\n".join(lines) + "\n"


def render_readme() -> str:
    rows = "\n".join(f"  {e.path:<12} {e.purpose}" for e in LAYOUT if e.kind not in ("document", "legacy"))
    return f"""{README_FIRST_LINE}

This one folder is a complete Velora installation. Move it, copy it or restore it anywhere and it works: no absolute paths are stored.

```
{rows}
```

## The commands you need
```
velora start               run it (it also sets up and upgrades anything that needs it, by itself)
velora doctor              check everything, and say how to fix anything wrong
velora ops backup          an encrypted backup of the whole installation
velora ops restore-workspace BACKUP --into NEWFOLDER     bring it back on a new machine
velora update              get new versions: updates, migrations and restart, in one step
velora layout              see this structure with real sizes, and fix permissions
```

Keep `platform/master.key` safe: it protects the passwords Velora stores. Only `apps/` is meant for version control (the `.gitignore` here already ignores the rest).
Everything is explained at http://localhost:8000/tutorial once Velora is running, and in docs/file-structure.md.
"""


def render_doc() -> str:
    """docs/file-structure.md (a test keeps the committed file identical to this)."""
    table = "\n".join(f"| `{e.path}` | {e.kind} | {e.purpose} | {'owner only' if e.private else 'normal'} | "
                      f"{'yes' if e.backed_up else 'no'} |" for e in LAYOUT if e.kind not in ("document",))
    moves = "\n".join(f"| `{a}` | `{b}` |" for a, b in LEGACY_MOVES)
    return f"""<!-- Generated from velora/layout.py by `velora layout --write-docs`. Do not edit by hand: a test fails if this file differs from the generated text. -->
# The Velora file structure

A Velora installation is **one folder**, called a *workspace*. It has six places, each with one job:

```
my-erp/
{chr(10).join(f"  {e.path:<12}# {e.kind}" for e in LAYOUT if e.kind not in ("document", "legacy"))}
```

| Place | What it is | What is in it | Who can read it | In `velora ops backup` |
|---|---|---|---|---|
{table}

## Making one
One command creates the whole thing, with a first company and an administrator, and starts it:

```
velora quickstart my-erp --email you@company.com
```

After that, `velora start` (inside the folder) runs it. Starting also upgrades anything that needs upgrading and repairs permissions, so there is nothing else to remember.

## Moving, copying and restoring
The folder is **relocatable**: nothing inside it records where the folder is. You can rename it, move it to another disk or server, copy it, or restore a backup into a new folder, and it opens its own data.
* Backup: `velora ops backup` writes one encrypted file containing `{", ".join(backed_up_folders())}`. If your uploaded files are very large they are left out and the backup **says so**; back `files/` up with your usual file backup.
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
{moves}

Uploads kept in `company_files/` are renamed to `files/`. SQLite company databases recorded with an absolute path are made relative. Everything keeps working while that is pending.

## Seeing it
```
velora layout          the structure with real sizes, and anything that needs attention
velora layout --fix    apply the repairs (moves, permissions, README and .gitignore)
```
"""


# --------------------------------------------------------------------------------------------------------------------------------------------------------
# Inspecting
# --------------------------------------------------------------------------------------------------------------------------------------------------------
def _size(path: Path) -> tuple[int, int]:
    if path.is_file():
        return path.stat().st_size, 1
    total = count = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
                count += 1
        except OSError:
            continue
    return total, count


def describe(ws) -> list[dict]:
    rows = []
    for e in LAYOUT:
        p = ws.root / e.path.rstrip("/")
        size, files = _size(p) if p.exists() else (0, 0)
        rows.append({"path": e.path, "kind": e.kind, "purpose": e.purpose, "exists": p.exists(), "bytes": size, "files": files, "private": e.private, "backed_up": e.backed_up})
    return rows


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _private_files(ws) -> list[Path]:
    """Individual files that must be owner-only: databases (and their journal files), keys, settings, site configs."""
    out: list[Path] = []
    for rel, patterns in (("platform", ("*.db", "*.db-wal", "*.db-shm", "*.key", "*.json")), ("platform/companies", ("*.db", "*.db-wal", "*.db-shm")),
                          ("config", ("*",)), ("sites", ("*/*.db", "*/*.db-wal", "*/*.db-shm", "*/site_config.json"))):
        base = ws.root / rel
        if base.is_dir():
            for pattern in patterns:
                out.extend(p for p in base.glob(pattern) if p.is_file() and not p.is_symlink())
    return sorted(set(out))


def check(ws) -> list[dict]:
    """What is wrong or pending, each with how to fix it: [{severity: warn|info, message, fix}]."""
    findings: list[dict] = []

    def add(severity, message, fix="velora layout --fix"):
        findings.append({"severity": severity, "message": message, "fix": fix})
    for old, new in LEGACY_MOVES:
        if (ws.root / old).exists() and not (ws.root / new).exists():
            add("info", f"{old} should be {new} (older layout; everything works meanwhile)")
    if (ws.root / "company_files").is_dir() and not (ws.root / "files").exists():
        add("info", "company_files/ should be files/ (renamed automatically when the first upload is read)")
    for e in folders():
        p = ws.root / e.path.rstrip("/")
        if e.private and p.is_dir() and _mode(p) & 0o077:
            add("warn", f"{e.path} can be read by other users on this machine ({oct(_mode(p))})")
    loose = [p for p in _private_files(ws) if _mode(p) & 0o077]
    if loose:
        add("warn", f"{len(loose)} database/key/settings file(s) can be read by other users on this machine, for example {loose[0].relative_to(ws.root)}")
    gi = ws.root / ".gitignore"
    if gi.exists() and gi.read_text() == OLD_GITIGNORE:
        add("warn", ".gitignore does not exclude platform/ (git add . would publish master.key and the databases)")
    known = {e.path.rstrip("/") for e in LAYOUT} | {"company_files"}
    extra = sorted(p.name for p in ws.root.iterdir() if p.name not in known and not p.name.startswith(".") and p.name != "__pycache__")
    if extra:
        add("info", f"not part of the layout: {', '.join(extra)} (Velora ignores it; it is not in backups)", "move it elsewhere, or ignore this note")
    readme = ws.root / "README.md"
    if readme.exists() and readme.read_text() == OLD_README:
        add("info", "README.md describes the old four-command setup")
    return findings


# --------------------------------------------------------------------------------------------------------------------------------------------------------
# Repairing
# --------------------------------------------------------------------------------------------------------------------------------------------------------
def migrate(ws) -> list[str]:
    """Move settings files from their old places into config/. Moved, never copied; nothing is overwritten."""
    done = []
    for old, new in LEGACY_MOVES:
        src, dst = ws.root / old, ws.root / new
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            done.append(f"moved {old} -> {new}")
    legacy = ws.root / "sites"
    if legacy.is_dir() and not any(legacy.iterdir()):
        legacy.rmdir()                                                   # the old folder is empty now: leave nothing behind
        done.append("removed the empty sites/ folder")
    return done


def secure(ws) -> list[str]:
    """Make everything except apps/ owner-only. Returns what was changed (empty when everything was already right)."""
    changed = []
    for e in folders():
        p = ws.root / e.path.rstrip("/")
        if e.private and p.is_dir() and _mode(p) != 0o700:
            os.chmod(p, 0o700)
            changed.append(f"{e.path} -> 700")
    companies = ws.root / "platform" / "companies"
    if companies.is_dir() and _mode(companies) != 0o700:
        os.chmod(companies, 0o700)
        changed.append("platform/companies/ -> 700")
    for f in _private_files(ws):
        if _mode(f) & 0o077:
            os.chmod(f, 0o600)
            changed.append(f"{f.relative_to(ws.root)} -> 600")
    return changed


def refresh_documents(ws) -> list[str]:
    """Replace the README and .gitignore ONLY when they are still the unmodified old defaults (never overwrite something a person edited), and write them when missing."""
    done = []
    for name, old, new in (("README.md", OLD_README, render_readme()), (".gitignore", OLD_GITIGNORE, render_gitignore())):
        f = ws.root / name
        if not f.exists() or f.read_text() == old:
            f.write_text(new)
            done.append(f"wrote {name}")
    return done


def tidy(ws) -> list[str]:
    """Everything the workspace needs to be in the current layout. Cheap and idempotent: it runs at every start and upgrade, so nobody has to remember it."""
    return migrate(ws) + refresh_documents(ws) + secure(ws)


def render_tree(ws) -> str:
    def human(n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
    lines = [f"{ws.root}/"]
    for r in describe(ws):
        if not r["exists"] and r["kind"] in ("legacy", "uploads", "system"):
            continue
        mark = "" if r["exists"] else "   (created when first needed)"
        size = f"  {human(r['bytes'])} in {r['files']} file(s)" if r["exists"] and r["kind"] not in ("document",) else ""
        lines.append(f"  {r['path']:<12}{size}{mark}")
        lines.append(f"      {r['purpose'].split('. ')[0].rstrip('.')}." + ("" if r["backed_up"] else "  [not in backups]") + ("  [private]" if r["private"] else ""))
    return "\n".join(lines)
