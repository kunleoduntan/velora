"""Create, drop and back up sites.

PostgreSQL has two modes:
  * provision  - give root credentials (`--db-root-password`); Velora creates a dedicated role and database for the site
  * bring-your-own - give an existing database + user (managed hosts that hand you a database and a login but no superuser)
SQLite is for development only.
"""
from __future__ import annotations

import gzip
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path


from . import dbadmin, site as site_mod
from .db import schema
from .workspace import Workspace, WorkspaceError


def _check_connect(cfg: dict):
    from .site import db_url_from_config
    dbadmin.check_connect(db_url_from_config(cfg, None))


def _stamp_fresh():
    """A brand-new database is current by definition: stamp the version and count existing patches as done."""
    from .upgrade import patches, state
    patches.mark_applied([])
    state.stamp()


def create_site(ws: Workspace, name: str, *, db: str = "sqlite", db_host: str = "localhost", db_port: int = 5432,
                db_name: str | None = None, db_user: str | None = None, db_password: str | None = None,
                root_user: str = "postgres", root_password: str | None = None, developer_mode: bool = False) -> Path:
    path = ws.site_path(name)
    if path.exists():
        raise WorkspaceError(f"Site {name} already exists")
    if db not in ("sqlite", "postgres"):
        raise WorkspaceError("--db must be 'sqlite' or 'postgres'")

    cfg: dict = {"db_type": db, "developer_mode": developer_mode, "secret_key": secrets.token_urlsafe(32),
                 "created_on": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    provisioned = False
    if db == "sqlite":
        cfg["db_name"] = "site.db"
    else:
        cfg.update(db_host=db_host, db_port=int(db_port))
        if root_password:                                   # provision mode
            ident = dbadmin.pg_ident(name)
            cfg.update(db_name=db_name or ident, db_user=db_user or ident, db_password=db_password or secrets.token_urlsafe(24))
            dbadmin.provision_pg(db_host, db_port, root_user, root_password, cfg["db_name"], cfg["db_user"], cfg["db_password"])
            provisioned = True
            cfg["provisioned_db"] = True
        else:                                               # bring-your-own database
            if not (db_name and db_user and db_password):
                raise WorkspaceError("PostgreSQL needs either --db-root-password (Velora creates the database) "
                                     "or --db-name, --db-user and --db-password (an existing, empty database)")
            cfg.update(db_name=db_name, db_user=db_user, db_password=db_password)
            _check_connect(cfg)

    try:
        for sub in ("private/backups", "public/files", "locks"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        cfg_file = path / "site_config.json"
        cfg_file.write_text(json.dumps(cfg, indent=2) + "\n")
        os.chmod(cfg_file, 0o600)                           # holds the database password and secret key
        site = site_mod.site_from_dir(path)
        try:
            with site_mod.use(site):
                schema.ensure_system_tables()
                _stamp_fresh()
        finally:
            site.dispose()
    except Exception:
        shutil.rmtree(path, ignore_errors=True)
        if provisioned:
            dbadmin.drop_pg(db_host, db_port, root_user, root_password, cfg["db_name"], cfg["db_user"])
        raise
    if not ws.sites() or ws.sites() == [name]:
        ws.use(name)
    return path


def drop_site(ws: Workspace, name: str, *, root_user: str = "postgres", root_password: str | None = None) -> str:
    path = ws.site_path(name)
    if not (path / "site_config.json").exists():
        raise WorkspaceError(f"Site {name} does not exist")
    cfg = site_mod.read_site_config(path)
    site_mod.unload_site(path)
    note = "database left untouched"
    if cfg.get("db_type") == "postgres" and cfg.get("provisioned_db"):
        if not root_password:
            raise WorkspaceError("This site's PostgreSQL database was created by Velora; pass --db-root-password to drop it "
                                 "(or drop it yourself and delete the site folder)")
        dbadmin.drop_pg(cfg.get("db_host", "localhost"), cfg.get("db_port", 5432), root_user, root_password, cfg["db_name"], cfg["db_user"])
        note = "database and role dropped"
    elif cfg.get("db_type") == "postgres":
        note = "the PostgreSQL database was NOT dropped (it was not created by Velora)"
    shutil.rmtree(path)
    cur = ws.sites_dir / "currentsite.txt"
    if cur.exists() and cur.read_text().strip() == name:
        cur.unlink()
    return note


def backup_database(cfg: dict, sqlite_file: Path | None, out_dir: Path, label: str) -> Path:
    """Back up one database described by a config dict (site_config.json or a company registry row + its secret)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pg = cfg.get("db_type", "sqlite") == "postgres"
    ext = "sql" if pg else "db"
    out, n = out_dir / f"{stamp}-{label}-database.{ext}.gz", 1
    while out.exists():                                     # a backup is NEVER overwritten (two in the same second, or a restore's safety copy)
        n += 1
        out = out_dir / f"{stamp}-{label}-database-{n}.{ext}.gz"
    if not pg:
        tmp = out_dir / f".{stamp}.tmp"
        s, d = sqlite3.connect(sqlite_file), sqlite3.connect(tmp)
        with d:
            s.backup(d)                                     # consistent copy even while the database is in use
        s.close(); d.close()
        with open(tmp, "rb") as fi, gzip.open(out, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        tmp.unlink()
    else:
        if not shutil.which("pg_dump"):
            raise WorkspaceError("pg_dump was not found. Install the PostgreSQL client tools (e.g. `apt install postgresql-client`).")
        env = {**os.environ, "PGPASSWORD": cfg.get("db_password", "")}
        cmd = ["pg_dump", "-h", cfg.get("db_host", "localhost"), "-p", str(cfg.get("db_port", 5432)),
               "-U", cfg["db_user"], "--no-owner", "--no-privileges", cfg["db_name"]]
        proc = subprocess.run(cmd, env=env, capture_output=True)
        if proc.returncode:
            raise WorkspaceError(f"pg_dump failed: {proc.stderr.decode(errors='replace').strip()[:300]}")
        with gzip.open(out, "wb") as fo:
            fo.write(proc.stdout)
    os.chmod(out, 0o600)
    return out


def backup_site(ws: Workspace, name: str) -> Path:
    path = ws.site_path(name)
    cfg = site_mod.read_site_config(path)
    return backup_database(cfg, path / cfg.get("db_name", "site.db"), path / "private" / "backups", name)
