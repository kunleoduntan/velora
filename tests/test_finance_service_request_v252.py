from pathlib import Path

ROOT=Path(__file__).parents[1]

def test_employee_clarification_response_is_not_blocked_by_finance_role_gate():
    source=(ROOT/'velora/api/finance_requests.py').read_text()
    assert 'finance_actions=set(policy["finance_actions"])' in source
    assert 'if action in finance_actions and not _finance(s,policy)' in source
    assert 'doc.requester != emp["name"] or status != "Waiting for Information"' in source

def test_approval_requires_recommendation_amount_and_manager_role():
    source=(ROOT/'velora/api/finance_requests.py').read_text()
    assert 'if not _manager(s,policy)' in source
    assert 'A recommended approved amount is required before approval.' in source
    assert 'status != "Pending Approval"' in source

def test_employee_request_validates_amount_and_currency():
    source=(ROOT/'velora/api/finance_requests.py').read_text()
    assert 'Requested Amount cannot be negative.' in source
    assert 'Currency must be a three-letter code.' in source

def test_frontend_finance_portals_and_routes_are_registered():
    app=(ROOT/'frontend/src/App.tsx').read_text(); router=(ROOT/'frontend/src/router.ts').read_text()
    page=ROOT/'frontend/src/components/FinanceRequestsCentre.tsx'
    assert page.exists()
    assert 'FinanceRequestsCentre mode="finance"' in app
    assert 'FinanceRequestsCentre mode="employee"' in app
    assert 'parts[0] === "finance" && parts[1] === "me"' in router
    assert 'parts[0] === "finance" && parts[1] === "requests"' in router
