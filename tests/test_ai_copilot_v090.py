import json
from velora import ai, ai_developer as dev
from velora.permissions import Session, session_as


def setup_provider(monkeypatch, response):
    monkeypatch.setenv("VELORA_DEV_AI_KEY", "test-secret")
    ai.save_provider({"name":"Copilot test","provider_type":"openai","model":"test","secret_env":"VELORA_DEV_AI_KEY"})
    monkeypatch.setattr(ai,"TRANSPORT",lambda *args:response)


def test_doctype_json_generator_returns_valid_unpublished_metadata(site, monkeypatch):
    payload={"name":"AI Asset Register","module":"Demo","fields":[{"fieldname":"asset_name","fieldtype":"Data","required":True}],"permissions":[{"role":"System Manager","read":True,"write":True,"create":True}]}
    with session_as(Session("Administrator",frozenset({"Developer"}))):
        setup_provider(monkeypatch,json.dumps(payload))
        out=dev.generate_doctype("An asset register", "velora_demo", "Demo")
        assert out["valid"] and out["persisted"] is False
        assert json.loads(out["json"])["name"]=="AI Asset Register"


def test_code_generator_validates_python_and_never_executes(site, monkeypatch):
    with session_as(Session("Administrator",frozenset({"Developer"}))):
        setup_provider(monkeypatch,"def add(a, b):\n    return a + b")
        out=dev.generate_code("Add two values")
        assert out["syntax_validated"] and out["executed"] is False
