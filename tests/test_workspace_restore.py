"""Encrypted workspace backups can be restored, safely, on a machine that has nothing."""
import io
import os
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from velora import operations as ops
from velora.workspace import Workspace, WorkspaceError

PW = "correct horse battery"
ROOT = Path(__file__).resolve().parent.parent


def build_workspace(tmp_path):
    ws = Workspace.create(tmp_path / "live")
    (ws.apps_dir / "shop").mkdir(parents=True, exist_ok=True)
    (ws.apps_dir / "shop" / "hello.py").write_text("print('shop')\n")
    site = ws.sites_dir / "demo.local"
    site.mkdir(parents=True, exist_ok=True)
    (site / "site_config.json").write_text('{"db_type": "sqlite", "db_name": "demo.db"}')
    (ws.root / "platform").mkdir(exist_ok=True)
    key = ws.root / "platform" / "master.key"
    key.write_text("SECRET-KEY\n"); os.chmod(key, 0o644)                                              # deliberately sloppy: a restore must tighten it
    (ws.root / "logs").mkdir(exist_ok=True); (ws.root / "logs" / "app.log").write_text("log line\n")
    (ws.root / "backups").mkdir(exist_ok=True); (ws.root / "backups" / "old.vbackup").write_bytes(b"old")
    (ws.root / "config" / ".env").write_text("TOKEN=abc\n")
    return ws


def live_db(ws, rows=50):
    """A SQLite database in WAL mode whose latest rows exist ONLY in the -wal file (nothing checkpointed), with the connection still open: like a running system."""
    con = sqlite3.connect(ws.sites_dir / "demo.local" / "demo.db", isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL"); con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE IF NOT EXISTS invoice (id INTEGER PRIMARY KEY, total INTEGER)")
    con.executemany("INSERT INTO invoice (total) VALUES (?)", [(i,) for i in range(rows)])
    return con


def members(vb, pw=PW):
    raw, _ = ops._unseal(Path(vb).read_bytes(), pw)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as t:
        return {m.name: m for m in t.getmembers()}


# ============================== backup and restore round trip ==============================
def test_a_backup_restores_into_a_new_directory_with_everything_that_matters(tmp_path):
    ws = build_workspace(tmp_path)
    con = live_db(ws)
    backup = ops.create_encrypted_backup(ws, PW)
    report = ops.restore_encrypted_backup(backup, PW, tmp_path / "recovered")
    out = tmp_path / "recovered"
    assert report["restored_to"] == str(out) and report["sites"] == ["demo.local"] and report["control_plane"] is True and report["files"] >= 4
    assert (out / "apps" / "shop" / "hello.py").read_text() == "print('shop')\n"
    assert (out / "sites" / "demo.local" / "site_config.json").exists()
    assert (out / "platform" / "master.key").read_text() == "SECRET-KEY\n"
    restored = sqlite3.connect(out / "sites" / "demo.local" / "demo.db")
    assert restored.execute("SELECT count(*), sum(total) FROM invoice").fetchone() == (50, sum(range(50)))          # every row, including those that lived only in the write-ahead log
    assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    restored.close(); con.close()


def test_secrets_logs_old_backups_and_wal_files_are_not_in_the_backup(tmp_path):
    ws = build_workspace(tmp_path)
    con = live_db(ws)
    names = set(members(ops.create_encrypted_backup(ws, PW)))
    assert "sites/demo.local/demo.db" in names
    assert not {n for n in names if n.endswith(("-wal", "-shm", "-journal"))}                                    # the snapshot already contains them
    assert not {n for n in names if n.startswith(("logs", "backups")) or n.endswith(".env")}
    con.close()


