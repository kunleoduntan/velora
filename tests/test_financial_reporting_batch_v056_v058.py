from decimal import Decimal
import pytest
from velora_erp.finance.reporting.live_gl_adapter import build_live_gl_extract, LiveGLAccessError, FrappeGLRepository
from velora_erp.finance.reporting.statement_service import assemble_multi_period_statement, FinancialStatementServiceError
from velora_erp.finance.reporting.workbench_service import (validate_report_definition, build_scheduled_report_spec,
    ReportingWorkbenchError)

class Repo:
    def __init__(self, allowed=True, rows=None): self.allowed=allowed; self.rows=rows or []
    def can_read_general_ledger(self, actor, legal_entity): return self.allowed
    def fetch_posted_gl_rows(self, **kwargs): return self.rows

ROWS=[
 {"legal_entity":"ACME","posting_date":"2026-01-01","currency":"NGN","account":"Cash","debit":"100","credit":"0","status":"Posted","source_reference":"JV:1"},
 {"legal_entity":"ACME","posting_date":"2026-01-01","currency":"NGN","account":"Capital","debit":"0","credit":"100","status":"Posted","source_reference":"JV:1"},
]

class FakeDB:
    def get_value(self, doctype, name, field): return "NGN"

class FakeSession:
    user = "Administrator"

class FakeFrappe:
    def __init__(self):
        self.session=FakeSession(); self.db=FakeDB(); self.users=[]
        self.rows=[{"company":"ACME","posting_date":"2026-01-01","account":"Cash",
            "debit":"1","credit":"0","docstatus":1,"voucher_type":"JV","voucher_no":str(i),
            "cost_center":"HQ"} for i in range(501)]
    def set_user(self, user): self.users.append(user); self.session.user=user
    def has_permission(self, *args): return True
    def get_list(self, doctype, filters, fields, start, page_length):
        assert doctype == "GL Entry" and filters["docstatus"] == 1
        return self.rows[start:start+page_length]


def test_live_gl_extract_requires_permission():
    with pytest.raises(LiveGLAccessError):
        build_live_gl_extract(repository=Repo(False, ROWS), actor="guest", legal_entity="ACME", period_from="2026-01-01", period_to="2026-01-31", currency="NGN")

def test_live_gl_extract_is_read_only_and_balanced():
    result=build_live_gl_extract(repository=Repo(True, ROWS), actor="finance@example.com", legal_entity="ACME", period_from="2026-01-01", period_to="2026-01-31", currency="NGN")
    assert result["balanced"] and result["read_only"] and result["posting_side_effects"] is False
    assert result["extraction"]["permission_checked"] is True

def test_live_gl_extract_rejects_bad_dates():
    with pytest.raises(ValueError):
        build_live_gl_extract(repository=Repo(True, ROWS), actor="a", legal_entity="ACME", period_from="2026-02-01", period_to="2026-01-01", currency="NGN")

def test_statement_assembly_requires_balanced_read_only_extract():
    bad={"read_only":True,"balanced":False,"legal_entity":"ACME","currency":"NGN"}
    with pytest.raises(FinancialStatementServiceError):
        assemble_multi_period_statement(template_code="profit_and_loss", mapping={"revenue":["Sales"],"cost_of_sales":["COS"],"operating_expenses":["Opex"],"finance_costs":["Finance"]}, current_extract=bad)

def test_statement_assembly_applies_normal_balance_signs():
    current={"read_only":True,"balanced":True,"legal_entity":"ACME","currency":"NGN",
        "period":{"from_date":"2026-01-01","to_date":"2026-01-31"},
        "accounts":[
            {"account":"Sales","net_debit":Decimal("-100")},
            {"account":"COS","net_debit":Decimal("30")},
            {"account":"Opex","net_debit":Decimal("20")},
            {"account":"Finance","net_debit":Decimal("5")}]}
    mapping={"revenue":["Sales"],"cost_of_sales":["COS"],
        "operating_expenses":["Opex"],"finance_costs":["Finance"]}
    result=assemble_multi_period_statement(template_code="profit_and_loss",mapping=mapping,current_extract=current)
    amounts={row["code"]:row["amount"] for row in result["statement"]["rows"]}
    assert amounts["revenue"] == Decimal("100")
    assert amounts["profit_before_tax"] == Decimal("45")

def test_report_definition_validation():
    cfg={"report_id":"monthly-pl","legal_entity":"ACME","currency":"NGN","period_from":"2026-01-01","period_to":"2026-01-31","report_type":"profit_and_loss","output_format":"pdf"}
    assert validate_report_definition(cfg)["validated"]
    with pytest.raises(ReportingWorkbenchError): validate_report_definition({**cfg,"output_format":"exe"})

def test_schedule_requires_approval_and_valid_timezone():
    cfg={"report_id":"monthly-pl","legal_entity":"ACME","currency":"NGN","period_from":"2026-01-01","period_to":"2026-01-31","report_type":"profit_and_loss","output_format":"pdf"}
    spec=build_scheduled_report_spec(report_definition=cfg,cadence="monthly",timezone="Africa/Lagos",recipients=["finance@example.com"])
    assert spec["enabled"] is False and spec["require_approval"] is True
    with pytest.raises(ReportingWorkbenchError): build_scheduled_report_spec(report_definition=cfg,cadence="monthly",timezone="Africa/Lagos",recipients=["finance@example.com"],require_approval=False)


def test_frappe_adapter_pages_and_restores_session_user():
    fake=FakeFrappe(); repo=FrappeGLRepository(fake)
    assert repo.can_read_general_ledger("finance@example.com", "ACME")
    rows=repo.fetch_posted_gl_rows(actor="finance@example.com", legal_entity="ACME",
        period_from="2026-01-01", period_to="2026-01-31", currency="NGN", dimensions={"cost_center":"HQ"})
    assert len(rows)==501
    assert fake.session.user == "Administrator"
    assert fake.users.count("Administrator") >= 2
