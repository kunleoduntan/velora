import json
import pytest
from velora import ai
from velora.exceptions import ValidationError


def test_native_transport_is_injectable_and_canonical(monkeypatch):
    seen = {}
    def fake(config, messages, system, tools, timeout):
        seen.update(config=config, messages=messages, system=system, tools=tools, timeout=timeout)
        return {"content": "", "tool_calls": [{"id": "call-1", "name": "doctype.list", "arguments": {}}]}
    monkeypatch.setattr(ai, "NATIVE_TOOL_TRANSPORT", fake)
    result = ai.ask_with_native_tools({"provider_type": "openai", "model": "mock"},
        [{"role": "user", "content": "List doctypes"}], "system", [{"name": "doctype.list"}], 120)
    assert result["tool_calls"][0]["name"] == "doctype.list"
    assert seen["timeout"] == 90


def test_native_transport_rejects_invalid_adapter_shape(monkeypatch):
    monkeypatch.setattr(ai, "NATIVE_TOOL_TRANSPORT", lambda *a: {"content": "bad", "tool_calls": "not-a-list"})
    with pytest.raises(ValidationError):
        ai.ask_with_native_tools({"provider_type": "openai", "model": "mock"}, [], "", [], 10)


def test_native_provider_adapter_supports_all_configured_provider_types():
    import inspect
    source = inspect.getsource(ai._native_tool_transport)
    for provider in ("openai", "openai_compatible", "azure_openai", "anthropic"):
        assert provider in source
    assert "functionDeclarations" in source
    assert "tool_use" in source
    assert '"tool_calls"' in source


def test_native_tool_api_route_is_registered():
    from velora.api.app import create_app
    app = create_app(auto_init=False)
    assert "/api/ai/agents/{agent_key}/execute-native" in {r.path for r in app.routes}
