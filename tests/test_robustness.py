"""Hostile-input regression tests found by fuzzing: no route, command or setting may ever answer with a server error / traceback."""
import io
import itertools
import contextlib
import os

import pytest
from fastapi.testclient import TestClient

import velora
from velora import new_doc
from velora.api import create_app
from velora.cli import main
from velora.controlplane import ControlPlane
from velora.workspace import Workspace

H = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
NASTY = [None, [], "str", 123, True, {}, {"filters": "x"}, {"filters": [["a"]]}, {"filters": {"a": 1}}, {"filters": [[1, 2, 3]]}, {"names": "x"}, {"names": [1, 2]}, {"names": {"a": 1}},
         {"columns": "x"}, {"columns": [1]}, {"header": 5}, {"order_by": 5}, {"order_by": ["a"]}, {"action": 5, "names": ["a"]}, {"action": "update", "names": ["CUST-0001"], "values": "x"},
         {"action": "update", "names": ["CUST-0001"], "values": {"customer_name": {"a": 1}}}, {"name": 5, "spec": 5}, {"name": "x", "spec": []}, {"name": "x", "spec": {"doctype": 5}},
         {"doctype": "Customer", "group_by": "status"}, {"doctype": "Customer", "group_by": [["a"]]}, {"doctype": "Customer", "group_by": ["status"], "measures": [5]},
         {"doctype": "Customer", "group_by": ["status"], "measures": [{"fn": "sum", "field": 5}]}, {"doctype": ["x"], "group_by": ["status"]},
         {"doctype": "Customer", "group_by": ["status"], "filters": [[["a"], "=", 1]]}, {"doctype": "Customer", "group_by": ["status"], "filters": [["status", ["="], 1]]},
         {"doctype": "Customer", "group_by": ["status"], "date_field": 5, "date_bucket": 5}, {"preset": 5}, {"preset": ["x"]}, {"preset": "velora", "radius": ["x"]}, {"preset": "velora", "density": {"a": 1}},
         {"preset": "velora", "font": ["x"]}, {"preset": "velora", "default_mode": ["x"]}, {"preset": "velora", "brand": 5}, {"brand_name": 5}, {"filters": {"from_date": [1]}}, {"filters": [1]},
         {"customer_name": {"a": 1}}, {"customer_name": ["a"]}, {"credit_limit": {"a": 1}}, {"credit_limit": "1e999"}, {"contacts": "x"}, {"contacts": [1]}, {"contacts": {"a": 1}},
         {"customer_name": "x" * 50000}, {"customer_name": "\x00null"}, {"customer_name": "'; DROP TABLE tab_customer; --"}, {"modified": "garbage"}, {"modified": 5}, {"docstatus": "x"}]
PARAMS = ["x", "", "CUST-0001", "../../etc/passwd", "%00", "a" * 3000]
QUERY = [{}, {"filters": "x"}, {"filters": "[1]"}, {"filters": '[["a","=",1]]'}, {"filters": '[["name","in","x"]]'}, {"fields": "x"}, {"fields": "[1]"}, {"fields": '["nope"]'},
         {"limit": "x"}, {"limit": "-5"}, {"offset": "x"}, {"order_by": "x y z"}, {"field": "x"}, {"kind": "x"}, {"limit": "99999999999999999999"}]


def route_calls(client, bodies, queries, max_params=6):
    for path, ops in client.get("/openapi.json").json()["paths"].items():
        for method in (m.upper() for m in ops):
            if method not in ("GET", "POST", "PUT", "DELETE"):
                continue
            names = [seg[1:seg.index("}")] for seg in path.replace("{", "|{").split("|") if seg.startswith("{")]
            combos = [dict(zip(names, v)) for v in itertools.islice(itertools.product(PARAMS, repeat=len(names)), max_params)] if names else [{}]
            for pv in combos:
                url = path
                for k, v in pv.items():
                    url = url.replace("{" + k + "}", v.replace("/", "%2F"))
                for q in (queries if method == "GET" else [{}]):
                    for b in (bodies if method in ("POST", "PUT") else [None]):
                        yield method, path, url, q, b