def test_the_restore_tightens_permissions_on_keys_and_never_keeps_setuid(tmp_path):
    ws = build_workspace(tmp_path)
    os.chmod(ws.apps_dir / "shop" / "hello.py", 0o4777)                                                          # setuid + world-writable
    out = tmp_path / "r"
    ops.restore_encrypted_backup(ops.create_encrypted_backup(ws, PW), PW, out)
    assert (out / "platform" / "master.key").stat().st_mode & 0o077 == 0                                         # owner only, though it was 0644
    mode = (out / "apps" / "shop" / "hello.py").stat().st_mode
    assert not mode & 0o6000 and not mode & 0o022                                                                # no setuid/setgid, not group/other-writable
    assert (out / "platform").stat().st_mode & 0o077 == 0


def test_a_restore_never_overwrites_anything_and_leaves_no_debris_on_failure(tmp_path):
    ws = build_workspace(tmp_path)
    backup = ops.create_encrypted_backup(ws, PW)
    full = tmp_path / "full"; full.mkdir(); (full / "precious.txt").write_text("keep me")
    with pytest.raises(WorkspaceError, match="Restore into a new directory"):
        ops.restore_encrypted_backup(backup, PW, full)
    assert (full / "precious.txt").read_text() == "keep me"
    with pytest.raises(WorkspaceError, match="Restore into a new directory"):
        ops.restore_encrypted_backup(backup, PW, ws.root)                                                        # the live workspace itself
    empty = tmp_path / "empty"; empty.mkdir()
    assert ops.restore_encrypted_backup(backup, PW, empty)["files"] > 0 and (empty / "apps" / "shop" / "hello.py").exists()   # an EMPTY directory is fine
    with pytest.raises(WorkspaceError, match="incorrect or the backup has been altered"):
        ops.restore_encrypted_backup(backup, "not the right password", tmp_path / "nope")
    assert not (tmp_path / "nope").exists() and not [p for p in tmp_path.iterdir() if ".restore-" in p.name]     # nothing at the destination, no staging folder left


# ============================== the file format ==============================
def test_new_backups_carry_their_key_derivation_settings_and_use_the_stronger_cost(tmp_path):
    ws = build_workspace(tmp_path)
    data = ops.create_encrypted_backup(ws, PW).read_bytes()
    assert data.startswith(ops.MAGIC2) and tuple(data[len(ops.MAGIC2):len(ops.MAGIC2) + 3]) == (17, 8, 1) and ops.KDF[0] >= 17


def test_backups_made_by_older_versions_still_verify_and_restore(tmp_path):
    ws = build_workspace(tmp_path)
    raw, _ = ops._unseal(ops.create_encrypted_backup(ws, PW).read_bytes(), PW)
    import os as _os
    salt = _os.urandom(16)
    v1 = tmp_path / "legacy.vbackup"
    v1.write_bytes(ops.MAGIC + salt + ops._fernet(PW, salt).encrypt(raw))                                       # exactly what v0.41-v0.49 wrote
    assert ops.verify_encrypted_backup(v1, PW)["format"] == 1
    assert ops.restore_encrypted_backup(v1, PW, tmp_path / "from_v1")["sites"] == ["demo.local"]


def test_a_crafted_header_cannot_demand_gigabytes_of_memory(tmp_path):
    bomb = ops.MAGIC2 + bytes([31, 8, 1]) + b"\0" * 16 + b"x" * 64
    f = tmp_path / "bomb.vbackup"; f.write_bytes(bomb)
    with pytest.raises(WorkspaceError, match="unsupported key-derivation"):
        ops.verify_encrypted_backup(f, PW)                                                                       # refused instantly: scrypt never ran
    for junk in (b"", b"nope", ops.MAGIC2, ops.MAGIC2 + b"\0" * 5, ops.MAGIC + b"\0" * 5):
        f.write_bytes(junk)
        with pytest.raises(WorkspaceError, match="Not a supported|unsupported"):
            ops.verify_encrypted_backup(f, PW)


