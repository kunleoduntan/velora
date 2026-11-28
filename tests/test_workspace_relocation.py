"""A workspace is one folder, and it must keep working wherever that folder is: moved, renamed, copied to a new server, or restored from a backup."""
import shutil
from pathlib import Path

import pytest

from velora import operations as ops
from velora.controlplane import ControlPlane
from velora.settings import get_setting, set_setting
from velora.workspace import Workspace

PW = "a long secure passphrase"


@pytest.fixture
def made(tmp_path, monkeypatch):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    monkeypatch.delenv("VELORA_WORKSPACE", raising=False)
    ws = Workspace.create(tmp_path / "old-server" / "erp")
    plane = ControlPlane.create(ws, admin_email="boss@acme.ng", admin_password=PW)
    plane.registry.create_tenant("Acme Group")
    co = plane.provisioning.provision_company("Acme Group", "Acme Ltd", apps=[])
    with plane.company_scope(co["id"]):
        set_setting("probe", {"invoice": "INV-0001", "amount": 12345})
    plane.dispose()
    return ws, co["id"], tmp_path


def read_probe(root: Path, cid: str):
    plane = ControlPlane.open(Workspace(root))
    try:
        with plane.company_scope(cid):
            return get_setting("probe"), plane.router.db_url(plane.registry.get_company(cid))
    finally:
        plane.dispose()


def registry_path(root: Path, cid: str) -> str:
    plane = ControlPlane.open(Workspace(root))
    try:
        return plane.registry.get_company(cid)["db_name"]
    finally:
        plane.dispose()


def test_a_new_company_records_its_database_relative_to_the_workspace(made):
    ws, cid, _ = made
    assert registry_path(ws.root, cid) == f"companies/{cid}.db"                                           # not /home/someone/erp/platform/companies/...


def test_a_moved_workspace_opens_its_own_data_and_not_the_old_location(made):
    ws, cid, tmp = made
    new = tmp / "new-server" / "renamed-erp"
    new.parent.mkdir()
    shutil.move(str(ws.root), str(new))                                                                    # the folder is simply moved: the old path no longer exists
    probe, url = read_probe(new, cid)
    assert probe == {"invoice": "INV-0001", "amount": 12345}
    assert str(new.resolve()) in url and "old-server" not in url                                           # it opened the database INSIDE the new folder


def test_a_copy_is_independent_of_the_original(made):
    ws, cid, tmp = made
    copy = tmp / "copy"
    shutil.copytree(ws.root, copy)
    plane = ControlPlane.open(Workspace(copy))
    with plane.company_scope(cid):
        set_setting("probe", {"changed": "in the copy"})
    plane.dispose()
    assert read_probe(ws.root, cid)[0] == {"invoice": "INV-0001", "amount": 12345}                          # the original is untouched: a copy never writes into the source
    assert read_probe(copy, cid)[0] == {"changed": "in the copy"}


def test_the_whole_disaster_recovery_path_works_end_to_end(made):
    """The real scenario: the server is gone, only the encrypted backup file survives, and it is restored on a new machine."""
    ws, cid, tmp = made
    backup = ops.create_encrypted_backup(ws, "a backup password!")
    keep = tmp / "survivor.vbackup"
    shutil.copy(backup, keep)
    shutil.rmtree(ws.root)                                                                                 # the server burns down
    report = ops.restore_encrypted_backup(keep, "a backup password!", tmp / "new-machine" / "erp")
    assert report["control_plane"] is True
    probe, url = read_probe(Path(report["restored_to"]), cid)
    assert probe == {"invoice": "INV-0001", "amount": 12345}                                               # the company's data came back, and the system opened it
    assert "new-machine" in url


def test_a_workspace_from_an_older_version_with_absolute_paths_still_opens_and_is_tidied_by_the_upgrade(made):
    ws, cid, tmp = made
    from sqlalchemy import update
    from velora.controlplane import models as m
    plane = ControlPlane.open(ws)
    with plane.engine.begin() as c:                                                                         # what versions before this recorded
        c.execute(update(m.company).where(m.company.c.id == cid).values(db_name=str(ws.root / "platform" / "companies" / f"{cid}.db")))
    plane.dispose()
    new = tmp / "moved"
    shutil.move(str(ws.root), str(new))
    assert registry_path(new, cid).startswith(str(tmp / "old-server"))                                     # the recorded path is now wrong ...
    assert read_probe(new, cid)[0] == {"invoice": "INV-0001", "amount": 12345}                             # ... and it still works: the file is found inside this workspace
    plane = ControlPlane.open(Workspace(new))
    plan = plane.migrate()
    plane.dispose()
    assert any("relative to the workspace" in line for line in plan)
    assert registry_path(new, cid) == f"companies/{cid}.db"                                                # normal upgrade fixed it for good


def test_a_database_kept_outside_the_workspace_on_purpose_is_left_alone(made, tmp_path):
    ws, cid, tmp = made
    from sqlalchemy import update
    from velora.controlplane import models as m
    elsewhere = tmp / "shared-disk" / "acme.db"
    elsewhere.parent.mkdir()
    shutil.copy(ws.root / "platform" / "companies" / f"{cid}.db", elsewhere)
    plane = ControlPlane.open(ws)
    with plane.engine.begin() as c:
        c.execute(update(m.company).where(m.company.c.id == cid).values(db_name=str(elsewhere)))
    assert plane.normalize_company_paths() == 0 and plane.registry.get_company(cid)["db_name"] == str(elsewhere)
    assert plane.sqlite_path(plane.registry.get_company(cid)) == elsewhere
    plane.dispose()


def test_deleting_a_company_removes_its_own_file_in_a_moved_workspace(made):
    ws, cid, tmp = made
    new = tmp / "moved2"
    shutil.move(str(ws.root), str(new))
    plane = ControlPlane.open(Workspace(new))
    try:
        assert (new / "platform" / "companies" / f"{cid}.db").exists()
        plane.provisioning.delete_company(cid) if hasattr(plane.provisioning, "delete_company") else plane.provisioning.drop_company(cid)
        assert not (new / "platform" / "companies" / f"{cid}.db").exists()
    finally:
        plane.dispose()