@pytest.mark.parametrize("shard", range(4))
def test_no_api_route_ever_returns_a_server_error_for_hostile_input(site, shard):
    # Split the exhaustive route/body matrix into four deterministic shards. This
    # preserves every request while allowing the suite to run under bounded CI workers.
    for g in ("Retail",):
        new_doc("Customer Group", group_name=g).insert()
    new_doc("Customer", customer_name="Acme", customer_group="Retail", status="Active", credit_limit=100).insert()
    c = TestClient(create_app(auto_init=False), raise_server_exceptions=False)
    bad, n = [], 0
    for index, (method, path, url, q, b) in enumerate(route_calls(c, NASTY, QUERY)):
        if index % 4 != shard:
            continue
        n += 1
        r = c.request(method, url, params=q, json=b, headers=H)
        if r.status_code >= 500:
            bad.append((method, path, r.status_code, str(b)[:80], q))
    assert n > 500 and bad == [], bad[:5]


def test_platform_auth_routes_survive_hostile_input(tmp_path, monkeypatch):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    ws = Workspace.create(tmp_path / "ws")
    plane = ControlPlane.create(ws, admin_email="root@example.com", admin_password="correct horse battery")
    try:
        c = TestClient(create_app(auto_init=False, workspace=ws, plane=plane), raise_server_exceptions=False)
        bodies = [None, [], "x", 5, {}, {"email": 5, "password": 5}, {"email": [], "password": {}}, {"email": "root@example.com", "password": ["x"]},
                  {"email": "root@example.com", "password": "x" * 100000}, {"email": "a" * 5000, "password": "x"}, {"company_id": []}, {"company_id": 5}, {"company_id": "../../x"},
                  {"current_password": 5, "new_password": []}, {"new_password": "x"}, {"email": "root@example.com", "password": "correct horse battery", "return_token": {}}]
        hdrs = [{}, {"Authorization": "Bearer"}, {"Authorization": "Bearer " + "x" * 5000}, {"Authorization": "Basic abc"}, {"X-Velora-Company": "x" * 5000}, {"X-Velora-Request": "1", "Cookie": "velora_session=zzz"}]
        bad = []
        for path, ops in c.get("/openapi.json").json()["paths"].items():
            for m in (x.upper() for x in ops):
                if m not in ("GET", "POST", "PUT", "DELETE"):
                    continue
                url = path.replace("{doctype}", "Customer").replace("{name}", "x").replace("{action}", "submit").replace("{rid}", "SR-x")
                for h in hdrs:
                    for b in (bodies if m in ("POST", "PUT") else [None]):
                        r = c.request(m, url, json=b, headers=h)
                        if r.status_code >= 500:
                            bad.append((m, path, r.status_code, str(b)[:60], str(h)[:40]))
        assert bad == [], bad[:5]
    finally:
        plane.dispose()


def _cli(argv):
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return main(argv), out.getvalue(), err.getvalue()
    except SystemExit as e:                      # argparse usage errors: a clean exit, not a crash
        return e.code, out.getvalue(), err.getvalue()


@pytest.mark.parametrize("argv", [["init", "/proc/nope/ws"], ["start", "--port", "-1"], ["start", "--port", "99999"], ["start", "--port", "abc"], ["init", ""], ["new-site", ""],
                                  ["new-site", "../x"], ["new-app", "A b"], ["install-app", ""], ["get-app", "not a url"], ["get-app", ""], ["tenant", "create", ""],
                                  ["user", "create", "not-an-email", "--password", "x"], ["company", "create", "X", "--tenant", "nope"], ["--site", "x", "migrate"], ["--company", "x", "doctypes"]])
def test_cli_never_prints_a_traceback_for_bad_input(argv, tmp_path, monkeypatch):
    for k in ("VELORA_SITE", "VELORA_WORKSPACE", "VELORA_MASTER_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    code, _, err = _cli(argv)                    # an uncaught exception would propagate and fail this test
    assert code not in (0, None)
    assert "Traceback" not in err
