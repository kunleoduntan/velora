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
