"""Publishing to Git from the Desk: the company guard, safe zip handling, a real push to a local repository, and the token never leaking."""
import io
import subprocess
import zipfile

import pytest

from velora import gitpublish
from test_platform import H, PW, clean_state, login, plat  # noqa: F401  (fixtures)

pytestmark = pytest.mark.skipif(not gitpublish.git_available(), reason="git is not installed")


@pytest.fixture
def remote(tmp_path, monkeypatch):
    r = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(r)], check=True, capture_output=True)
    monkeypatch.setattr(gitpublish, "ALLOW_LOCAL_REMOTES", True)
    return r


def _zip(files: dict, wrapper: str | None = None) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, c in files.items():
            z.writestr((wrapper + "/" if wrapper else "") + n, c)
    return b.getvalue()


def _admin(plat):
    c = plat.client()
    assert login(c, "root@example.com").status_code == 200
    return c


def _profile(plat, remote, **over):
    body = {"id": "velora-core", "label": "Velora", "source": "upload", "company_id": plat.A, "repo_url": str(remote), "branch": "main"}
    body.update(over)
    return body


def _save(c, body):
    return c.post("/api/publish/profiles", headers=H, json=body)


def test_only_platform_administrators_can_use_it(plat, remote):
    a = plat.client(); login(a, "alice@example.com")
    assert a.get("/api/publish/profiles", headers=H).status_code in (401, 403)
    assert _save(a, _profile(plat, remote)).status_code in (401, 403)


def test_a_profile_needs_a_company_a_real_repo_address_and_a_sane_branch(plat, remote):
    c = _admin(plat)
    assert _save(c, _profile(plat, remote, company_id="")).status_code == 422
    assert _save(c, _profile(plat, remote, company_id="NOPE")).status_code == 422
    assert _save(c, _profile(plat, remote, repo_url="https://user:pw@github.com/o/r")).status_code == 422       # credentials never go in the address
    assert _save(c, _profile(plat, remote, repo_url="git@github.com:o/r.git")).status_code == 422
    assert _save(c, _profile(plat, remote, branch="../x")).status_code == 422
    assert _save(c, _profile(plat, remote, source="app", app="nope")).status_code == 422
    assert _save(c, _profile(plat, remote)).status_code == 200


def test_the_token_is_stored_encrypted_and_never_returned(plat, remote):
    c = _admin(plat)
    out = _save(c, _profile(plat, remote, token="ghp_supersecrettoken123"))
    assert out.status_code == 200 and out.json()["data"]["has_token"] is True
    assert "ghp_supersecrettoken123" not in out.text
    assert "ghp_supersecrettoken123" not in c.get("/api/publish/profiles", headers=H).text
    assert "ghp_supersecrettoken123" not in (plat.ws.root / "platform" / "publish_profiles.json").read_text()


def test_a_profile_cannot_be_repointed_to_another_company(plat, remote):
    c = _admin(plat)
    assert _save(c, _profile(plat, remote)).status_code == 200
    r = _save(c, _profile(plat, remote, company_id=plat.B))
    assert r.status_code == 422 and "cannot be changed" in r.json()["message"]


