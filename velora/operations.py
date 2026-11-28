"""Workspace operations: health snapshots and authenticated encrypted backups."""
from __future__ import annotations
import base64, gzip, hashlib, io, json, os, shutil, sqlite3, tarfile, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from cryptography.fernet import Fernet, InvalidToken
from . import layout
from .workspace import Workspace, WorkspaceError

MAGIC = b"VELORA-BACKUP-1\n"

MAGIC2 = b"VELORA-BACKUP-2\n"          # current: MAGIC2 + log2(N), r, p (one byte each) + 16-byte salt + Fernet token (the settings travel with the file)
KDF = (17, 8, 1)                        # scrypt N=2**17, r=8, p=1: the OWASP minimum (about 128 MB, a noticeable fraction of a second per guess). v1 files used N=2**14.
KDF_LIMITS = ((14, 20), (1, 16), (1, 4))   # what a header may ask for: a crafted file must not be able to demand gigabytes of memory


def _key(password: str, salt: bytes, log_n: int, r: int, p: int) -> Fernet:
    if not password or len(password) < 12:
        raise WorkspaceError("Backup encryption password must contain at least 12 characters")
    maxmem = 128 * r * (2 ** log_n) * 2 + (1 << 20)                       # hashlib.scrypt refuses more than 32 MB unless told how much it may use
    key = hashlib.scrypt(password.encode(), salt=salt, n=2 ** log_n, r=r, p=p, dklen=32, maxmem=maxmem)
    return Fernet(base64.urlsafe_b64encode(key))


def _fernet(password: str, salt: bytes) -> Fernet:
    return _key(password, salt, 14, 8, 1)                                  # the original (v1) settings, kept so old backups still open


def _seal(raw: bytes, password: str) -> bytes:
    salt = os.urandom(16)
    return MAGIC2 + bytes(KDF) + salt + _key(password, salt, *KDF).encrypt(raw)


def _unseal(data: bytes, password: str) -> tuple[bytes, int]:
    """(plain archive bytes, format version). A wrong password and a damaged file are indistinguishable by design: both say so."""
    if data.startswith(MAGIC2):
        head = len(MAGIC2)
        if len(data) <= head + 3 + 16:
            raise WorkspaceError("Not a supported Velora encrypted backup")
        params = tuple(data[head:head + 3])
        if any(not lo <= v <= hi for v, (lo, hi) in zip(params, KDF_LIMITS)):
            raise WorkspaceError("The backup header asks for unsupported key-derivation settings: the file is damaged or not a Velora backup")
        key, token, version = _key(password, data[head + 3:head + 19], *params), data[head + 19:], 2
    elif data.startswith(MAGIC):
        if len(data) <= len(MAGIC) + 16:
            raise WorkspaceError("Not a supported Velora encrypted backup")
        key, token, version = _fernet(password, data[len(MAGIC):len(MAGIC) + 16]), data[len(MAGIC) + 16:], 1
    else:
        raise WorkspaceError("Not a supported Velora encrypted backup")
    try:
        return key.decrypt(token), version
    except InvalidToken as exc:
        raise WorkspaceError("Backup password is incorrect or the backup has been altered") from exc


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def health_snapshot(ws: Workspace) -> dict:
    """Return operational signals without exposing configuration values or credentials."""
    sites = ws.sites(); apps = ws.apps()
    missing = [a for a in apps if not ws.app_path(a).is_dir()]
    disk = shutil.disk_usage(ws.root)
    free_percent = round(disk.free / disk.total * 100, 2) if disk.total else 0                       # (some filesystems report a total of 0)
    logs = ws.root / "logs"
    log_files = list(logs.glob("*.log")) if logs.exists() else []
    recent_errors = 0
    for path in log_files:
        try:
            tail = path.read_text(errors="replace")[-200_000:]
            recent_errors += sum(1 for line in tail.splitlines() if " ERROR " in line or "Traceback" in line)
        except OSError:
            continue
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(ws.root),
        "sites": {"count": len(sites), "names": sites},
        "applications": {"registered": apps, "missing_directories": missing},
        "storage": {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free, "free_percent": free_percent},
        "logs": {"files": len(log_files), "recent_error_lines": recent_errors},
        "status": "fail" if missing else ("warning" if free_percent < 10 else "ok"),
    }

def _folder_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink()) if path.is_dir() else 0


