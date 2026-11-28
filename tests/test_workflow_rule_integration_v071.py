import velora
from velora.permissions import session_as
from velora.rules import save_rule
from velora.workflows import _transition_conditions_match


def test_workflow_transition_uses_named_rule_and_execution_context(site):
    with session_as(velora.Session("approver@example.test", frozenset({"System Manager", "Accounts Manager"}))):
        save_rule({
            "name": "WorkflowHighValueGate",
            "title": "Workflow high value gate",
            "scope": "global",
            "definition": {
                "all": [
                    {"condition": {"field": "grand_total", "operator": ">=", "value": 1000000}},
                    {"condition": {"field": "$user", "operator": "=", "value": "approver@example.test"}},
                    {"condition": {"field": "$roles", "operator": "contains", "value": "Accounts Manager"}},
                ],
            },
        })
        transition = {"rule": "WorkflowHighValueGate"}
        assert _transition_conditions_match(transition, {"grand_total": 1500000}, "Purchase Order")
        assert not _transition_conditions_match(transition, {"grand_total": 500000}, "Purchase Order")
    with session_as(velora.Session("clerk@example.test", frozenset({"Accounts User"}))):
        assert not _transition_conditions_match(
            {"rule": "WorkflowHighValueGate"}, {"grand_total": 1500000}, "Purchase Order"
        )
