"""The Server Console: editing framework and app code, and the database tools, behind a second password check and a full audit trail."""
import json

import pytest

from test_platform import H, PW, clean_state, login, plat  # noqa: F401  (fixtures)
from velora.filemanager import FileManager


@pytest.fixture
def con(plat, tmp_path, monkeypatch):
    from velora import elevation
    elevation._FAILS.clear()
    fw = tmp_path / "fwcode"
    (fw / "sub").mkdir(parents=True)
    (fw / "mod.py").write_text("X = 1\n")
    (fw / "data.json").write_text('{"a": 1}')
    monkeypatch.setattr(FileManager, "framework_path", staticmethod(lambda: fw))
    c = plat.client()
    assert login(c, "root@example.com").status_code == 200
    c.fw, c.plat = fw, plat
    return c


def unlock(c, password=PW):
    r = c.post("/api/console/unlock", json={"password": password}, headers=H)
    return r, ({**H, "X-Velora-Elevation": r.json()["data"]["token"]} if r.status_code == 200 else H)


def test_only_platform_administrators(plat):
    c = plat.client()
    login(c, "alice@example.com")
    for r in (c.get("/api/console/status", headers=H), c.post("/api/console/unlock", json={"password": PW}, headers=H),
              c.get(f"/api/console/db/{plat.A}/tables", headers=H)):
        assert r.status_code in (401, 403)


def test_a_wrong_password_does_not_unlock_and_is_throttled(con):
    for _ in range(5):
        assert con.post("/api/console/unlock", json={"password": "wrong-password"}, headers=H).status_code in (401, 403)
    assert con.post("/api/console/unlock", json={"password": PW}, headers=H).status_code == 403          # even the right one waits
    events = [e["event"] for e in con.plat.plane.engine.connect().exec_driver_sql("select event from cp_audit").mappings()]
    assert "console.unlock_failed" in events


def test_framework_code_can_be_read_but_only_edited_when_unlocked(con):
    assert [e["name"] for e in con.get("/api/filemanager/list", params={"path": "framework"}, headers=H).json()["data"]["entries"]] == ["sub", "data.json", "mod.py"]
    opened = con.get("/api/filemanager/read", params={"path": "framework/mod.py"}, headers=H).json()["data"]
    assert opened["content"] == "X = 1\n" and opened["needs_unlock"] is True
    body = {"path": "framework/mod.py", "content": "X = 2\n", "expected_modified": opened["modified"]}
    assert con.put("/api/filemanager/write", json=body, headers=H).status_code == 403              # not unlocked
    _, h = unlock(con)
    ok = con.put("/api/filemanager/write", json=body, headers=h)
    assert ok.status_code == 200 and ok.json()["data"]["restart_required"] is True
    assert (con.fw / "mod.py").read_text() == "X = 2\n"


def test_a_token_from_another_session_is_useless(con, plat):
    _, h = unlock(con)
    other = plat.client()
    login(other, "root@example.com")
    r = other.put("/api/filemanager/write", json={"path": "framework/mod.py", "content": "X = 3\n"}, headers=h)
    assert r.status_code == 403 and (con.fw / "mod.py").read_text() == "X = 1\n"


def test_broken_python_or_json_is_refused_and_old_versions_can_be_restored(con):
    _, h = unlock(con)
    bad = con.put("/api/filemanager/write", json={"path": "framework/mod.py", "content": "def (:\n"}, headers=h)
    assert bad.status_code in (400, 422) and "Python error" in bad.text
    assert con.put("/api/filemanager/write", json={"path": "framework/data.json", "content": "{nope"}, headers=h).status_code in (400, 422)
    assert con.put("/api/filemanager/write", json={"path": "framework/mod.py", "content": "X = 5\n"}, headers=h).status_code == 200
    versions = con.get("/api/filemanager/history", params={"path": "framework/mod.py"}, headers=H).json()["data"]
    assert len(versions) == 1
    r = con.post("/api/filemanager/restore", json={"path": "framework/mod.py", "version": versions[0]["version"]}, headers=h)
    assert r.status_code == 200 and (con.fw / "mod.py").read_text() == "X = 1\n"


def test_copy_never_replaces_and_framework_files_cannot_be_renamed_or_deleted(con):
    _, h = unlock(con)
    assert con.post("/api/filemanager/copy", json={"path": "framework/mod.py", "to": "framework/mod_copy.py"}, headers=h).status_code == 200
    assert con.post("/api/filemanager/copy", json={"path": "framework/mod.py", "to": "framework/mod_copy.py"}, headers=h).status_code in (400, 422)
    assert con.post("/api/filemanager/rename", json={"path": "framework/mod.py", "new_name": "z.py"}, headers=h).status_code == 403
    assert con.post("/api/filemanager/delete", json={"path": "framework/mod.py"}, headers=h).status_code == 403
    assert (con.fw / "mod.py").exists()
    assert con.post("/api/filemanager/copy", json={"path": "framework/mod.py", "to": "files/mod_backup.py"}, headers=H).status_code == 200      # into your own files: no unlock


