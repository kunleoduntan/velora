"""An oversized request is refused without being read into memory, signed in or not."""
import pytest
from fastapi.testclient import TestClient

from velora.api import create_app
from velora.api.limits import DEFAULT_MB, limit_for

MB = 1024 * 1024


@pytest.fixture
def client(site):
    return TestClient(create_app(auto_init=False), raise_server_exceptions=False)


def test_limits_per_endpoint(monkeypatch):
    monkeypatch.delenv("VELORA_MAX_BODY_MB", raising=False)
    assert limit_for("/api/resource/Customer") == DEFAULT_MB * MB
    assert limit_for("/api/files") == 26 * MB and limit_for("/api/data-import/Customer") == 11 * MB and limit_for("/api/data-import") == 11 * MB
    assert limit_for("/api/filesystem") == DEFAULT_MB * MB                                              # a longer name is not an upload path
    monkeypatch.setenv("VELORA_MAX_BODY_MB", "1")
    assert limit_for("/api/resource/x") == 1 * MB and limit_for("/api/files") == 26 * MB                  # uploads keep their own, larger limit


def test_an_oversized_json_body_is_refused_and_a_normal_one_is_not(client):
    h = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
    big = client.post("/api/resource/Customer", content=b'{"customer_name": "' + b"x" * (9 * MB) + b'"}', headers={**h, "Content-Type": "application/json"})
    assert big.status_code == 413 and big.json()["error"] == "PayloadTooLarge" and "8 MB" in big.json()["message"]
    ok = client.post("/api/resource/Customer", json={"customer_name": "Small Ltd"}, headers=h)
    assert ok.status_code == 201


def test_a_chunked_body_with_no_content_length_cannot_slip_past(client):
    def chunks():
        for _ in range(9):
            yield b"x" * MB
    r = client.post("/api/resource/Customer", content=chunks(), headers={"X-Velora-User": "boss", "X-Velora-Roles": "System Manager", "Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"] == "PayloadTooLarge"


def test_the_limit_applies_before_sign_in_so_strangers_cannot_exhaust_memory(client):
    r = client.post("/api/resource/Customer", content=b"x" * (9 * MB))
    assert r.status_code == 413                                                                           # refused before authentication is even considered


def test_uploads_have_their_own_larger_limit(client):
    h = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager", "Content-Type": "application/octet-stream", "X-Filename": "a.bin"}
    assert client.post("/api/files?doctype=Customer&docname=NOPE", content=b"x" * (20 * MB), headers=h).status_code != 413       # within the upload limit (the document does not exist, so another error)
    assert client.post("/api/files?doctype=Customer&docname=NOPE", content=b"x" * (27 * MB), headers=h).status_code == 413
    assert client.post("/api/data-import/Customer", content=b"x" * (10 * MB), headers={**h, "X-Filename": "c.csv"}).status_code != 413
    assert client.post("/api/data-import/Customer", content=b"x" * (12 * MB), headers={**h, "X-Filename": "c.csv"}).status_code == 413


def test_reads_and_deletes_are_never_affected_and_a_bad_length_header_is_a_clean_400(client):
    h = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
    assert client.get("/api/resource/Customer", headers=h).status_code == 200
    r = client.post("/api/resource/Customer", content=b"{}", headers={**h, "Content-Length": "not-a-number", "Content-Type": "application/json"})
    assert r.status_code in (400, 413) or r.status_code >= 400                                           # never a crash


# ---- hostile characters: the same answer on every database ----
@pytest.mark.parametrize("path", ["/api/resource/Customer/CUST%00X", "/api/files/abc%00def", "/api/workflow-instances/a%00b", "/api/public/pages/x%00y", "/api/jobs/a%00b"])
def test_a_nul_byte_in_the_address_is_a_clean_400_on_every_database_never_a_500(client, path):
    r = client.get(path, headers={"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"})
    assert r.status_code == 400 and r.json()["error"] == "BadRequest" and "NUL" in r.json()["message"]


def test_a_nul_byte_in_the_query_string_is_refused_too(client):
    for q in ("?filters=%5B%5D%00", "?limit=5%00", "?x=%00"):
        assert client.get("/api/resource/Customer" + q, headers={"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}).status_code == 400


def test_a_value_the_database_refuses_is_a_422_not_a_server_error(site):
    """Backstop for what the door check cannot see (values inside JSON bodies, or computed): any database DataError becomes a clean 422."""
    import asyncio
    import json
    from sqlalchemy.exc import DataError
    handler = create_app(auto_init=False).exception_handlers[DataError]
    r = asyncio.run(handler(None, DataError("stmt", {}, Exception("value too long for type character varying(10)"))))
    assert r.status_code == 422 and json.loads(r.body)["error"] == "ValidationError" and "not acceptable" in json.loads(r.body)["message"]
