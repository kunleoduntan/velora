import json
from pathlib import Path

ROOT=Path(__file__).parents[1]

def test_policy_metadata_carries_all_business_configuration_without_embedded_values():
    p=ROOT/"apps/velora_erp/velora_erp/finance/doctype/finance_request_policy/finance_request_policy.json"
    meta=json.loads(p.read_text()); fields={f["fieldname"]:f for f in meta["fields"]}
    required={"enabled","default_currency","finance_roles","manager_roles","request_types","priorities","transaction_types","approval_rules","finance_actions","workflow_definition"}
    assert required <= set(fields)
    request=json.loads((ROOT/"apps/velora_erp/velora_erp/finance/doctype/finance_service_request/finance_service_request.json").read_text())
    by_name={f["fieldname"]:f for f in request["fields"]}
    assert by_name["request_type"]["options"] == []
    assert by_name["priority"]["options"] == []

def test_finance_request_api_uses_policy_for_roles_types_priorities_currency_and_transactions():
    s=(ROOT/"velora/api/finance_requests.py").read_text()
    for token in ["_policy(","policy[\"finance_roles\"]","policy[\"manager_roles\"]","policy[\"request_types\"]","policy[\"priorities\"]","policy[\"transaction_types\"]","_approval_roles(policy"]:
        assert token in s
    assert 'or "NGN"' not in s
    assert 'FINANCE_ROLES =' not in s and 'MANAGER_ROLES =' not in s

def test_approval_thresholds_are_loaded_from_configured_rules():
    s=(ROOT/"velora/api/finance_requests.py").read_text()
    assert 'rule.get("minimum_amount",0)' in s
    assert 'rule.get("maximum_amount")' in s
    assert 'approver_roles' in s
    assert 'No unique approval rule covers this request amount.' in s
    assert 'workflow_start(policy["workflow_definition"]' in s
    assert 'workflow_act(doc.workflow_instance,"Approve"' in s
