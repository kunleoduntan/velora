import pytest
from fastapi.testclient import TestClient
from velora.live_dashboard import create_dashboard_app

def test_dashboard_requires_long_token(monkeypatch, tmp_path):
    monkeypatch.delenv("VELORA_OPS_DASHBOARD_TOKEN", raising=False)
    with pytest.raises(RuntimeError): create_dashboard_app(type("W", (), {"root":tmp_path})(), token="short")

def test_dashboard_rejects_unauthorized_requests(tmp_path):
    ws=type("W", (), {"root":tmp_path})()
    client=TestClient(create_dashboard_app(ws, token="a"*32))
    assert client.get("/api/ops").status_code == 401

def test_dashboard_serves_authenticated_html(tmp_path):
    ws=type("W", (), {"root":tmp_path})()
    client=TestClient(create_dashboard_app(ws, token="b"*32))
    response=client.get("/", headers={"Authorization":"Bearer "+"b"*32})
    assert response.status_code == 200 and "Live Operations" in response.text