def create_encrypted_backup(ws: Workspace, password: str, destination: str | Path | None = None, *, include_files: bool | None = None) -> Path:
    """Create an encrypted, self-contained workspace snapshot. Existing backups/logs are excluded. Every SQLite database is captured with SQLite's own backup API (a consistent
    snapshot, including recent writes still in its write-ahead log), never by copying a file that may be mid-write."""
    _key(password, b"\0" * 16, 14, 8, 1)                                  # a weak password is refused up front, before any work
    files_dir, files_bytes = ws.root / "files", _folder_bytes(ws.root / "files")
    if include_files is None:                                              # automatic: include attachments unless they would not fit comfortably in memory
        include_files = files_bytes <= MAX_FILES_IN_BACKUP
    backup_dir = ws.root / "backups"; backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(destination) if destination else backup_dir / f"workspace-{stamp}.vbackup"
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".tar.gz", dir=out.parent); os.close(fd)
    try:
        with tempfile.TemporaryDirectory(dir=out.parent, prefix=".snapshot-") as stage_dir:
            stage, snapshots = Path(stage_dir), {}
            for top in ("sites", "platform"):
                for path in sorted((ws.root / top).rglob("*")) if (ws.root / top).exists() else []:
                    if path.is_file() and not path.is_symlink() and path.suffix in (".db", ".sqlite", ".sqlite3") and _is_sqlite(path):
                        rel = path.relative_to(ws.root).as_posix()
                        if any(part in {"backups", "logs", "__pycache__", ".git"} for part in rel.split("/")):
                            continue
                        dst = stage / rel; dst.parent.mkdir(parents=True, exist_ok=True)
                        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                        try:
                            copy = sqlite3.connect(dst)
                            try:
                                src.backup(copy)
                            finally:
                                copy.close()
                        finally:
                            src.close()
                        os.chmod(dst, path.stat().st_mode & 0o777)
                        snapshots[rel] = dst

            def include_member(member: tarfile.TarInfo):
                parts = Path(member.name).parts
                if any(part in {"backups", "__pycache__", ".git", "logs"} for part in parts):
                    return None
                if Path(member.name).name in {".env", ".env.local"}:
                    return None
                if member.name in snapshots or any(member.name == f"{k}{ext}" for k in snapshots for ext in ("-wal", "-shm", "-journal")):
                    return None                                                  # replaced by the consistent snapshot added below
                return member
            with tarfile.open(tmp_name, "w:gz") as tar:
                for top in [t for t in layout.backed_up_folders() if include_files or t != "files"]:
                    source = ws.root / top
                    if source.exists(): tar.add(source, arcname=top, recursive=True, filter=include_member)
                if not include_files and files_bytes:
                    note = (f"This backup does NOT contain the uploaded files ({files_bytes / 1024 ** 2:,.0f} MB in {files_dir}). Back that folder up separately "
                            "(for example with rsync) or run `velora ops backup` with enough memory and without --no-files.\n").encode()
                    info = tarfile.TarInfo(FILES_MARKER); info.size = len(note); info.mode = 0o600
                    tar.addfile(info, io.BytesIO(note))
                for rel, staged in sorted(snapshots.items()):
                    tar.add(staged, arcname=rel)
                # Workspace-level operational config only; never include logs, existing backups or VCS metadata.
                for name in ("README.md", ".gitignore"):
                    source = ws.root / name
                    if source.is_file(): tar.add(source, arcname=name)
        temp_out = out.with_suffix(out.suffix + ".tmp")
        temp_out.write_bytes(_seal(Path(tmp_name).read_bytes(), password)); os.chmod(temp_out, 0o600); os.replace(temp_out, out)
        return out
    finally:
        Path(tmp_name).unlink(missing_ok=True)


def verify_encrypted_backup(path: str | Path, password: str) -> dict:
    """Decrypt the backup and check what is inside it: the archive reads end to end, it has sites, and EVERY SQLite database in it passes SQLite's integrity check."""
    p = Path(path)
    try:
        raw, version = _unseal(p.read_bytes(), password)
        checked = 0
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            members = tar.getmembers()
            names = [m.name for m in members]
            if not any(n in ("config/apps.txt", "sites/apps.txt") for n in names):
                raise WorkspaceError("This does not look like a Velora workspace backup (it has no config/apps.txt)")
            with tempfile.TemporaryDirectory() as scratch:
                for i, m in enumerate(members):
                    if not m.isreg() or Path(m.name).suffix not in (".db", ".sqlite", ".sqlite3"):
                        continue
                    f = tar.extractfile(m)
                    head = f.read(16)
                    if head != b"SQLite format 3\x00":
                        continue
                    target = Path(scratch) / f"db{i}.sqlite"
                    with target.open("wb") as dst:
                        dst.write(head); shutil.copyfileobj(f, dst)
                    con = sqlite3.connect(target)
                    try:
                        result = con.execute("PRAGMA integrity_check").fetchone()[0]
                    except sqlite3.DatabaseError as exc:
                        result = str(exc)
                    finally:
                        con.close()
                    if result != "ok":
                        raise WorkspaceError(f"The database {m.name} inside the backup is damaged: {result}")
                    checked += 1
        has_files = any(n.startswith("files/") and n != FILES_MARKER for n in names)
        return {"valid": True, "file": p.name, "bytes": p.stat().st_size, "members": len(names), "databases_checked": checked, "format": version,
                "attachments": sum(1 for m in members if m.isreg() and m.name.startswith("files/") and m.name != FILES_MARKER), "files_included": has_files or FILES_MARKER not in names}
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise WorkspaceError(f"Backup verification failed: {exc}") from exc


