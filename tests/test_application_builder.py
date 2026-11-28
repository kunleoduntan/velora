from fastapi.testclient import TestClient

from velora.api import create_app
from velora.workspace import Workspace


def test_application_builder_creates_scaffold_without_installing(site, tmp_path, monkeypatch):
    ws = Workspace.create(tmp_path / "workspace")
    monkeypatch.setattr(Workspace, "discover", lambda start=None: ws)
    client = TestClient(create_app(auto_init=False))
    headers = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
    response = client.post("/api/devtools/apps", headers=headers,
                           json={"name": "fleet_ops", "module": "Fleet", "title": "Fleet Operations"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["created"] is True
    assert data["installed"] is False
    root = ws.apps_dir / "fleet_ops"
    assert (root / "fleet_ops" / "hooks.py").is_file()
    assert (root / "fleet_ops" / "fleet" / "doctype").is_dir()
    assert "fleet_ops" not in ws.apps()


def test_application_builder_rejects_invalid_names_and_non_managers(site, tmp_path, monkeypatch):
    ws = Workspace.create(tmp_path / "workspace")
    monkeypatch.setattr(Workspace, "discover", lambda start=None: ws)
    client = TestClient(create_app(auto_init=False))
    manager = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
    ordinary = {"X-Velora-User": "user", "X-Velora-Roles": "Sales User"}
    assert client.post("/api/devtools/apps", headers=ordinary, json={"name": "bad-app"}).status_code == 403
    assert client.post("/api/devtools/apps", headers=manager, json={"name": "bad-app"}).status_code == 422
