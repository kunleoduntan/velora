"""Uploaded files live in one fixed folder inside the workspace, and a backup that cannot restore them is not a backup."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from velora import files, operations as ops
from velora.controlplane import ControlPlane
from velora.workspace import Workspace

PW = "a long secure passphrase"
BK = "a backup password!"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    monkeypatch.delenv("VELORA_WORKSPACE", raising=False)
    monkeypatch.delenv("VELORA_FILE_ROOT", raising=False)
    ws = Workspace.create(tmp_path / "erp")
    plane = ControlPlane.create(ws, admin_email="boss@acme.ng", admin_password=PW)
    plane.registry.create_tenant("Acme Group")
    co = plane.provisioning.provision_company("Acme Group", "Acme Ltd", apps=[])
    yield ws, plane, co["id"], tmp_path
    plane.dispose()


def root_of(plane, cid):
    with plane.company_scope(cid):
        return files.storage_root()


def put(root: Path, name: str, data: bytes):
    f = root / name[:2] / name[2:4] / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


# ============================== where the files are ==============================
def test_uploads_live_in_one_fixed_private_folder_inside_the_workspace(env):
    ws, plane, cid, _ = env
    root = root_of(plane, cid)
    assert root == (ws.root / "files" / cid).resolve() and root.is_dir()
    assert (ws.root / "files").stat().st_mode & 0o077 == 0 and root.stat().st_mode & 0o077 == 0              # nobody else on the machine can read customers' uploads


def test_the_old_folder_name_is_renamed_once_automatically_and_nothing_is_lost(env):
    ws, plane, cid, _ = env
    old = ws.root / "company_files" / cid
    old.mkdir(parents=True)
    (old / "invoice.bin").write_bytes(b"uploaded before the upgrade")
    root = root_of(plane, cid)
    assert (root / "invoice.bin").read_bytes() == b"uploaded before the upgrade"
    assert not (ws.root / "company_files").exists()
    assert root_of(plane, cid) == root                                                                        # idempotent: nothing further happens


def test_if_both_folders_exist_the_new_one_wins_and_the_old_is_never_clobbered(env):
    ws, plane, cid, _ = env
    (ws.root / "files" / cid).mkdir(parents=True)
    (ws.root / "company_files" / cid).mkdir(parents=True)
    (ws.root / "company_files" / cid / "keep.bin").write_bytes(b"x")
    assert root_of(plane, cid) == (ws.root / "files" / cid).resolve()
    assert (ws.root / "company_files" / cid / "keep.bin").exists()                                            # left for a human to reconcile, never overwritten


# ============================== the backup carries them ==============================
def test_disaster_recovery_brings_the_attachments_back_too(env):
    ws, plane, cid, tmp = env
    root = root_of(plane, cid)
    contract = put(root, "ab12cd34ef", b"the signed contract")
    big = bytes(range(256)) * 400
    put(root, "ff00aa11bb", big)
    kept = tmp / "survivor.vbackup"
    kept.write_bytes(ops.create_encrypted_backup(ws, BK).read_bytes())
    plane.dispose()
    __import__("shutil").rmtree(ws.root)
    report = ops.restore_encrypted_backup(kept, BK, tmp / "new-machine" / "erp")
    new_root = tmp / "new-machine" / "erp" / "files" / cid
    assert report["attachments"] == 2 and report["attachments_included"] is True
    assert (new_root / "ab" / "12" / "ab12cd34ef").read_bytes() == b"the signed contract"
    assert (new_root / "ff" / "00" / "ff00aa11bb").read_bytes() == big
    assert (new_root / "ab" / "12" / "ab12cd34ef").stat().st_mode & 0o077 == 0                                # restored private, whatever the archive said
    assert (tmp / "new-machine" / "erp" / "files").stat().st_mode & 0o077 == 0
    assert contract.name == "ab12cd34ef"


# ============================== too large to hold in memory: say so, never silently omit ==============================
def test_attachments_too_large_for_the_backup_are_left_out_and_the_backup_says_so(env, monkeypatch):
    ws, plane, cid, tmp = env
    put(root_of(plane, cid), "ab12cd34ef", b"x" * 100)
    monkeypatch.setattr(ops, "MAX_FILES_IN_BACKUP", 10)
    backup = ops.create_encrypted_backup(ws, BK)
    info = ops.verify_encrypted_backup(backup, BK)
    assert info["files_included"] is False and info["attachments"] == 0
    report = ops.restore_encrypted_backup(backup, BK, tmp / "r1")
    assert report["attachments_included"] is False and report["attachments"] == 0
    note = (tmp / "r1" / "files" / "NOT-INCLUDED.txt").read_text()
    assert "does NOT contain the uploaded files" in note and str(ws.root / "files") in note and "rsync" in note   # whoever restores it is told, in the backup itself


def test_the_choice_can_be_forced_either_way(env, monkeypatch):
    ws, plane, cid, tmp = env
    put(root_of(plane, cid), "ab12cd34ef", b"x" * 100)
    monkeypatch.setattr(ops, "MAX_FILES_IN_BACKUP", 10)
    assert ops.verify_encrypted_backup(ops.create_encrypted_backup(ws, BK, include_files=True), BK)["attachments"] == 1          # "yes, include them anyway"
    monkeypatch.setattr(ops, "MAX_FILES_IN_BACKUP", 10 ** 9)
    assert ops.verify_encrypted_backup(ops.create_encrypted_backup(ws, BK, include_files=False), BK)["files_included"] is False   # "leave them out"


def test_a_workspace_with_no_uploads_has_a_clean_backup_with_no_warning_note(env):
    ws, plane, cid, tmp = env
    info = ops.verify_encrypted_backup(ops.create_encrypted_backup(ws, BK), BK)
    assert info["files_included"] is True and info["attachments"] == 0


# ============================== unattended ==============================
def test_the_backup_command_runs_unattended_with_the_environment_password_and_reports_the_files(env):
    ws, plane, cid, tmp = env
    put(root_of(plane, cid), "ab12cd34ef", b"data")
    plane.dispose()
    e = {**os.environ, "VELORA_BACKUP_PASSWORD": BK, "PYTHONPATH": str(ROOT)}
    e.pop("VELORA_WORKSPACE", None)
    run = lambda *a: subprocess.run([sys.executable, "-m", "velora.cli", "--workspace", str(ws.root), "ops", *a], capture_output=True, text=True, env=e, timeout=120, stdin=subprocess.DEVNULL)  # noqa: E731
    r = run("backup")
    assert r.returncode == 0 and "Encrypted workspace backup created" in r.stdout and "Uploaded files: 1 included" in r.stdout, r.stderr
    r = run("backup", "--no-files")
    assert r.returncode == 0 and "WARNING: uploaded files are NOT in this backup" in r.stdout


def test_a_files_folder_that_already_existed_with_loose_permissions_is_made_private(env):
    ws, plane, cid, _ = env
    (ws.root / "files").mkdir()
    os.chmod(ws.root / "files", 0o755)                                                                       # e.g. created by hand, or by an older version
    root_of(plane, cid)
    assert (ws.root / "files").stat().st_mode & 0o077 == 0