RESTORE_TOP = set(layout.backed_up_folders()) | {"README.md", ".gitignore"}
MAX_FILES_IN_BACKUP = 1024 ** 3                  # the archive is built and encrypted in memory: above this, attachments are left out (and the backup SAYS so) rather than risk exhausting it
FILES_MARKER = "files/NOT-INCLUDED.txt"
MAX_RESTORE_BYTES = 32 * 1024 ** 3
MAX_RESTORE_MEMBERS = 500_000


def restore_encrypted_backup(path: str | Path, password: str, into: str | Path, *, max_bytes: int = MAX_RESTORE_BYTES) -> dict:
    """Restore a workspace backup into a NEW directory (never over a live workspace). Works on a machine that has no workspace at all, which is the situation after a disaster.

    Only plain files and folders with known top-level names are extracted: a backup that smuggles in an absolute path, `..`, a symbolic or hard link, a device or an unexpected
    top-level folder is refused before anything is written. Nothing is created at the destination unless the whole restore succeeds."""
    p, into = Path(path), Path(into).expanduser().resolve()
    try:
        raw, _version = _unseal(p.read_bytes(), password)
    except OSError as exc:
        raise WorkspaceError(f"Cannot read the backup: {exc}") from exc
    if into.exists() and (not into.is_dir() or any(into.iterdir())):
        raise WorkspaceError(f"{into} already exists and is not empty. Restore into a new directory, then switch to it: a restore never overwrites a live workspace")
    into.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{into.name}.restore-", dir=into.parent))
    files = total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            members = tar.getmembers()
            if not members or len(members) > MAX_RESTORE_MEMBERS:
                raise WorkspaceError("The backup is empty or has an unreasonable number of entries")
            seen = set()
            for m in members:
                pure = PurePosixPath(m.name)
                if pure.is_absolute() or ".." in pure.parts or "\\" in m.name or not pure.parts or pure.parts[0] not in RESTORE_TOP:
                    raise WorkspaceError(f"Unsafe entry in the backup (path): {m.name!r}")
                if not (m.isreg() or m.isdir()):
                    raise WorkspaceError(f"Unsafe entry in the backup (only files and folders are allowed): {m.name!r}")
                if m.name in seen:
                    raise WorkspaceError(f"Unsafe entry in the backup (listed twice): {m.name!r}")
                seen.add(m.name)
                total += m.size if m.isreg() else 0
                if total > max_bytes:
                    raise WorkspaceError(f"The backup would expand beyond {max_bytes // 1024 ** 3} GB")
            for m in members:
                pure, target = PurePosixPath(m.name), stage.joinpath(*PurePosixPath(m.name).parts)
                private = pure.parts[0] in ("platform", "config", "files")   # keys, credentials and customers' uploads: owner only, whatever the archive said
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True); os.chmod(target, 0o700 if private else 0o755)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                mode = (m.mode & 0o755) | 0o600                                 # never setuid/setgid/sticky, never group/other-writable
                os.chmod(target, mode & 0o700 if private else mode)
                files += 1
        sites = sorted(d.name for d in (stage / "sites").iterdir() if d.is_dir()) if (stage / "sites").is_dir() else []
        if into.exists():
            into.rmdir()
        os.replace(stage, into)
    except (tarfile.TarError, EOFError, OSError) as exc:
        shutil.rmtree(stage, ignore_errors=True)
        raise WorkspaceError(f"Restore failed and nothing was written to {into}: {exc}") from exc
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    uploads = sum(1 for p in (into / "files").rglob("*") if p.is_file() and p.name != "NOT-INCLUDED.txt") if (into / "files").is_dir() else 0
    companies = sorted(p.stem for p in (into / "platform" / "companies").glob("*.db")) if (into / "platform" / "companies").is_dir() else []
    return {"restored_to": str(into), "files": files, "attachments": uploads, "companies": companies, "attachments_included": not (into / "files" / "NOT-INCLUDED.txt").exists(),
            "bytes": total, "sites": sites, "control_plane": (into / "platform").is_dir(),
            "next": f"cd {into} && velora doctor     # then start it with `velora start`. PostgreSQL company databases are restored separately (`velora restore`)"}


