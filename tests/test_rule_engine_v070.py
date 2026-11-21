from types import SimpleNamespace
import pytest

import velora
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import session_as
from velora.rules import (
    evaluate_definition, save_rule, get_rule, list_rules, delete_rule,
    evaluate_saved_rule, validate_definition,
)

ADMIN = SimpleNamespace(user="Administrator", roles=frozenset({"System Manager"}))


def test_rule_engine_nested_boolean_and_numeric_comparison():
    rule = {"all": [
        {"condition": {"field": "amount", "operator": ">", "value": 100}},
        {"any": [
            {"condition": {"field": "department", "operator": "=", "value": "Finance"}},
            {"condition": {"field": "urgent", "operator": "=", "value": True}},
        ]},
    ]}
    assert evaluate_definition(rule, {"amount": "150.00", "department": "Finance"})
    assert evaluate_definition(rule, {"amount": 150, "urgent": True})
    assert not evaluate_definition(rule, {"amount": 50, "urgent": True})
    assert not evaluate_definition(rule, {"amount": 150, "department": "Sales", "urgent": False})


def test_rule_context_and_string_operators():
    rule = {"all": [
        {"condition": {"field": "$user", "operator": "=", "value": "approver@example.test"}},
        {"condition": {"field": "reference", "operator": "starts_with", "value": "PO-"}},
        {"condition": {"field": "tags", "operator": "contains", "value": "urgent"}},
    ]}
    assert evaluate_definition(rule, {"reference": "PO-0001", "tags": ["urgent"]},
                               {"user": "approver@example.test"})
    assert not evaluate_definition(rule, {"reference": "INV-1", "tags": ["urgent"]},
                                   {"user": "approver@example.test"})


@pytest.mark.parametrize("bad", [
    {"condition": {"field": "amount", "operator": "python", "value": 1}},
    {"condition": {"field": "__class__", "operator": "=", "value": "x"}},
    {"all": []},
    {"condition": {"field": "amount", "operator": ">", "value": 1, "execute": "os.system('id')"}},
    {"call": "open('/etc/passwd')"},
])
def test_rule_rejects_unsafe_or_malformed_definitions(bad):
    with pytest.raises(ValidationError):
        validate_definition(bad)


def test_rule_complexity_limit():
    nested = {"condition": {"field": "amount", "operator": ">", "value": 1}}
    for _ in range(14):
        nested = {"not": nested}
    with pytest.raises(ValidationError, match="complexity"):
        validate_definition(nested)


def test_persisted_rule_versions_and_evaluation(site):
    with session_as(velora.Session("Administrator", frozenset({"System Manager"}))):
        first = save_rule({
            "name": "HighValuePurchase", "title": "High Value Purchase",
            "scope": "global", "definition": {
                "condition": {"field": "grand_total", "operator": ">", "value": 500000}
            }
        })
        assert first["version"] == 1
        second = save_rule({
            "name": "HighValuePurchase", "title": "High Value Purchase",
            "scope": "global", "definition": {
                "condition": {"field": "grand_total", "operator": ">=", "value": 500000}
            }
        })
        assert second["version"] == 2
        assert evaluate_saved_rule("HighValuePurchase", {"grand_total": 500000})["matched"] is True
        assert get_rule("HighValuePurchase")["version"] == 2
        assert any(x["name"] == "HighValuePurchase" for x in list_rules())
        assert delete_rule("HighValuePurchase") == {"deleted": "HighValuePurchase"}


def test_rule_administration_is_not_available_to_ordinary_user(site):
    with session_as(velora.Session("clerk@example.test", frozenset({"Accounts User"}))):
        with pytest.raises(PermissionDenied):
            save_rule({"name": "NoAccessRule", "definition": {
                "condition": {"field": "amount", "operator": ">", "value": 1}
            }})
