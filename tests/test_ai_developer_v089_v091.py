import json
import pytest
from velora import ai
from velora import ai_developer as dev
from velora.permissions import Session, session_as
from velora.exceptions import PermissionDenied, ValidationError


def _provider(monkeypatch, response):
    monkeypatch.setenv("VELORA_DEV_AI_KEY", "test-secret")
    ai.save_provider({"name":"Dev test provider","provider_type":"openai","model":"test-model","secret_env":"VELORA_DEV_AI_KEY","priority":1})
    monkeypatch.setattr(ai, "TRANSPORT", lambda *args: response)


def test_ai_generated_doctype_is_validated_but_not_persisted(site, monkeypatch):
    definition = {"name":"AI Generated Register","module":"Demo","fields":[{"fieldname":"title","fieldtype":"Data","required":True}],
                 "permissions":[{"role":"System Manager","read":True,"write":True,"create":True}]}
    with session_as(Session("Administrator", frozenset({"System Manager","Developer"}))):
        _provider(monkeypatch, json.dumps(definition))
        result = dev.generate_doctype("A simple register with a required title", "velora_demo", "Demo")
        assert result["valid"] is True
        assert result["persisted"] is False
        assert json.loads(result["json"])["fields"][0]["fieldname"] == "title"
        assert "AI Generated Register" not in [d.name for d in __import__('velora.meta.registry',fromlist=['registry']).registry.all()]


def test_ai_generated_python_code_is_syntax_checked_and_never_executed(site, monkeypatch):
    with session_as(Session("Administrator", frozenset({"Developer"}))):
        _provider(monkeypatch, "def calculate_total(lines):\n    return sum(line['amount'] for line in lines)")
        result = dev.generate_code("Write a safe total helper", "python", "server")
        assert result["syntax_validated"] is True
        assert result["executed"] is False
        with pytest.raises(ValidationError, match="dynamic execution"):
            monkeypatch.setattr(ai, "TRANSPORT", lambda *args: "exec('import os')")
            dev.generate_code("bad", "python")


def test_database_inspection_and_permission_aware_doctype_query_are_read_only(site):
    from velora.document import new_doc
    with session_as(Session("Administrator", frozenset({"System Manager"}))):
        new_doc("Customer", customer_name="Query Customer").insert()
        info = dev.inspect_database()
        assert info["read_only"] is True
        assert any(x["doctype"] == "Customer" for x in info["tables"])
        result = dev.query_database("Customer", ["name", "customer_name"], limit=10)
        assert result["read_only"] is True and result["permission_checked"] is True
        assert result["row_count"] == 1
        with pytest.raises(Exception):
            dev.query_database("Customer; DELETE FROM tab_customer", ["name"])


def test_ai_document_operations_require_preview_and_confirmation_and_only_touch_drafts(site):
    with session_as(Session("Administrator", frozenset({"System Manager"}))):
        plan = dev.preview_document_operation("create_draft", "Customer", {"customer_name":"AI Draft Customer"})
        assert plan["requires_human_confirmation"] is True
        assert plan["will_submit"] is False and plan["will_post"] is False
        with pytest.raises(PermissionDenied):
            dev.execute_document_operation(plan["confirmation_token"], False)
        result = dev.execute_document_operation(plan["confirmation_token"], True)
        assert result["completed"] and result["docstatus"] == 0
        update_plan = dev.preview_document_operation("update_draft", "Customer", {"status":"Inactive"}, result["document"])
        dev.execute_document_operation(update_plan["confirmation_token"], True)
        delete_plan = dev.preview_document_operation("delete_draft", "Customer", {}, result["document"], "test cleanup")
        deleted = dev.execute_document_operation(delete_plan["confirmation_token"], True)
        assert deleted["completed"] is True


def test_ai_document_operation_token_is_actor_bound_and_one_time(site):
    with session_as(Session("Administrator", frozenset({"System Manager"}))):
        plan = dev.preview_document_operation("create_draft", "Customer", {"customer_name":"Bound Token"})
    with session_as(Session("other", frozenset({"System Manager"}))):
        with pytest.raises(PermissionDenied, match="previewed"):
            dev.execute_document_operation(plan["confirmation_token"], True)
    with session_as(Session("Administrator", frozenset({"System Manager"}))):
        result = dev.execute_document_operation(plan["confirmation_token"], True)
        assert result["completed"]
        with pytest.raises(ValidationError, match="invalid, expired or already used"):
            dev.execute_document_operation(plan["confirmation_token"], True)


def test_command_advisor_only_returns_approved_velora_commands(site, monkeypatch):
    with session_as(Session("Administrator", frozenset({"Developer"}))):
        _provider(monkeypatch, json.dumps({"explanation":"Preview first.","commands":["velora migrate --dry-run", "rm -rf /"]}))
        result = dev.suggest_commands("Preview migration")
        assert result["commands"] == ["velora migrate --dry-run"]
        assert result["executed"] is False


def test_agent_tool_allowlist_and_role_gate(site):
    with session_as(Session("Administrator", frozenset({"AI Developer"}))):
        saved = dev.save_agent({"agent_key":"test_dev_agent","title":"Test Developer","instructions":"Help safely.",
                                "roles":["Developer"],"tools":["doctype.generate","database.query_readonly"]})
        assert saved["agent_key"] == "test_dev_agent"
        with pytest.raises(ValidationError, match="unsupported tool"):
            dev.save_agent({"agent_key":"bad_dev_agent","title":"Bad","instructions":"No","tools":["shell.execute"]})
        with pytest.raises(ValidationError, match="unsupported tool"):
            dev.save_agent({"agent_key":"bad_shape_agent","title":"Bad shape","instructions":"No","tools":[{"shell":"execute"}]})
    with session_as(Session("reader", frozenset({"Accounts User"}))):
        assert not any(x["agent_key"] == "test_dev_agent" for x in dev.list_agents())
