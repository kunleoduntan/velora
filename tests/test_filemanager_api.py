from urllib.parse import quote

from test_platform import H, PW, clean_state, login, plat  # noqa: F401  (fixtures)


def admin(plat):
    c = plat.client()
    assert login(c, "root@example.com").status_code == 200
    return c


def test_only_platform_administrators_may_use_it(plat):
    anon = plat.client()
    assert anon.get("/api/filemanager/list", headers=H).status_code in (401, 403)
    c = plat.client()
    login(c, "alice@example.com")                                  # a company user, not a platform administrator
    for r in (c.get("/api/filemanager/list", headers=H), c.get("/api/filemanager/read?path=apps", headers=H),
              c.post("/api/filemanager/upload?path=files", content=b"x", headers={**H, "X-Filename": "a.txt"}),
              c.post("/api/filemanager/delete", json={"path": "files/x"}, headers=H)):
        assert r.status_code in (401, 403), r.text


def test_browse_edit_upload_download_rename_delete(plat):
    c = admin(plat)
    root = c.get("/api/filemanager/list", headers=H).json()["data"]
    assert [e["name"] for e in root["entries"]] == ["apps", "files", "backups", "logs", "framework", "installed"]
    up = c.post("/api/filemanager/upload?path=files", content=b"hello world", headers={**H, "X-Filename": quote("my report.txt")})
    assert up.status_code == 200, up.text
    assert up.json()["data"]["path"] == "files/my report.txt"
    opened = c.get("/api/filemanager/read", params={"path": "files/my report.txt"}, headers=H).json()["data"]
    assert opened["content"] == "hello world" and opened["editable"] is True
    saved = c.put("/api/filemanager/write", json={"path": "files/my report.txt", "content": "changed", "expected_modified": opened["modified"]}, headers=H)
    assert saved.status_code == 200
    stale = c.put("/api/filemanager/write", json={"path": "files/my report.txt", "content": "late", "expected_modified": opened["modified"]}, headers=H)
    assert stale.status_code in (400, 422)
    dl = c.get("/api/filemanager/download", params={"path": "files/my report.txt"}, headers=H)
    assert dl.status_code == 200 and dl.content == b"changed" and "attachment" in dl.headers["content-disposition"] and dl.headers["x-content-type-options"] == "nosniff"
    assert c.post("/api/filemanager/rename", json={"path": "files/my report.txt", "new_name": "report.txt"}, headers=H).status_code == 200
    assert c.post("/api/filemanager/mkdir", json={"path": "files/sub"}, headers=H).status_code == 200
    assert c.post("/api/filemanager/new-file", json={"path": "files/sub/a.md", "content": "# x"}, headers=H).status_code == 200
    assert c.post("/api/filemanager/delete", json={"path": "files/sub"}, headers=H).status_code in (400, 422)           # not empty, not confirmed
    assert c.post("/api/filemanager/delete", json={"path": "files/sub", "recursive": True}, headers=H).status_code == 200
    assert c.post("/api/filemanager/delete", json={"path": "files/report.txt"}, headers=H).status_code == 200
    assert not (plat.ws.root / "files" / "report.txt").exists()


def test_the_secrets_are_out_of_reach_over_http(plat):
    c = admin(plat)
    for path in ("platform/master.key", "platform", "config/common.json", "../platform/master.key", "apps/../platform/master.key", "%2e%2e/platform/master.key"):
        for ep in ("read", "download", "list"):
            r = c.get(f"/api/filemanager/{ep}", params={"path": path}, headers=H)
            assert r.status_code in (400, 403, 404, 422), (ep, path, r.status_code)
            assert "KEY" not in r.text and (plat.ws.root / "platform" / "master.key").read_bytes() not in r.content
    up = c.post("/api/filemanager/upload?path=platform", content=b"x", headers={**H, "X-Filename": "evil.txt"})
    assert up.status_code in (400, 403, 422) and not (plat.ws.root / "platform" / "evil.txt").exists()
    up = c.post("/api/filemanager/upload?path=files", content=b"x", headers={**H, "X-Filename": quote("../../platform/evil.txt", safe="")})
    assert up.status_code in (400, 403, 422) and not (plat.ws.root / "platform" / "evil.txt").exists()


def test_changes_are_recorded_in_the_audit_trail(plat):
    from sqlalchemy import select
    from velora.controlplane import models as cpm
    c = admin(plat)
    c.post("/api/filemanager/upload?path=files", content=b"x", headers={**H, "X-Filename": "audit.txt"})
    c.post("/api/filemanager/delete", json={"path": "files/audit.txt"}, headers=H)
    with plat.plane.engine.connect() as conn:
        events = {r[0] for r in conn.execute(select(cpm.audit.c.event))}
    assert {"file.upload", "file.delete"} <= events


def test_an_oversized_upload_is_refused_before_it_is_read(plat):
    from velora.api.limits import limit_for
    assert limit_for("/api/filemanager/upload") > 100 * 1024 * 1024
    assert limit_for("/api/filemanager/write") < 10 * 1024 * 1024