def test_tampering_with_any_byte_is_detected(tmp_path):
    ws = build_workspace(tmp_path)
    backup = ops.create_encrypted_backup(ws, PW)
    data = bytearray(backup.read_bytes())
    for position in (len(ops.MAGIC2) + 3 + 16 + 5, len(data) // 2, len(data) - 3):
        mutated = bytearray(data); mutated[position] ^= 0x01
        backup.write_bytes(bytes(mutated))
        with pytest.raises(WorkspaceError, match="incorrect or the backup has been altered"):
            ops.verify_encrypted_backup(backup, PW)


def test_verification_looks_inside_and_catches_a_damaged_database(tmp_path):
    ws = build_workspace(tmp_path)
    live_db(ws, rows=3000).close()
    good = ops.verify_encrypted_backup(ops.create_encrypted_backup(ws, PW), PW)
    assert good["valid"] and good["databases_checked"] >= 1 and good["format"] == 2
    db_path = ws.sites_dir / "demo.local" / "demo.db"
    raw = bytearray(db_path.read_bytes()); raw[8192:20480] = os.urandom(12288)                                   # scribble over the middle of the database file
    db_path.write_bytes(bytes(raw))
    for name in ("-wal", "-shm"):
        Path(str(db_path) + name).unlink(missing_ok=True)
    bad = tmp_path / "bad.vbackup"
    with tarfile.open(tmp_path / "bad.tar.gz", "w:gz") as t:
        t.add(ws.sites_dir, arcname="sites")
        t.add(ws.root / "config", arcname="config")
    bad.write_bytes(ops._seal((tmp_path / "bad.tar.gz").read_bytes(), PW))
    with pytest.raises(WorkspaceError, match="damaged"):
        ops.verify_encrypted_backup(bad, PW)                                                                     # the old verify only listed file names and would have said "valid"


def test_a_weak_password_is_refused_before_any_work(tmp_path):
    ws = build_workspace(tmp_path)
    with pytest.raises(WorkspaceError, match="12 characters"):
        ops.create_encrypted_backup(ws, "short")
    assert not list((ws.root / "backups").glob("workspace-*"))


# ============================== hostile archives ==============================
def evil(tmp_path, build, name="evil.vbackup"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        build(t)
    f = tmp_path / name
    f.write_bytes(ops._seal(buf.getvalue(), PW))
    return f


def add_file(t, name, data=b"x", mode=0o644):
    info = tarfile.TarInfo(name); info.size = len(data); info.mode = mode
    t.addfile(info, io.BytesIO(data))


def add_special(t, name, kind, target=""):
    info = tarfile.TarInfo(name); info.type = kind; info.linkname = target
    t.addfile(info)


@pytest.mark.parametrize("label,build,frag", [
    ("parent traversal", lambda t: add_file(t, "sites/../../evil.txt"), "path"),
    ("deep traversal", lambda t: add_file(t, "apps/x/../../../../etc/cron.d/pwn"), "path"),
    ("absolute path", lambda t: add_file(t, "/etc/passwd"), "path"),
    ("windows separator", lambda t: add_file(t, "sites\\evil.txt"), "path"),
    ("unexpected top-level folder", lambda t: add_file(t, "etc/passwd"), "path"),
    ("symbolic link", lambda t: add_special(t, "sites/link", tarfile.SYMTYPE, "/etc"), "files and folders"),
    ("hard link", lambda t: add_special(t, "sites/hard", tarfile.LNKTYPE, "sites/x"), "files and folders"),
    ("device node", lambda t: add_special(t, "sites/dev", tarfile.CHRTYPE), "files and folders"),
    ("fifo", lambda t: add_special(t, "sites/pipe", tarfile.FIFOTYPE), "files and folders"),
    ("duplicate entry", lambda t: (add_file(t, "sites/a"), add_file(t, "sites/a")), "listed twice"),
])
def test_hostile_archives_are_refused_before_anything_is_written(tmp_path, label, build, frag):
    victim = tmp_path / "victim"; victim.mkdir()
    out = tmp_path / "out"
    f = evil(tmp_path, lambda t: (add_file(t, "sites/ok.txt"), build(t)))                                         # a perfectly good file first: still nothing may be written
    with pytest.raises(WorkspaceError, match=frag):
        ops.restore_encrypted_backup(f, PW, out)
    assert not out.exists() and not [p for p in tmp_path.iterdir() if ".restore-" in p.name] and list(victim.iterdir()) == []
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path.parent / "evil.txt").exists()


def test_a_damaged_archive_halfway_through_leaves_nothing_behind(tmp_path):
    """The password was right and the staging folder already exists when the archive turns out to be cut short: the folder must not be left lying around."""
    ws = build_workspace(tmp_path)
    raw, _ = ops._unseal(ops.create_encrypted_backup(ws, PW).read_bytes(), PW)
    cut = tmp_path / "cut.vbackup"
    cut.write_bytes(ops._seal(raw[: len(raw) * 2 // 3], PW))                                                     # a valid envelope around a truncated gzip stream
    with pytest.raises(WorkspaceError, match="Restore failed and nothing was written"):
        ops.restore_encrypted_backup(cut, PW, tmp_path / "out")
    assert not (tmp_path / "out").exists() and not [p for p in tmp_path.iterdir() if ".restore-" in p.name]


def test_a_backup_that_would_expand_beyond_the_limit_is_refused(tmp_path):
    f = evil(tmp_path, lambda t: add_file(t, "sites/big.bin", b"\0" * 5000))
    with pytest.raises(WorkspaceError, match="expand beyond"):
        ops.restore_encrypted_backup(f, PW, tmp_path / "o", max_bytes=1000)
    assert not (tmp_path / "o").exists()


# ============================== from the command line, on a machine with no workspace ==============================
def test_the_command_restores_on_a_bare_machine_using_the_environment_password(tmp_path):
    ws = build_workspace(tmp_path)
    backup = ops.create_encrypted_backup(ws, PW)
    bare = tmp_path / "newserver"; bare.mkdir()                                                                  # no workspace here at all
    env = {**os.environ, "VELORA_BACKUP_PASSWORD": PW, "PYTHONPATH": str(ROOT)}
    env.pop("VELORA_WORKSPACE", None)

    def cli(*a):
        r = subprocess.run([sys.executable, "-m", "velora.cli", "ops", *a], capture_output=True, text=True, cwd=bare, env=env, timeout=120)
        return r.returncode, r.stdout, r.stderr
    code, out, err = cli("verify", str(backup))
    assert code == 0 and '"databases_checked"' in out, err
    code, out, err = cli("restore-workspace", str(backup), "--into", str(bare / "recovered"))
    assert code == 0 and '"sites": [' in out and "demo.local" in out and (bare / "recovered" / "apps" / "shop" / "hello.py").exists(), err
    assert cli("restore-workspace", str(backup))[0] != 0 and "--into" in cli("restore-workspace", str(backup))[2]
    assert "not empty" in cli("restore-workspace", str(backup), "--into", str(bare / "recovered"))[2]
    env["VELORA_BACKUP_PASSWORD"] = "the wrong password!"
    assert "incorrect or the backup has been altered" in cli("restore-workspace", str(backup), "--into", str(bare / "again"))[2]


def test_an_archive_that_is_not_a_workspace_is_refused_with_a_clear_reason(tmp_path):
    f = evil(tmp_path, lambda t: add_file(t, "apps/x.py"))
    with pytest.raises(WorkspaceError, match="does not look like a Velora workspace backup"):
        ops.verify_encrypted_backup(f, PW)


def test_backups_of_both_layouts_verify(tmp_path):
    new = build_workspace(tmp_path)
    assert ops.verify_encrypted_backup(ops.create_encrypted_backup(new, PW), PW)["valid"]                    # config/apps.txt
    old = tmp_path / "older"
    for d in ("apps", "sites", "config"):
        (old / d).mkdir(parents=True)
    (old / "sites" / "apps.txt").write_text("")
    assert ops.verify_encrypted_backup(ops.create_encrypted_backup(Workspace(old), PW), PW)["valid"]          # sites/apps.txt
