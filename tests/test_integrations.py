import os
from datetime import timedelta

import pytest

from velora import integration_engine as ie
from velora.document.document import now
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import Session, session_as


def test_api_key_is_shown_once_and_revocable(site):
    key = ie.issue_api_key("Nightly import", ["read", "write"])
    assert key["api_key"].startswith("vla_")
    assert "api_key" not in ie.list_api_keys()[0]
    assert ie.authenticate_api_key(key["api_key"], "read")["label"] == "Nightly import"
    assert ie.authenticate_api_key(key["api_key"], "write")
    assert ie.revoke_api_key(key["id"])
    assert ie.authenticate_api_key(key["api_key"], "read") is None


def test_api_key_scope_is_enforced(site):
    key = ie.issue_api_key("Read only", ["read"])
    with pytest.raises(PermissionDenied):
        ie.authenticate_api_key(key["api_key"], "write")


def test_api_key_expiry(site):
    key = ie.issue_api_key("Expired", ["read"], now() - timedelta(seconds=1))
    assert ie.authenticate_api_key(key["api_key"], "read") is None


def test_provider_adapter_registration(site):
    ie.register_provider("SMS", lambda recipient, message, config: {"id": "provider-1"})
    assert ie.send_message("SMS", "+2348000000000", "Sensitive test body")["id"] == "provider-1"
    entries = ie.integration_logs()
    assert entries[0]["status"] == "Sent"
    assert "Sensitive test body" not in entries[0]["summary"]
    with pytest.raises(ValidationError):
        ie.send_message("WHATSAPP", "+2348000000000", "Test")


def test_webhook_requires_master_key(site, monkeypatch):
    monkeypatch.delenv("VELORA_INTEGRATION_MASTER_KEY", raising=False)
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    monkeypatch.setattr(ie, "_public_https", lambda url: url)
    with pytest.raises(ValidationError):
        ie.create_webhook("ERP events", "https://example.com/hook", ["invoice.created"])


def test_webhook_secret_is_encrypted_and_queue_is_company_local(site, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("VELORA_INTEGRATION_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(ie, "_public_https", lambda url: url)
    hook = ie.create_webhook("ERP events", "https://example.com/hook", ["invoice.created"])
    with ie.db.transaction() as c:
        stored = c.execute(ie._hooks.select().where(ie._hooks.c.id == hook["id"])).mappings().one()
    assert "secret" not in stored
    assert stored["secret_ciphertext"] != hook["secret"]
    assert ie.enqueue_event("invoice.created", {"name": "INV-001"}) == 1
    with ie.db.transaction() as c:
        job = c.execute(ie._queue.select()).mappings().one()
    assert job["payload"]["name"] == "INV-001"


def test_webhook_can_be_deactivated(site, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("VELORA_INTEGRATION_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(ie, "_public_https", lambda url: url)
    hook = ie.create_webhook("ERP events", "https://example.com/hook", ["invoice.created"])
    assert ie.deactivate_webhook(hook["id"])
    assert ie.enqueue_event("invoice.created", {"name": "INV-002"}) == 0


def test_stuck_webhook_delivery_is_recovered(site, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("VELORA_INTEGRATION_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(ie, "_public_https", lambda url: url)
    hook = ie.create_webhook("ERP events", "https://example.com/hook", ["invoice.created"])
    ie.enqueue_event("invoice.created", {"name": "INV-003"})
    with ie.db.transaction() as c:
        job = c.execute(ie._queue.select()).mappings().one()
        c.execute(ie._queue.update().where(ie._queue.c.id == job["id"]).values(
            status="Sending", claimed_at=now() - timedelta(minutes=20)))
    assert ie.recover_stuck_webhooks() == 1
    with ie.db.transaction() as c:
        job = c.execute(ie._queue.select()).mappings().one()
    assert job["status"] == "Queued"
    assert job["attempts"] == 1


def test_integration_api_key_management_endpoint(site):
    from fastapi.testclient import TestClient
    from velora.api import create_app
    client = TestClient(create_app(auto_init=False))
    headers = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
    response = client.post("/api/integrations/api-keys",
        json={"label": "External reporting", "scopes": ["read", "reports"]}, headers=headers)
    assert response.status_code == 200
    key = response.json()["data"]
    assert key["api_key"].startswith("vla_")
    listed = client.get("/api/integrations/api-keys", headers=headers).json()["data"]
    assert listed[0]["label"] == "External reporting"
    assert "api_key" not in listed[0]
    revoked = client.delete(f"/api/integrations/api-keys/{key['id']}", headers=headers)
    assert revoked.status_code == 200
