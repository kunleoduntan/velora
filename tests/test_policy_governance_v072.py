import pytest
import velora
from velora.permissions import session_as
from velora.exceptions import PermissionDenied, ValidationError
from velora.rules import save_rule, get_rule
from velora.policy_governance import (
    save_binding, transition, evaluate, simulate, audit_history, rule_versions, restore_rule
)

def admin(user="Administrator"):
    return velora.Session(user, frozenset({"System Manager"}))

def test_policy_lifecycle_maker_checker_and_restrictive_decision(site):
    with session_as(admin("maker@example.test")):
        save_rule({"name":"PolicyBlockHighAmount","title":"Block high amount","scope":"global",
            "definition":{"condition":{"field":"amount","operator":">","value":100}}})
        save_binding({"name":"BlockHighAmount","doctype":"Customer","target_type":"action",
            "target":"write","rule_name":"PolicyBlockHighAmount"})
        transition("BlockHighAmount","submit")
    with session_as(admin("checker@example.test")):
        transition("BlockHighAmount","approve")
        transition("BlockHighAmount","publish")
    with session_as(velora.Session("clerk@example.test", frozenset({"Accounts User"}))):
        assert evaluate("Customer","action","write",{"amount":150}) is True
        assert evaluate("Customer","action","write",{"amount":50}) is False
    with session_as(admin()):
        assert any(x["event"]=="publish" for x in audit_history("BlockHighAmount"))

def test_policy_simulation_is_read_only_and_explains_each_policy(site):
    with session_as(admin()):
        save_rule({"name":"SimRule","title":"Simulation rule","scope":"global",
            "definition":{"condition":{"field":"status","operator":"=","value":"Blocked"}}})
        save_binding({"name":"SimPolicy","doctype":"Customer","target_type":"field","target":"email",
            "rule_name":"SimRule"})
        transition("SimPolicy","submit")
    with session_as(admin("checker@example.test")):
        transition("SimPolicy","approve"); transition("SimPolicy","publish")
    with session_as(admin()):
        result=simulate({"doctype":"Customer","target_type":"field","target":"email",
            "document":{"status":"Blocked"}})
        assert result["denied"] is True
        assert result["outcomes"][0]["policy"]=="SimPolicy"

def test_rule_history_is_append_only_and_restore_creates_new_version(site):
    with session_as(admin()):
        save_rule({"name":"VersionedPolicyRule","title":"Versioned","scope":"global",
            "definition":{"condition":{"field":"amount","operator":">","value":10}}})
        save_rule({"name":"VersionedPolicyRule","title":"Versioned","scope":"global",
            "definition":{"condition":{"field":"amount","operator":">","value":20}}})
        history=rule_versions("VersionedPolicyRule")
        assert [x["version"] for x in history]==[1]
        restored=restore_rule("VersionedPolicyRule",1)
        assert restored["version"]==3
        assert get_rule("VersionedPolicyRule")["definition"]["condition"]["value"]==10


def test_published_field_and_document_action_policy_enforced(site):
    from velora.permissions import field_access, check_row_policy
    with session_as(admin()):
        save_rule({"name":"HideEmailRule","title":"Hide email","scope":"global",
            "definition":{"condition":{"field":"$user","operator":"=","value":"clerk@example.test"}}})
        save_binding({"name":"HideEmailPolicy","doctype":"Customer","target_type":"field","target":"email",
            "rule_name":"HideEmailRule"})
        save_rule({"name":"BlockLargeWriteRule","title":"Block large write","scope":"global",
            "definition":{"condition":{"field":"amount","operator":">","value":500}}})
        save_binding({"name":"BlockLargeWritePolicy","doctype":"Customer","target_type":"action","target":"write",
            "rule_name":"BlockLargeWriteRule"})
        transition("HideEmailPolicy","submit")
        transition("BlockLargeWritePolicy","submit")
    with session_as(admin("checker@example.test")):
        for policy in ("HideEmailPolicy","BlockLargeWritePolicy"):
            transition(policy,"approve"); transition(policy,"publish")
    with session_as(velora.Session("clerk@example.test", frozenset({"Accounts User"}))):
        assert field_access("Customer","email") == "hidden"
        with pytest.raises(PermissionDenied,match="action policy"):
            check_row_policy("Customer","write",{"amount":900})