def test_upload_then_push_reaches_the_repository(plat, remote, tmp_path):
    c = _admin(plat)
    _save(c, _profile(plat, remote))
    z = _zip({"pyproject.toml": "x", "velora/__init__.py": "v=1", "node_modules/a.js": "no", "velora/__pycache__/a.pyc": "no", ".env": "SECRET=1", "notes.txt": "hi"}, wrapper="velora")
    up = c.post("/api/publish-upload/velora-core", headers={**H, "Content-Type": "application/zip"}, content=z)
    assert up.status_code == 200, up.text
    d = up.json()["data"]
    assert d["files"] == 3 and d["stripped_top_folder"] is True and d["skipped_count"] == 3
    r = c.post("/api/publish/profiles/velora-core/push", headers=H, json={"message": "First"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["new_commit"] is True
    check = tmp_path / "check"
    subprocess.run(["git", "clone", "-q", str(remote), str(check)], check=True)
    files = {p.relative_to(check).as_posix() for p in check.rglob("*") if p.is_file() and ".git/" not in p.as_posix()}
    assert {"pyproject.toml", "velora/__init__.py", "notes.txt", ".gitignore"} <= files
    assert not any("node_modules" in f or f == ".env" or f.endswith(".pyc") for f in files)
    again = c.post("/api/publish/profiles/velora-core/push", headers=H, json={})
    assert again.status_code == 200 and again.json()["data"]["new_commit"] is False          # nothing changed: no empty commit
    z2 = _zip({"pyproject.toml": "x2", "velora/__init__.py": "v=2", "notes.txt": "hi"}, wrapper="velora")
    c.post("/api/publish-upload/velora-core", headers={**H, "Content-Type": "application/zip"}, content=z2)
    assert c.post("/api/publish/profiles/velora-core/push", headers=H, json={"message": "Second"}).json()["data"]["new_commit"] is True
    log = subprocess.run(["git", "-C", str(remote), "log", "--format=%s"], capture_output=True, text=True).stdout.split()
    assert log == ["Second", "First"]                                                            # history kept across uploads


def test_unsafe_zips_are_refused_and_change_nothing(plat, remote):
    c = _admin(plat)
    _save(c, _profile(plat, remote))
    ok = _zip({"a.txt": "1", "b.txt": "2"})
    assert c.post("/api/publish-upload/velora-core", headers={**H, "Content-Type": "application/zip"}, content=ok).status_code == 200
    for bad in (_zip({"../evil.txt": "x"}), _zip({"/abs.txt": "x"})):
        assert c.post("/api/publish-upload/velora-core", headers={**H, "Content-Type": "application/zip"}, content=bad).status_code == 422
    link = io.BytesIO()
    with zipfile.ZipFile(link, "w") as z:
        i = zipfile.ZipInfo("l"); i.create_system = 3; i.external_attr = 0o120777 << 16; z.writestr(i, "/etc/passwd")
    assert c.post("/api/publish-upload/velora-core", headers={**H, "Content-Type": "application/zip"}, content=link.getvalue()).status_code == 422
    assert c.post("/api/publish-upload/velora-core", headers={**H, "Content-Type": "application/zip"}, content=b"not a zip").status_code == 422
    stage = plat.ws.root / "publish" / "velora-core"
    assert sorted(p.name for p in stage.iterdir() if p.name != ".git") == ["a.txt", "b.txt"]       # still the earlier good upload


def test_pushing_an_app_checks_it_belongs_to_the_company(plat, remote):
    c = _admin(plat)
    app = plat.ws.apps_dir / "shop"
    assert app.is_dir()
    assert _save(c, _profile(plat, remote, id="shop-a", source="app", app="shop", company_id=plat.A)).status_code == 200
    ok = c.post("/api/publish/profiles/shop-a/push", headers=H, json={"message": "Shop"})
    assert ok.status_code == 200, ok.text                                                         # shop is installed in company A
    assert ok.json()["data"]["company_check"]["checked"] is True
    # an app that is NOT installed in the profile's company is refused
    plat.plane.router.site_for(plat.plane.registry.get_company(plat.B))
    other = plat.ws.apps_dir / "orphan"; other.mkdir(); (other / "x.txt").write_text("1"); plat.ws.register_app("orphan")
    assert _save(c, _profile(plat, remote, id="orphan-a", source="app", app="orphan", company_id=plat.A)).status_code == 200
    bad = c.post("/api/publish/profiles/orphan-a/push", headers=H, json={})
    assert bad.status_code == 422 and "not installed in" in bad.json()["message"]


def test_a_rejected_push_never_overwrites_the_remote(plat, remote, tmp_path):
    seed = tmp_path / "seed"; seed.mkdir()
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "-c", "user.name=a", "-c", "user.email=a@a", "commit", "-q", "--allow-empty", "-m", "theirs"],
                ["git", "remote", "add", "origin", str(remote)], ["git", "push", "-q", "origin", "main"]):
        subprocess.run(cmd, cwd=seed, check=True)
    c = _admin(plat)
    _save(c, _profile(plat, remote))
    c.post("/api/publish-upload/velora-core", headers={**H, "Content-Type": "application/zip"}, content=_zip({"a.txt": "1"}))
    r = c.post("/api/publish/profiles/velora-core/push", headers=H, json={})
    assert r.status_code == 422 and "Nothing was overwritten" in r.json()["message"]
    assert subprocess.run(["git", "-C", str(remote), "log", "--format=%s"], capture_output=True, text=True).stdout.split() == ["theirs"]


