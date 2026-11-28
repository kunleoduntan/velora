"""The workspace layout: simple, documented, generated from one table, relocatable, private by default, and self-repairing."""
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from velora import layout, operations as ops, quickstart as qs
from velora.workspace import Workspace

ROOT = Path(__file__).resolve().parent.parent
PW = "a long passphrase 1"


def mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


@pytest.fixture
def quick(tmp_path, monkeypatch):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    monkeypatch.delenv("VELORA_WORKSPACE", raising=False)
    res = qs.quickstart(str(tmp_path / "erp"), email="boss@acme.ng", password=PW, company="Acme Ltd", log=lambda *_: None)
    return Workspace(Path(res["workspace"]))


def cli(ws, *args, check=False):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("VELORA_WORKSPACE", None)
    r = subprocess.run([sys.executable, "-m", "velora.cli", "--workspace", str(ws.root), *args], capture_output=True, text=True, env=env, timeout=180, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


def legacy_workspace(tmp_path) -> Workspace:
    """What every version before this layout created."""
    root = tmp_path / "old"
    for d in ("apps", "sites", "config", "logs", "backups"):
        (root / d).mkdir(parents=True)
    (root / "sites" / "apps.txt").write_text("starter\n")
    (root / "sites" / "common_site_config.json").write_text('{"developer_mode": false, "auto_upgrade": true}')
    (root / "sites" / "lifecycle_log.json").write_text("[]")
    (root / ".gitignore").write_text(layout.OLD_GITIGNORE)
    (root / "README.md").write_text(layout.OLD_README)
    return Workspace(root)


# ============================== the structure ==============================
def test_a_new_workspace_has_exactly_the_documented_places_and_no_legacy_folder(tmp_path):
    ws = Workspace.create(tmp_path / "erp")
    names = sorted(p.name for p in ws.root.iterdir())
    assert names == [".gitignore", "README.md", "apps", "backups", "config", "logs"]
    assert (ws.root / "config" / "apps.txt").exists() and (ws.root / "config" / "common.json").exists() and not (ws.root / "sites").exists()
    assert Workspace.is_workspace(ws.root) and Workspace.discover(ws.root / "apps").root == ws.root                       # found from inside it


def test_quickstart_builds_the_whole_documented_structure_in_one_step(quick):
    assert sorted(p.name for p in quick.root.iterdir()) == [".gitignore", "README.md", "apps", "backups", "config", "logs", "platform"]
    assert (quick.root / "platform" / "control.db").exists() and (quick.root / "platform" / "master.key").exists()
    assert list((quick.root / "platform" / "companies").glob("COMP-*.db"))
    assert layout.check(quick) == []                                                                                       # and nothing is wrong with it


def test_every_part_of_the_layout_is_unique_and_only_code_is_versioned():
    paths = [e.path for e in layout.LAYOUT]
    assert len(paths) == len(set(paths))
    assert [e.path for e in layout.LAYOUT if e.versioned] == ["apps/"]
    assert all(e.private for e in layout.LAYOUT if e.kind in ("settings", "system", "uploads", "backups", "logs"))
    assert layout.backed_up_folders() == ["apps", "config", "platform", "files", "sites"]                                   # backups and logs are never inside a backup


def test_the_backup_uses_exactly_the_layouts_list(quick, tmp_path):
    raw, _ = ops._unseal(ops.create_encrypted_backup(quick, "a backup password!").read_bytes(), "a backup password!")
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as t:
        tops = {n.split("/")[0] for n in t.getnames()}
    assert tops <= set(layout.backed_up_folders()) | {"README.md", ".gitignore"} and {"apps", "config", "platform"} <= tops
    assert ops.RESTORE_TOP == set(layout.backed_up_folders()) | {"README.md", ".gitignore"}


# ============================== private by default ==============================
def test_everything_except_code_is_owner_only_from_the_first_minute(quick):
    for d in ("config", "platform", "backups", "logs"):
        assert mode(quick.root / d) & 0o077 == 0, d
    assert mode(quick.root / "platform" / "companies") & 0o077 == 0
    for f in [quick.root / "platform" / "control.db", quick.root / "platform" / "master.key", quick.root / "platform" / "control_plane.json", *(quick.root / "platform" / "companies").glob("*.db")]:
        assert mode(f) == 0o600, f                                                                                         # password hashes and keys: nobody else on the machine can read them
    assert mode(quick.root / "apps") & 0o005                                                                               # code stays normal


def test_loose_permissions_are_reported_and_repaired_and_the_repair_is_idempotent(quick):
    for p in (quick.root / "platform", quick.root / "config"):
        os.chmod(p, 0o755)
    os.chmod(quick.root / "platform" / "control.db", 0o644)
    wal = quick.root / "platform" / "control.db-wal"
    wal.write_bytes(b"x"); os.chmod(wal, 0o644)
    warns = [f for f in layout.check(quick) if f["severity"] == "warn"]
    assert len(warns) == 3 and any("control.db" in f["message"] for f in warns) and all(f["fix"] == "velora layout --fix" for f in warns)
    changed = layout.secure(quick)
    assert "platform/ -> 700" in changed and "platform/control.db -> 600" in changed and "platform/control.db-wal -> 600" in changed     # the journal files too: they contain recent data
    assert layout.secure(quick) == [] and [f for f in layout.check(quick) if f["severity"] == "warn"] == []


# ============================== version control can never publish a secret ==============================
@pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")
def test_git_add_everything_stages_only_the_code_and_two_documents(quick):
    (quick.root / "files" / "COMP-001").mkdir(parents=True)
    (quick.root / "files" / "COMP-001" / "contract.pdf").write_bytes(b"customer data")
    (quick.root / "backups" / "x.vbackup").write_bytes(b"backup")
    (quick.root / "some_new_folder").mkdir(); (quick.root / "some_new_folder" / "secret.txt").write_text("a folder added later")
    (quick.root / ".env").write_text("TOKEN=abc")
    run = lambda *a: subprocess.run(["git", "-C", str(quick.root), *a], capture_output=True, text=True)       # noqa: E731
    run("init", "-q"); run("add", "-A")
    staged = run("ls-files").stdout.split()
    assert "README.md" in staged and ".gitignore" in staged and any(s.startswith("apps/") for s in staged)
    forbidden = [s for s in staged if s.startswith(("platform/", "files/", "backups/", "config/", "logs/", "some_new_folder/")) or s.endswith((".key", ".db", ".env"))]
    assert forbidden == []                                                                                                 # master.key, the databases, uploads, backups and even a folder added later


def test_the_old_default_gitignore_is_reported_as_dangerous(tmp_path):
    ws = legacy_workspace(tmp_path)
    assert any("master.key" in f["message"] and f["severity"] == "warn" for f in layout.check(ws))


# ============================== older installations move on by themselves ==============================
def test_an_older_workspace_keeps_working_before_it_is_migrated(tmp_path):
    ws = legacy_workspace(tmp_path)
    assert Workspace.is_workspace(ws.root) and ws.apps() == ["starter"] and ws.common_config()["auto_upgrade"] is True
    ws.register_app("shop")
    ws.update_config(developer_mode=True)
    assert (ws.root / "sites" / "apps.txt").read_text() == "starter\nshop\n" and not (ws.root / "config" / "apps.txt").exists()      # it writes where the file IS
    assert ws.common_config()["developer_mode"] is True


def test_tidy_moves_the_settings_once_removes_the_empty_folder_and_never_overwrites(tmp_path):
    ws = legacy_workspace(tmp_path)
    done = layout.tidy(ws)
    assert [d for d in done if d.startswith("moved")] == ["moved sites/apps.txt -> config/apps.txt", "moved sites/common_site_config.json -> config/common.json",
                                                         "moved sites/lifecycle_log.json -> config/lifecycle.json"]
    assert "removed the empty sites/ folder" in done and not (ws.root / "sites").exists()
    assert ws.apps() == ["starter"] and ws.common_config()["auto_upgrade"] is True and ws.apps_file == ws.root / "config" / "apps.txt"
    assert layout.tidy(ws) == [] and layout.check(ws) == []                                                              # idempotent, and now nothing is pending
    (ws.root / "sites").mkdir(); (ws.root / "sites" / "apps.txt").write_text("stale\n")
    assert layout.migrate(ws) == [] and ws.apps() == ["starter"]                                                          # a file already in place is never overwritten


def test_a_legacy_site_folder_with_real_sites_is_never_removed(tmp_path):
    ws = legacy_workspace(tmp_path)
    (ws.root / "sites" / "erp.local").mkdir()
    (ws.root / "sites" / "erp.local" / "site_config.json").write_text("{}")
    layout.tidy(ws)
    assert (ws.root / "sites" / "erp.local" / "site_config.json").exists()


def test_the_readme_and_gitignore_are_refreshed_only_when_they_are_still_the_old_defaults(tmp_path):
    ws = legacy_workspace(tmp_path)
    layout.tidy(ws)
    assert "velora layout" in (ws.root / "README.md").read_text() and "/*" in (ws.root / ".gitignore").read_text()
    mine = legacy_workspace(tmp_path / "second")
    (mine.root / "README.md").write_text("# Our company ERP: notes for the team\n")
    (mine.root / ".gitignore").write_text("node_modules/\n")
    layout.tidy(mine)
    assert (mine.root / "README.md").read_text() == "# Our company ERP: notes for the team\n" and (mine.root / ".gitignore").read_text() == "node_modules/\n"   # a person's edits are sacred


def test_unexpected_folders_are_mentioned_not_touched(quick):
    (quick.root / "my-notes").mkdir()
    f = [x for x in layout.check(quick) if "not part of the layout" in x["message"]]
    assert f and "my-notes" in f[0]["message"] and f[0]["severity"] == "info" and (quick.root / "my-notes").is_dir()


# ============================== the documentation cannot drift ==============================
def test_the_committed_documentation_is_exactly_what_the_table_generates():
    assert (ROOT / "docs" / "file-structure.md").read_text() == layout.render_doc()                                       # change velora/layout.py, then `velora layout --write-docs docs/file-structure.md`


def test_the_generated_readme_names_every_folder_and_the_commands_you_need():
    text = layout.render_readme()
    for e in layout.folders():
        if e.kind != "legacy":
            assert e.path in text
    for command in ("velora start", "velora doctor", "velora ops backup", "velora ops restore-workspace", "velora update", "velora layout"):
        assert command in text
    assert "new-site" not in text and "master.key" in text                                                                   # the old four-command flow is gone


def test_the_doc_page_explains_moving_backing_up_and_what_to_commit():
    doc = layout.render_doc()
    for phrase in ("relocatable", "velora quickstart", "restore-workspace", "version control", "700", "company_files/", "velora layout --fix"):
        assert phrase in doc


# ============================== seeing it and fixing it ==============================
def test_the_layout_command_shows_the_structure_and_fixes_it(tmp_path, quick):
    code, out, _ = cli(quick, "layout")
    assert code == 0 and "apps/" in out and "platform/" in out and "Everything is where it should be." in out
    os.chmod(quick.root / "platform" / "control.db", 0o644)
    code, out, _ = cli(quick, "layout")
    assert code == 1 and "[warn]" in out and "velora layout --fix" in out                                                  # a problem is a non-zero exit (usable in scripts)
    code, out, _ = cli(quick, "layout", "--fix")
    assert code == 0 and "platform/control.db -> 600" in out and mode(quick.root / "platform" / "control.db") == 0o600


def test_the_doctor_reports_the_layout_and_the_upgrade_repairs_an_older_workspace(tmp_path, quick):
    assert "everything is where it should be" in cli(quick, "doctor")[1]
    shutil.move(str(quick.root / "config" / "apps.txt"), str(tmp_path / "apps.txt"))
    (quick.root / "sites").mkdir(); shutil.move(str(tmp_path / "apps.txt"), str(quick.root / "sites" / "apps.txt"))
    assert "should be config/apps.txt" in cli(quick, "layout")[1]
    code, out, err = cli(quick, "upgrade")
    assert (quick.root / "config" / "apps.txt").exists() and not (quick.root / "sites").exists(), err                     # a normal upgrade moved it: nobody had to run anything extra


def test_write_docs_produces_the_committed_file(tmp_path):
    out = tmp_path / "fs.md"
    code, text, _ = cli(Workspace(tmp_path), "layout", "--write-docs", str(out))
    assert code == 0 and out.read_text() == layout.render_doc()