def prune_backups(ws: Workspace, keep: int = 14) -> list[Path]:
    if keep < 1: raise WorkspaceError("Retention must keep at least one backup")
    folder = ws.root / "backups"
    files = sorted(folder.glob("*.vbackup"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.exists() else []
    removed = files[keep:]
    for path in removed: path.unlink()
    return removed


# Scheduled backup policy is workspace-scoped. A host scheduler (cron/systemd) invokes
# `velora ops run-scheduled`; this avoids hidden daemon threads and makes execution auditable.
POLICY_FILE = "config/backup-policy.json"
STATE_FILE = "config/backup-state.json"

def configure_backup_policy(ws: Workspace, *, every_hours: int = 24, keep: int = 14,
                            workspace_snapshot: bool = True, verify: bool = True) -> dict:
    if not isinstance(every_hours, int) or not 1 <= every_hours <= 720:
        raise WorkspaceError("Backup interval must be between 1 and 720 hours")
    if not isinstance(keep, int) or not 1 <= keep <= 365:
        raise WorkspaceError("Backup retention must be between 1 and 365 runs")
    policy = {"version": 1, "enabled": True, "every_hours": every_hours, "keep": keep,
              "workspace_snapshot": bool(workspace_snapshot), "verify": bool(verify),
              "updated_at": datetime.now(timezone.utc).isoformat()}
    path = ws.root / POLICY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(policy, indent=2) + "\n")
    os.chmod(tmp, 0o600); os.replace(tmp, path)
    return policy

def read_backup_policy(ws: Workspace) -> dict:
    path = ws.root / POLICY_FILE
    if not path.exists():
        raise WorkspaceError("No scheduled backup policy. Run `velora ops configure` first.")
    try:
        policy = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"Backup policy is unreadable: {exc}") from exc
    if policy.get("version") != 1 or not isinstance(policy.get("every_hours"), int) or not 1 <= policy["every_hours"] <= 720:
        raise WorkspaceError("Backup policy is invalid; reconfigure it with `velora ops configure`")
    return policy

def backup_status(ws: Workspace) -> dict:
    policy_path, state_path = ws.root / POLICY_FILE, ws.root / STATE_FILE
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    return {"configured": policy is not None, "policy": policy, "last_run": state.get("last_run"),
            "last_status": state.get("status"), "last_error": state.get("error"),
            "next_due": state.get("next_due")}