def test_commands_are_generated_with_the_company_named(plat, remote):
    c = _admin(plat)
    _save(c, _profile(plat, remote))
    text = c.get("/api/publish/profiles/velora-core/commands", headers=H).json()["data"]["commands"]
    assert "git push -u origin main" in text and "Velora Technologies" in text and "git add -A" in text


def test_push_writes_an_audit_event_without_the_token(plat, remote):
    c = _admin(plat)
    _save(c, _profile(plat, remote, token="ghp_audit_token_value1"))
    c.post("/api/publish-upload/velora-core", headers={**H, "Content-Type": "application/zip"}, content=_zip({"a.txt": "1"}))
    c.post("/api/publish/profiles/velora-core/push", headers=H, json={})
    from sqlalchemy import select
    from velora.controlplane import models as m
    with plat.plane.engine.connect() as conn:
        rows = conn.execute(select(m.audit.c.event, m.audit.c.detail)).all()
    assert any(e == "publish.push" for e, _ in rows)
    assert "ghp_audit_token_value1" not in str(rows)


def test_the_token_is_scrubbed_from_anything_git_prints(plat, tmp_path):
    pub = gitpublish.Publisher(plat.plane)
    r = pub._git(tmp_path, "-c", "alias.leak=!echo $VELORA_GIT_TOKEN; echo $VELORA_GIT_TOKEN 1>&2", "leak", token="ghp_leaky_token_12345")
    assert "ghp_leaky_token_12345" not in r.stdout + r.stderr and "***" in r.stdout


# ---------------------------------------------------------------- publish on top, and install / update from the repository
def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _seed(remote, tmp_path, files: dict, name="seed"):
    seed = tmp_path / name; seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    for n, c in files.items():
        (seed / n).write_text(c)
    _git(seed, "add", "-A"); _git(seed, "commit", "-q", "-m", "theirs"); _git(seed, "remote", "add", "origin", str(remote)); _git(seed, "push", "-q", "origin", "main")
    return seed


def test_publish_on_top_keeps_their_history_and_makes_the_repository_match_this_copy(plat, remote, tmp_path):
    _seed(remote, tmp_path, {"README.md": "old", "keep.txt": "same"})
    c = _admin(plat)
    _save(c, _profile(plat, remote))
    c.post("/api/publish-upload/velora-core", headers={**H, "Content-Type": "application/zip"}, content=_zip({"a.txt": "1", "keep.txt": "new"}))
    assert c.post("/api/publish/profiles/velora-core/push", headers=H, json={}).status_code == 422      # the plain push is still refused
    cmp = c.get("/api/publish/profiles/velora-core/compare", headers=H).json()["data"]
    assert cmp["remote_exists"] and cmp["added"] == [".gitignore", "a.txt"] and cmp["changed"] == ["keep.txt"] and cmp["removed"] == ["README.md"]
    r = c.post("/api/publish/profiles/velora-core/push", headers=H, json={"message": "Velora 1.19", "on_top": True})
    assert r.status_code == 200, r.text and r.json()["data"]["placed_on_top"] is True
    assert _git(remote, "log", "--format=%s").split("\n")[:2] == ["Velora 1.19", "theirs"], "their commit is still there, ours is after it"
    assert sorted(_git(remote, "ls-tree", "--name-only", "main").split()) == [".gitignore", "a.txt", "keep.txt"]
    # from now on the ordinary push works
    c.post("/api/publish-upload/velora-core", headers={**H, "Content-Type": "application/zip"}, content=_zip({"a.txt": "2", "keep.txt": "new"}))
    assert c.post("/api/publish/profiles/velora-core/push", headers=H, json={"message": "next"}).status_code == 200
    assert _git(remote, "log", "--format=%s").split("\n")[:3] == ["next", "Velora 1.19", "theirs"]
    assert c.get("/api/publish/profiles/velora-core/compare", headers=H).json()["data"]["relation"] == "same"


