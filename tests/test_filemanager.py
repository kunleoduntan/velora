"""The file explorer: the safety rules (nothing outside the four folders, no secrets, no symbolic links, no path tricks) and the operations."""
import os

import pytest

from velora.exceptions import PermissionDenied, ValidationError
from velora.filemanager import FileManager, MAX_EDIT_BYTES


@pytest.fixture
def fm(tmp_path):
    ws = tmp_path / "srv" / "workspace"
    for d in ("apps", "files", "backups", "logs", "platform", "config"):
        (ws / d).mkdir(parents=True)
    (ws / "platform" / "master.key").write_text("KEY")
    (ws / "config" / "common.json").write_text("{}")
    (tmp_path / "srv" / ".db-root-password").write_text("rootpw")
    (ws / "apps" / "shop").mkdir()
    (ws / "apps" / "shop" / "hooks.py").write_text("app_name = 'shop'\n")
    (ws / "files" / "note.txt").write_text("hello")
    (ws / "backups" / "b1.vbackup").write_bytes(b"\x00\x01binary")
    (ws / "logs" / "velora.log").write_text("line\n")
    m = FileManager(ws)
    m.ws = ws
    return m


# ---- what may be reached -----------------------------------------------------------------------------------------------------------------
def test_root_lists_only_the_known_folders(fm):
    assert [e["name"] for e in fm.list("")["entries"]] == ["apps", "files", "backups", "logs", "framework", "installed"]


@pytest.mark.parametrize("path", ["platform", "platform/master.key", "config", "config/common.json", "..", "../.db-root-password", "apps/../platform/master.key", "apps/..",
                                   "/etc/passwd", "~/x", "apps/shop/../../platform", "apps\\..\\platform", "apps/\x00x", "./platform", "apps/./../config"])
def test_everything_else_is_unreachable(fm, path):
    for op in (fm.list, fm.read_text, fm.file_for_download):
        with pytest.raises((PermissionDenied, ValidationError)):
            op(path)


@pytest.mark.parametrize("name", [".env", ".env.production", "server.key", "cert.pem", "db_password.txt", "my-secret.json", "id_rsa", "credentials.json", ".pgpass", "x.p12"])
def test_secret_looking_files_are_never_listed_opened_or_created(fm, name):
    (fm.ws / "apps" / "shop" / name).write_text("hidden")
    assert name not in [e["name"] for e in fm.list("apps/shop")["entries"]]
    with pytest.raises(PermissionDenied):
        fm.read_text(f"apps/shop/{name}")
    with pytest.raises(PermissionDenied):
        fm.new_file(f"apps/shop/{name}")
    with pytest.raises(PermissionDenied):
        fm.upload("apps/shop", name, b"x")


def test_a_symbolic_link_cannot_lead_out(fm, tmp_path):
    os.symlink(fm.ws / "platform", fm.ws / "apps" / "sneaky")
    os.symlink(fm.ws / "platform" / "master.key", fm.ws / "files" / "key.txt")
    assert {e["name"]: e["type"] for e in fm.list("apps")["entries"]}["sneaky"] == "link"
    for p in ("apps/sneaky", "apps/sneaky/master.key", "files/key.txt"):
        with pytest.raises(PermissionDenied):
            fm.read_text(p)
    with pytest.raises(PermissionDenied):
        fm.list("apps/sneaky")
    with pytest.raises(PermissionDenied):
        fm.write_text("files/key.txt", "overwrite")
    assert (fm.ws / "platform" / "master.key").read_text() == "KEY"


def test_deleting_a_folder_removes_links_without_following_them(fm):
    outside = fm.ws / "platform"
    (fm.ws / "apps" / "shop" / "link").symlink_to(outside)
    fm.delete("apps/shop", recursive=True)
    assert (outside / "master.key").read_text() == "KEY" and not (fm.ws / "apps" / "shop").exists()


# ---- reading -----------------------------------------------------------------------------------------------------------------------------
def test_read_text_and_binary_and_large(fm):
    assert fm.read_text("files/note.txt")["content"] == "hello"
    with pytest.raises(ValidationError):
        fm.read_text("backups/b1.vbackup")
    (fm.ws / "files" / "big.txt").write_text("x" * (MAX_EDIT_BYTES + 1))
    with pytest.raises(ValidationError):
        fm.read_text("files/big.txt")
    assert fm.file_for_download("backups/b1.vbackup").name == "b1.vbackup"


