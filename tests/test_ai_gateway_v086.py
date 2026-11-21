import os
import pytest
from sqlalchemy import select
from velora import db
from velora import ai
from velora.permissions import Session, session_as
from velora.exceptions import PermissionDenied, ValidationError


def test_provider_config_stores_secret_reference_not_secret(site, monkeypatch):
    monkeypatch.setenv("VELORA_TEST_AI_KEY", "never-store-this-secret")
    with session_as(Session("Administrator", frozenset({"System Manager"}))):
        row=ai.save_provider({"name":"Test OpenAI","provider_type":"openai","model":"test-model","secret_env":"VELORA_TEST_AI_KEY","priority":1})
        assert row["credential_configured"] is True
        listed=ai.list_providers()
        assert listed[0]["credential_configured"] is True
        assert "secret_env" not in listed[0]
        assert "never-store-this-secret" not in repr(listed)
        with db.transaction() as conn:
            stored=conn.execute(select(ai.providers)).mappings().first()
        assert stored["secret_env"] == "VELORA_TEST_AI_KEY"
        assert "never-store-this-secret" not in repr(dict(stored))


def test_provider_rejects_inline_secret_and_insecure_remote_endpoint(site):
    with session_as(Session("Administrator", frozenset({"System Manager"}))):
        with pytest.raises(ValidationError, match="environment variable"):
            ai.save_provider({"name":"Bad","provider_type":"openai","model":"m","secret_env":"sk-real-secret"})
        with pytest.raises(ValidationError, match="HTTPS"):
            ai.save_provider({"name":"Bad","provider_type":"openai_compatible","model":"m","secret_env":"VELORA_TEST_KEY","endpoint":"http://example.com/api"})


def test_provider_admin_requires_role(site):
    with session_as(Session("reader", frozenset({"Accounts User"}))):
        with pytest.raises(PermissionDenied):
            ai.save_provider({"name":"No","provider_type":"openai","model":"m","secret_env":"VELORA_TEST_KEY"})
        assert ai.capabilities()["can_manage_providers"] is False


def test_ai_advisor_routes_through_priority_fallback_and_is_advisory(site, monkeypatch):
    monkeypatch.setenv("VELORA_TEST_AI_KEY", "test")
    with session_as(Session("Administrator", frozenset({"System Manager"}))):
        ai.save_provider({"name":"First","provider_type":"openai","model":"m1","secret_env":"VELORA_TEST_AI_KEY","priority":1})
        ai.save_provider({"name":"Second","provider_type":"anthropic","model":"m2","secret_env":"VELORA_TEST_AI_KEY","priority":2})
        ai.register_advisor({"id":"test.finance.advisor","title":"Test Finance Advisor","roles":["Accounts User"],"system_prompt":"Be careful."})
        calls=[]
        def fake(config,prompt,system,timeout):
            calls.append(config["name"])
            if config["name"]=="First": raise RuntimeError("temporary outage")
            return "Review completed with caveats."
        monkeypatch.setattr(ai,"TRANSPORT",fake)
        result=ai.ask("test.finance.advisor","Review this scenario")
        assert calls==["First","Second"]
        assert result["provider"]=="Second"
        assert result["advisory_only"] is True
        with session_as(Session("Administrator", frozenset({"System Manager"}))):
            logs=ai.usage_summary()
            assert logs["total"] == 2
            assert {x["outcome"] for x in logs["items"]} == {"failed", "success"}
            assert all("prompt" not in x and "answer" not in x for x in logs["items"])


def test_ai_advisor_role_gate(site, monkeypatch):
    ai.register_advisor({"id":"restricted.advisor","title":"Restricted","roles":["Finance Manager"]})
    with session_as(Session("user", frozenset({"Accounts User"}))):
        with pytest.raises(PermissionDenied):
            ai.ask("restricted.advisor","Can you help?")


def test_provider_endpoint_rejects_embedded_credentials_and_query_secrets(site):
    with session_as(Session("Administrator", frozenset({"System Manager"}))):
        for endpoint in ("https://user:pass@example.com/v1", "https://example.com/v1?api_key=leak"):
            with pytest.raises(ValidationError, match="credentials|API keys"):
                ai.save_provider({"name":"Unsafe","provider_type":"openai_compatible","model":"m","secret_env":"VELORA_TEST_KEY","endpoint":endpoint})


def test_advisor_context_allowlist_rejects_sensitive_fields(site):
    with pytest.raises(ValidationError, match="Sensitive fields"):
        ai.register_advisor({"id":"test.sensitive.advisor","context_fields":["email","grand_total"]})