def test_edits_are_audited(con):
    _, h = unlock(con)
    con.put("/api/filemanager/write", json={"path": "framework/mod.py", "content": "X = 9\n"}, headers=h)
    rows = [dict(r) for r in con.plat.plane.engine.connect().exec_driver_sql("select event, subject from cp_audit").mappings()]
    assert {"event": "console.unlocked", "subject": "root@example.com"} in rows and {"event": "file.edit", "subject": "framework/mod.py"} in rows


# ---------------------------------------------------------------------------------- database
def sql(c, plat, statement, mode="read", h=H, **extra):
    return c.post(f"/api/console/db/{plat.A}/sql", json={"sql": statement, "mode": mode, **extra}, headers=h)


def test_browse_tables_and_read_sql(con, plat):
    tables = con.get(f"/api/console/db/{plat.A}/tables", headers=H).json()["data"]
    assert "tab_product" in [t["name"] for t in tables]
    page = con.get(f"/api/console/db/{plat.A}/table/tab_product", headers=H).json()["data"]
    assert page["structure"]["primary_key"] == ["name"] and page["data"]["total"] == 0
    r = sql(con, plat, "select count(*) as n from tab_product").json()["data"]
    assert r["columns"] == ["n"] and r["rows"] == [[0]]


@pytest.mark.parametrize("statement", ["select 1; select 2", "copy tab_product to stdout", "create role x", "select load_extension('x')",
                                       "pragma query_only = off", "attach database 'x' as y", "vacuum"])
def test_dangerous_or_multiple_statements_are_refused(con, plat, statement):
    assert sql(con, plat, statement).status_code in (400, 403, 422)


def test_a_changing_statement_cannot_run_as_a_read(con, plat):
    r = sql(con, plat, "delete from tab_product")
    assert r.status_code in (400, 422)
    r = sql(con, plat, "with x as (select 1) delete from tab_product")
    assert r.status_code in (400, 422, 403)


def test_changes_need_the_unlock_then_a_preview_then_the_same_statement(con, plat):
    from velora import new_doc
    with plat.plane.company_scope(plat.A):
        for n in ("P1", "P2", "P3"):
            new_doc("Product", name=n, title=n).insert(ignore_permissions=True)
    stmt = "delete from tab_product where name in ('P1', 'P2')"
    assert sql(con, plat, stmt, "preview").status_code == 403                                      # locked
    _, h = unlock(con)
    prev = sql(con, plat, stmt, "preview", h).json()["data"]
    assert prev["would_affect"] == 2 and prev["kind"] == "preview"
    count = lambda: sql(con, plat, "select count(*) from tab_product").json()["data"]["rows"][0][0]       # noqa: E731
    assert count() == 3                                                                          # the preview changed nothing
    assert sql(con, plat, stmt, "apply", h).status_code in (400, 422)                              # no plan
    assert sql(con, plat, "delete from tab_product", "apply", h, plan=prev["plan"]).status_code in (400, 422)   # a different statement
    done = sql(con, plat, stmt, "apply", h, plan=prev["plan"]).json()["data"]
    assert done["affected"] == 2 and count() == 1
    events = [r["event"] for r in plat.plane.engine.connect().exec_driver_sql("select event from cp_audit").mappings()]
    assert {"db.preview", "db.apply", "db.read"} <= set(events)
    assert list((plat.ws.root / "platform" / "backups").rglob("*"))                                 # a safety backup was taken first


def test_a_stuck_document_can_be_removed_with_its_rows(con, plat):
    from velora import new_doc
    with plat.plane.company_scope(plat.A):
        new_doc("Product", name="STUCK", title="x").insert(ignore_permissions=True)
    url = f"/api/console/db/{plat.A}/document"
    body = {"doctype": "Product", "name": "STUCK", "action": "delete"}
    assert con.post(url, json={**body, "mode": "preview"}, headers=H).status_code == 403
    _, h = unlock(con)
    prev = con.post(url, json={**body, "mode": "preview"}, headers=h).json()["data"]
    assert con.post(url, json={**body, "mode": "apply", "plan": prev["plan"], "confirm": "nope"}, headers=h).status_code in (400, 422)       # name must be typed
    assert con.post(url, json={**body, "mode": "apply", "plan": prev["plan"], "confirm": "STUCK"}, headers=h).status_code == 200
    assert sql(con, plat, "select count(*) from tab_product where name = 'STUCK'").json()["data"]["rows"] == [[0]]


def test_the_console_can_be_switched_off(con, monkeypatch):
    monkeypatch.setenv("VELORA_SERVER_CONSOLE", "off")
    assert con.get("/api/console/status", headers=H).status_code == 403
    assert con.post("/api/filemanager/copy", json={"path": "framework/mod.py", "to": "framework/q.py"}, headers=H).status_code == 403