def _write_json_atomic(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    os.chmod(tmp, 0o600); os.replace(tmp, path)

def _verify_database_backup(path: Path) -> dict:
    """Verify gzip integrity; SQLite snapshots also receive PRAGMA integrity_check."""
    try:
        with gzip.open(path, "rb") as source:
            payload = source.read()
        if not payload:
            raise WorkspaceError(f"Backup is empty: {path.name}")
        if path.name.endswith(".db.gz"):
            with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
                tmp.write(payload); tmp.flush()
                conn = sqlite3.connect(tmp.name)
                try:
                    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise WorkspaceError(f"SQLite integrity check failed for {path.name}: {result}")
                finally:
                    conn.close()
        return {"valid": True, "file": path.name, "bytes": path.stat().st_size}
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise WorkspaceError(f"Database backup verification failed for {path.name}: {exc}") from exc

def _prune_folder(folder: Path, keep: int) -> list[str]:
    if keep < 1:
        raise WorkspaceError("Retention must keep at least one backup")
    candidates = sorted((p for p in folder.glob("*.gz") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True) if folder.exists() else []
    removed = candidates[keep:]
    for path in removed:
        path.unlink()
    return [p.name for p in removed]

def run_scheduled_backups(ws: Workspace, *, password: str | None = None, force: bool = False,
                          now_at: datetime | None = None) -> dict:
    """Run site/company database backups plus optional encrypted workspace snapshot.

    The caller should invoke this from cron/systemd. A process lock prevents overlapping runs.
    """
    import fcntl
    policy = read_backup_policy(ws)
    if not policy.get("enabled", True):
        return {"status": "disabled", "created": []}
    now_at = now_at or datetime.now(timezone.utc)
    state_path = ws.root / STATE_FILE
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    last = state.get("last_success")
    if not force and last:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None: last_dt = last_dt.replace(tzinfo=timezone.utc)
            if now_at - last_dt < timedelta(hours=policy["every_hours"]):
                return {"status": "not_due", "next_due": state.get("next_due"), "created": []}
        except ValueError:
            pass
    lock_path = ws.root / "backups" / ".scheduled-backup.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "already_running", "created": []}
        created, errors, verified, pruned = [], [], [], []
        try:
            from . import provision
            for site_name in ws.sites():
                try:
                    path = provision.backup_site(ws, site_name)
                    created.append({"scope": "site", "name": site_name, "path": str(path)})
                    if policy.get("verify", True): verified.append(_verify_database_backup(path))
                    pruned.extend({"scope": "site", "name": site_name, "file": n}
                                  for n in _prune_folder(ws.site_path(site_name) / "private" / "backups", policy["keep"]))
                except Exception as exc:  # isolate failures so one tenant does not block others
                    errors.append({"scope": "site", "name": site_name, "error": f"{type(exc).__name__}: {exc}"})
            if (ws.root / "platform" / "control_plane.json").exists():
                try:
                    from .controlplane import ControlPlane
                    plane = ControlPlane.open(ws)
                    cp_sqlite = (plane.platform_dir / plane.cfg.get("db_name", "control.db")) if plane.cfg.get("db_type", "sqlite") == "sqlite" else None
                    cp_backup = provision.backup_database(plane.cfg, cp_sqlite, plane.platform_dir / "backups", "control-plane")
                    created.append({"scope": "control_plane", "name": "control_plane", "path": str(cp_backup)})
                    if policy.get("verify", True): verified.append(_verify_database_backup(cp_backup))
                    pruned.extend({"scope": "control_plane", "name": "control_plane", "file": n}
                                  for n in _prune_folder(cp_backup.parent, policy["keep"]))
                    for company in plane.registry.list_companies():
                        if company.get("status", "active") != "active":
                            continue
                        try:
                            path = plane.backup_company(company)
                            created.append({"scope": "company", "name": company["id"], "path": str(path)})
                            if policy.get("verify", True): verified.append(_verify_database_backup(path))
                            pruned.extend({"scope": "company", "name": company["id"], "file": n}
                                          for n in _prune_folder(path.parent, policy["keep"]))
                        except Exception as exc:
                            errors.append({"scope": "company", "name": company.get("id", "unknown"), "error": f"{type(exc).__name__}: {exc}"})
                except Exception as exc:
                    errors.append({"scope": "control_plane", "name": "control_plane", "error": f"{type(exc).__name__}: {exc}"})
            if policy.get("workspace_snapshot"):
                if not password:
                    errors.append({"scope": "workspace", "name": "workspace", "error": "VELORA_BACKUP_PASSWORD is required for encrypted workspace snapshots"})
                else:
                    try:
                        path = create_encrypted_backup(ws, password)             # attachments included automatically when they fit (see MAX_FILES_IN_BACKUP)
                        created.append({"scope": "workspace", "name": "workspace", "path": str(path)})
                        if policy.get("verify", True): verified.append(verify_encrypted_backup(path, password))
                        pruned.extend({"scope": "workspace", "name": "workspace", "file": p.name}
                                      for p in _prune_workspace_snapshots(ws, policy["keep"]))
                    except Exception as exc:
                        errors.append({"scope": "workspace", "name": "workspace", "error": f"{type(exc).__name__}: {exc}"})
            status = "success" if not errors else ("partial" if created else "failed")
            state = {"last_run": now_at.isoformat(), "last_success": now_at.isoformat() if status == "success" else state.get("last_success"),
                     "status": status, "error_count": len(errors), "created_count": len(created),
                     "verified_count": len(verified),
                     "next_due": ((datetime.fromisoformat(state["last_success"]) + timedelta(hours=policy["every_hours"]))
                                  if state.get("last_success") else now_at).isoformat()}
            _write_json_atomic(state_path, state)
            audit = {"timestamp": now_at.isoformat(), "status": status, "created": created,
                     "verified": verified, "pruned": pruned, "errors": errors}
            audit_path = ws.root / "logs" / "backup-audit.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a") as stream:
                stream.write(json.dumps(audit, default=str) + "\n")
            os.chmod(audit_path, 0o600)
            return audit
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

def _prune_workspace_snapshots(ws: Workspace, keep: int) -> list[Path]:
    folder = ws.root / "backups"
    files = sorted(folder.glob("workspace-*.vbackup"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.exists() else []
    removed = files[keep:]
    for path in removed: path.unlink()
    return removed
