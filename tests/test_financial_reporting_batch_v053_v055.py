from decimal import Decimal
import pytest
from velora_erp.finance.reporting.gl_integration import extract_gl_reporting_data, drill_down_account, GLIntegrationError
from velora_erp.finance.reporting.statement_templates import get_statement_template, validate_template_mapping, assemble_statement_template, StatementTemplateError
from velora_erp.finance.reporting.dimensional_reporting import build_dimensional_report, reconcile_dimensional_totals, DimensionalReportingError

@pytest.fixture
def ledger():
    return [
      {"legal_entity":"LE1","posting_date":"2026-01-10","status":"Posted","is_posted":True,"currency":"NGN","account":"Cash","debit":"100","credit":"0","source_reference":"JV-1","dimensions":{"branch":"Lagos","department":"Finance","cost_centre":"CC1","business_unit":"Retail","project":"P1","segment":"Local"}},
      {"legal_entity":"LE1","posting_date":"2026-01-10","status":"Posted","is_posted":True,"currency":"NGN","account":"Revenue","debit":"0","credit":"100","source_reference":"SI-1","dimensions":{"branch":"Lagos","department":"Sales","cost_centre":"CC2","business_unit":"Retail","project":"P1","segment":"Local"}},
      {"legal_entity":"LE1","posting_date":"2026-01-10","status":"Draft","currency":"NGN","account":"Cash","debit":"900","credit":"0","source_reference":"DRAFT"},
      {"legal_entity":"LE2","posting_date":"2026-01-10","status":"Posted","currency":"NGN","account":"Cash","debit":"500","credit":"0","source_reference":"OTHER"},
    ]

def test_gl_extract_only_posted_entity_and_period_rows(ledger):
    out=extract_gl_reporting_data(rows=ledger,legal_entity="LE1",period_from="2026-01-01",period_to="2026-01-31",currency="NGN")
    assert out["balanced"] and out["accepted_line_count"]==2
    assert out["excluded_rows"]=={"unposted":1,"entity":1}
    assert out["read_only"] and out["posting_side_effects"] is False

def test_gl_drilldown_retains_refs(ledger):
    out=extract_gl_reporting_data(rows=ledger,legal_entity="LE1",period_from="2026-01-01",period_to="2026-01-31",currency="NGN")
    assert drill_down_account(out,"Cash")["source_refs"]==["JV-1"]

def test_gl_mixed_currency_rejected(ledger):
    ledger[1]["currency"]="USD"
    with pytest.raises(GLIntegrationError): extract_gl_reporting_data(rows=ledger,legal_entity="LE1",period_from="2026-01-01",period_to="2026-01-31",currency="NGN")

def test_gl_missing_source_ref_rejected(ledger):
    ledger[0]["source_reference"]=""
    with pytest.raises(GLIntegrationError): extract_gl_reporting_data(rows=ledger,legal_entity="LE1",period_from="2026-01-01",period_to="2026-01-31",currency="NGN")

def test_gl_account_scope_excludes_unmapped(ledger):
    out=extract_gl_reporting_data(rows=ledger,legal_entity="LE1",period_from="2026-01-01",period_to="2026-01-31",currency="NGN",allowed_accounts=["Cash"])
    assert out["accepted_line_count"]==1 and out["excluded_rows"]["account_scope"]==1

def test_template_catalogue_has_four_statements():
    assert {"profit_and_loss","balance_sheet","cash_flow","changes_in_equity"} <= set(__import__('velora_erp.finance.reporting.statement_templates',fromlist=['TEMPLATES']).TEMPLATES)

def test_template_mapping_requires_every_account_row():
    template=get_statement_template("profit_and_loss")
    with pytest.raises(StatementTemplateError): validate_template_mapping(template,{"revenue":["4000"]})

def test_template_mapping_prevents_duplicate_account():
    template=get_statement_template("profit_and_loss")
    mapping={"revenue":["4000"],"cost_of_sales":["5000"],"operating_expenses":["5000"],"finance_costs":["6000"]}
    with pytest.raises(StatementTemplateError): validate_template_mapping(template,mapping)

def test_profit_loss_template_assembles_formulas():
    mapping={"revenue":["4000"],"cost_of_sales":["5000"],"operating_expenses":["6000"],"finance_costs":["7000"]}
    result=assemble_statement_template("profit_and_loss",mapping,{"4000":1000,"5000":400,"6000":200,"7000":50})
    amounts={r["code"]:r["amount"] for r in result["rows"]}
    assert amounts["gross_profit"]==Decimal("600")
    assert amounts["profit_before_tax"]==Decimal("350")

def test_balance_sheet_template_has_equation_rows():
    t=get_statement_template("balance_sheet")
    assert "total_assets" in [r["code"] for r in t["rows"]]
    assert "total_equity_liabilities" in [r["code"] for r in t["rows"]]

def test_unknown_template_rejected():
    with pytest.raises(StatementTemplateError): get_statement_template("cashflow_guess")

def test_dimension_aggregation_and_reconciliation(ledger):
    out=build_dimensional_report(rows=ledger,legal_entity="LE1",currency="NGN",dimensions=["branch"])
    assert len(out["groups"])==1 and out["groups"][0]["debit"]==Decimal("100")
    rec=reconcile_dimensional_totals(out,{"debit":100,"credit":100})
    assert rec["reconciled"]

def test_multiple_dimensions_split_groups(ledger):
    out=build_dimensional_report(rows=ledger,legal_entity="LE1",currency="NGN",dimensions=["branch","department"])
    assert len(out["groups"])==2

def test_dimension_unknown_rejected(ledger):
    with pytest.raises(DimensionalReportingError): build_dimensional_report(rows=ledger,legal_entity="LE1",currency="NGN",dimensions=["region"])

def test_missing_dimension_excluded(ledger):
    del ledger[0]["dimensions"]["branch"]
    out=build_dimensional_report(rows=ledger,legal_entity="LE1",currency="NGN",dimensions=["branch"])
    assert out["excluded_rows"]["missing_dimension"]==1

def test_dimensional_mixed_currency_rejected(ledger):
    ledger[1]["currency"]="USD"
    with pytest.raises(DimensionalReportingError): build_dimensional_report(rows=ledger,legal_entity="LE1",currency="NGN",dimensions=["branch"])

def test_dimension_requires_source_reference(ledger):
    ledger[0]["source_reference"]=""
    with pytest.raises(DimensionalReportingError): build_dimensional_report(rows=ledger,legal_entity="LE1",currency="NGN",dimensions=["branch"])

def test_dimension_report_reconciliation_detects_difference(ledger):
    out=build_dimensional_report(rows=ledger,legal_entity="LE1",currency="NGN",dimensions=["branch"])
    assert not reconcile_dimensional_totals(out,{"debit":101,"credit":100})["reconciled"]
