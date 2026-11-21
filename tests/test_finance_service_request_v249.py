import json
from pathlib import Path

def test_finance_request_v249_metadata_has_review_and_approval_audit_fields():
    p=Path(__file__).parents[1]/'apps/velora_erp/velora_erp/finance/doctype/finance_service_request/finance_service_request.json'
    d=json.loads(p.read_text()); fields={x['fieldname']:x for x in d['fields']}
    assert {'approved_amount','clarification_request','clarification_response','recommended_by','approved_by','converted_by','closed_on'} <= set(fields)
    assert fields['approved_amount']['fieldtype']=='Currency'

def test_finance_request_api_routes_are_installed():
    p=Path(__file__).parents[1]/'velora/api/app.py'; s=p.read_text()
    assert 'install_finance_request_routes(app, run)' in s
    module=(p.parent/'finance_requests.py').read_text()
    for route in ['/api/finance/requests','/api/finance/me/requests','/api/finance/requests/{name}/action','/api/finance/requests/analytics']:
        assert route in module

def test_request_conversion_only_links_existing_transactions_and_never_posts():
    s=(Path(__file__).parents[1]/'velora/api/finance_requests.py').read_text()
    assert 'get_doc(doctype,transaction,ignore_permissions=True)' in s
    assert 'new_doc(doctype' not in s
    assert 'post_financial_transaction' not in s
    assert 'policy["transaction_types"]' in s

def test_finance_manager_gate_and_amount_ceiling_are_enforced():
    s=(Path(__file__).parents[1]/'velora/api/finance_requests.py').read_text()
    assert 'if not _manager(s,policy)' in s
    assert 'amount > Decimal(str(doc.requested_amount))' in s
    assert 'status != "Pending Approval"' in s