def test_what_is_editable_depends_on_the_folder(fm):
    by = lambda p: {e["name"]: e for e in fm.list(p)["entries"]}
    assert by("apps/shop")["hooks.py"]["editable"] is True
    assert by("files")["note.txt"]["editable"] is True
    assert by("logs")["velora.log"]["editable"] is False and by("logs")["velora.log"]["can_delete"] is True
    assert by("backups")["b1.vbackup"]["editable"] is False


# ---- changing ----------------------------------------------------------------------------------------------------------------------------
def test_edit_saves_atomically_and_detects_a_concurrent_change(fm):
    opened = fm.read_text("apps/shop/hooks.py")
    out = fm.write_text("apps/shop/hooks.py", "app_name = 'shop2'\n", opened["modified"])
    assert (fm.ws / "apps/shop/hooks.py").read_text() == "app_name = 'shop2'\n"
    with pytest.raises(ValidationError, match="changed"):
        fm.write_text("apps/shop/hooks.py", "stale edit", opened["modified"])
    assert fm.write_text("apps/shop/hooks.py", "ok", out["modified"])["size"] == 2
    assert not [p for p in (fm.ws / "apps/shop").iterdir() if p.name.startswith(".velora-upload-")]


def test_logs_and_backups_cannot_be_edited_or_uploaded_into(fm):
    for folder in ("logs", "backups"):
        with pytest.raises(PermissionDenied):
            fm.upload(folder, "x.txt", b"x")
        with pytest.raises(PermissionDenied):
            fm.mkdir(f"{folder}/new")
    with pytest.raises(PermissionDenied):
        fm.write_text("logs/velora.log", "tampered")


def test_upload_new_refuse_overwrite_unless_asked(fm):
    assert fm.upload("files", "a.bin", b"\x00\x01")["size"] == 2
    with pytest.raises(ValidationError, match="already exists"):
        fm.upload("files", "a.bin", b"new")
    fm.upload("files", "a.bin", b"new", overwrite=True)
    assert (fm.ws / "files" / "a.bin").read_bytes() == b"new"


@pytest.mark.parametrize("name", ["", "..", "a/b", "a\\b", "x" * 201, "a\x00b", "con:x", ".", "trailing."])
def test_bad_names_are_refused(fm, name):
    with pytest.raises((ValidationError, PermissionDenied)):
        fm.upload("files", name, b"x")
    with pytest.raises((ValidationError, PermissionDenied)):
        fm.mkdir(f"files/{name}")


def test_upload_does_not_escape_through_the_name(fm):
    for evil in ("../../platform/master.key", "..%2f..%2fplatform%2fmaster.key", "/etc/cron.d/x"):
        with pytest.raises((ValidationError, PermissionDenied)):
            fm.upload("files", evil, b"pwned")
    assert (fm.ws / "platform" / "master.key").read_text() == "KEY"


def test_new_file_mkdir_rename_delete(fm):
    fm.mkdir("files/docs")
    fm.new_file("files/docs/readme.md", "# hi")
    with pytest.raises(ValidationError):
        fm.new_file("files/docs/readme.md")
    with pytest.raises(ValidationError):
        fm.new_file("files/docs/app.exe")
    assert fm.rename("files/docs/readme.md", "README.md")["path"] == "files/docs/README.md"
    with pytest.raises(ValidationError):
        fm.rename("files/docs/README.md", "../escape.md")
    with pytest.raises(ValidationError, match="not empty"):
        fm.delete("files/docs")
    fm.delete("files/docs", recursive=True)
    assert not (fm.ws / "files" / "docs").exists()


def test_top_level_folders_cannot_be_renamed_or_deleted(fm):
    for p in ("apps", "files", "backups", "logs"):
        with pytest.raises(PermissionDenied):
            fm.delete(p, recursive=True)
        with pytest.raises(ValidationError):
            fm.rename(p, "x")


def test_backups_and_logs_files_can_be_deleted(fm):
    fm.delete("backups/b1.vbackup")
    fm.delete("logs/velora.log")
    assert not (fm.ws / "backups" / "b1.vbackup").exists()
