from fastapi.testclient import TestClient

from velora.api import create_app

H = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}


def test_a_body_that_names_doctype_does_not_crash_create(site):
    c = TestClient(create_app(auto_init=False), raise_server_exceptions=False)
    r = c.post("/api/resource/Customer", json={"doctype": "Customer", "customer_name": "Zed"}, headers=H)
    assert r.status_code < 500, r.text


def test_audit_case_bodies_never_give_a_server_error(site):
    c = TestClient(create_app(auto_init=False), raise_server_exceptions=False)
    for body in ({}, {"unknown": 1}, {"title": 5}, {"title": "x", "bogus": True}):
        assert c.post("/api/audit/cases", json=body, headers=H).status_code < 500, body
    assert c.put("/api/audit/cases/NOPE", json={"case_id": "x", "zzz": 1}, headers=H).status_code < 500
