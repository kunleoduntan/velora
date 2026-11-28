import pytest
from fastapi.testclient import TestClient

from velora.api import create_app

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
SALES = {"X-Velora-User": "sam", "X-Velora-Roles": "Sales User"}


@pytest.fixture
def client(site):
    return TestClient(create_app(auto_init=False))


def test_branding_read_and_role_restrictions(client):
    response = client.get("/api/application-branding", headers=ADMIN)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["branding"]["app_name"] == "Velora"
    assert data["can_edit"] is True
    assert data["available_doctypes"]
    denied = client.put("/api/application-branding", headers=SALES, json={"app_name": "Acme"})
    assert denied.status_code == 403


def test_branding_saves_identity_and_navigation(client):
    available = client.get("/api/application-branding", headers=ADMIN).json()["data"]["available_doctypes"]
    doctype = available[0]["name"]
    body = {"app_name": "Acme ERP", "tagline": "One connected business", "logo_url": "/assets/acme/logo.svg",
            "favicon_url": "https://example.com/favicon.ico",
            "navigation": [{"label": "Finance", "items": [{"doctype": doctype, "label": "Transactions", "icon": "wallet"}]}]}
    saved = client.put("/api/application-branding", headers=ADMIN, json=body)
    assert saved.status_code == 200
    reread = client.get("/api/application-branding", headers=ADMIN).json()["data"]["branding"]
    assert reread == body


@pytest.mark.parametrize("body", [
    {"app_name": "x", "logo_url": "javascript:alert(1)"},
    {"app_name": "x", "logo_url": "//evil.example/logo.svg"},
    {"navigation": [{"label": "Bad", "items": [{"doctype": "Not A Real DocType"}]}]},
    {"navigation": [{"label": "Bad", "items": [{"doctype": "A", "icon": "Wallet!"}]}]},
    {"unknown": "property"},
])
def test_branding_rejects_unsafe_or_invalid_configuration_without_saving(client, body):
    before = client.get("/api/application-branding", headers=ADMIN).json()["data"]["branding"]
    response = client.put("/api/application-branding", headers=ADMIN, json=body)
    assert response.status_code in (403, 422)
    after = client.get("/api/application-branding", headers=ADMIN).json()["data"]["branding"]
    assert after == before
