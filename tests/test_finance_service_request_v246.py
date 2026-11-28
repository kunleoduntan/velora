import json
from pathlib import Path

def test_finance_service_request_metadata_is_registered_and_has_expected_fields():
    path = Path(__file__).parents[1] / "apps/velora_erp/velora_erp/finance/doctype/finance_service_request/finance_service_request.json"
    meta = json.loads(path.read_text())
    assert meta["name"] == "Finance Service Request"
    fields = {f["fieldname"]: f for f in meta["fields"]}
    assert {"requester", "request_type", "business_purpose", "requested_amount", "request_status", "linked_transaction"} <= set(fields)
    assert "Finance Manager" in {p["role"] for p in meta["permissions"]}

def test_finance_erequest_is_in_operational_centre_inbox():
    from velora.api.operational_centre import QUEUES
    finance_requests = [q for q in QUEUES if q[1] == "Finance Service Request"]
    assert len(finance_requests) == 2
    assert finance_requests[0][2] == "Finance eRequests awaiting review"
    assert finance_requests[0][3] == {"request_status": "Submitted"}
    assert finance_requests[1][2] == "Finance eRequests awaiting approval"
    assert finance_requests[1][3] == {"request_status": "Pending Approval"}

def test_finance_erequest_is_not_a_posting_document():
    path = Path(__file__).parents[1] / "apps/velora_erp/velora_erp/finance/doctype/finance_service_request/finance_service_request.py"
    source = path.read_text()
    assert "post_financial_transaction" not in source
    assert "post_financial_transaction(" not in source
    assert "Converted" in source