def _app_repo(remote, tmp_path, name="crm"):
    from velora.scaffold import new_app
    root = new_app(tmp_path / "src", name, module="CRM")
    _git(root, "init", "-q", "-b", "main"); _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "first")
    _git(root, "remote", "add", "origin", str(remote)); _git(root, "push", "-q", "origin", "main")
    return root


def test_install_from_the_repository_then_update_it_forward(plat, remote, tmp_path):
    src = _app_repo(remote, tmp_path)
    c = _admin(plat)
    assert _save(c, _profile(plat, remote, id="crm-a", source="app", app="crm")).status_code == 422          # not on this server, not ticked
    assert _save(c, _profile(plat, remote, id="crm-a", source="app", app="crm", from_repository=True)).status_code == 200
    r = c.post("/api/publish/profiles/crm-a/install", headers=H, json={})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["installed"] == ["crm"] and d["previous"] is None and any("Restart the server" in s for s in d["steps"])
    assert (plat.ws.apps_dir / "crm" / "crm" / "__init__.py").exists() and "crm" in plat.ws.apps()
    assert "crm" in plat.plane.router.site_for(plat.plane.registry.get_company(plat.A)).installed_apps()
    # a new commit in the repository: Update moves forward to it
    (src / "README.md").write_text("v2"); _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "v2"); _git(src, "push", "-q", "origin", "main")
    ur = c.post("/api/publish/profiles/crm-a/install", headers=H, json={})
    assert ur.status_code == 200, ur.text
    u = ur.json()["data"]
    assert u["previous"] != u["commit"] and u["installed"] == [] and (plat.ws.apps_dir / "crm" / "README.md").read_text() == "v2"
    again = c.post("/api/publish/profiles/crm-a/install", headers=H, json={}).json()["data"]
    assert again["changed"] is False and any("already has everything" in s for s in again["steps"])


def test_install_never_overwrites_changes_made_on_this_server(plat, remote, tmp_path):
    src = _app_repo(remote, tmp_path)
    c = _admin(plat)
    _save(c, _profile(plat, remote, id="crm-a", source="app", app="crm", from_repository=True))
    assert c.post("/api/publish/profiles/crm-a/install", headers=H, json={}).status_code == 200
    mine = plat.ws.apps_dir / "crm" / "README.md"
    mine.write_text("edited on the server")
    (src / "README.md").write_text("theirs"); _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "x"); _git(src, "push", "-q", "origin", "main")
    r = c.post("/api/publish/profiles/crm-a/install", headers=H, json={})
    assert r.status_code == 422 and "not in the repository" in r.json()["message"] and r.json()["advice"]["hint"].startswith("Publish them first")
    assert mine.read_text() == "edited on the server"


def test_an_app_folder_never_linked_to_the_repository_is_not_updated_from_it(plat, remote, tmp_path):
    _seed(remote, tmp_path, {"README.md": "x"})
    c = _admin(plat)
    _save(c, _profile(plat, remote, id="shop-a", source="app", app="shop"))
    r = c.post("/api/publish/profiles/shop-a/install", headers=H, json={})
    assert r.status_code == 422 and "not linked to the repository" in r.json()["message"]
    assert "Publish on top of GitHub" in r.json()["advice"]["hint"]


def test_cache_files_left_by_running_the_app_do_not_block_an_update(plat, remote, tmp_path):
    src = _app_repo(remote, tmp_path)
    c = _admin(plat)
    _save(c, _profile(plat, remote, id="crm-a", source="app", app="crm", from_repository=True))
    assert c.post("/api/publish/profiles/crm-a/install", headers=H, json={}).status_code == 200
    cache = plat.ws.apps_dir / "crm" / "crm" / "__pycache__"; cache.mkdir(exist_ok=True); (cache / "x.cpython-313.pyc").write_bytes(b"0")
    (src / "README.md").write_text("v3"); _git(src, "add", "-A"); _git(src, "commit", "-q", "-m", "v3"); _git(src, "push", "-q", "origin", "main")
    r = c.post("/api/publish/profiles/crm-a/install", headers=H, json={})
    assert r.status_code == 200, r.text
    assert (plat.ws.apps_dir / "crm" / "README.md").read_text() == "v3"
