from decimal import Decimal
import pytest
from velora_erp.finance.reporting.workbench import assemble_financial_reporting_pack
from velora_erp.finance.reporting.ias7 import ReportingConfigurationError

PERIOD={"from_date":"2026-01-01","to_date":"2026-12-31"}
MAPPINGS=[
 {"account":"Depreciation Expense","classification":"Operating","treatment":"Non-cash","description":"Non-cash depreciation adjustment","approval_status":"Approved"},
 {"account":"Trade Receivables","classification":"Operating","treatment":"Movement","description":"Operating working capital","approval_status":"Approved"},
 {"account":"Property Plant Equipment","classification":"Investing","treatment":"Movement","description":"Capital expenditure","approval_status":"Approved"},
 {"account":"Long Term Loan","classification":"Financing","treatment":"Movement","description":"Borrowings","approval_status":"Approved"},
]
SCHEDULES=[
 {"code":"DEP","account":"Depreciation Expense","schedule_type":"Non-cash Adjustment","signed_amount":"20","source_reference":"FA-DEP-001","approval_status":"Approved"},
 {"code":"AR","account":"Trade Receivables","schedule_type":"Working Capital","signed_amount":"-10","source_reference":"AR-MOV-001","approval_status":"Approved"},
 {"code":"PPE","account":"Property Plant Equipment","schedule_type":"Investing","signed_amount":"-30","source_reference":"FA-ADD-001","approval_status":"Approved"},
 {"code":"LOAN","account":"Long Term Loan","schedule_type":"Financing","signed_amount":"15","source_reference":"LOAN-001","approval_status":"Approved"},
]

def build(**overrides):
 args=dict(period=PERIOD,cash_mappings=MAPPINGS,schedules=SCHEDULES,net_profit="100",opening_cash="50",closing_cash="145",opening_equity={"Share Capital":"100","Retained Earnings":"50"},equity_movements=[{"code":"PROFIT","component":"Retained Earnings","movement_type":"Profit or loss","amount":"25","source":"IS-2026","classification_status":"Approved"}],closing_equity={"Share Capital":"100","Retained Earnings":"75"},disclosure_notes=[{"code":"POLICY","title":"Accounting policies","required":True,"status":"Approved","content":"Basis of preparation"}],ratio_inputs={"current_assets":"200","current_liabilities":"100","total_debt":"50","total_equity":"175","revenue":"500","gross_profit":"200","operating_profit":"100","net_profit":"25","total_assets":"300"},cash_equivalents_policy="Cash and cash equivalents comprise cash at bank and on hand.")
 args.update(overrides)
 return assemble_financial_reporting_pack(**args)

def test_workbench_assembles_reconciled_pack():
 result=build()
 assert result["publication_ready"] is True
 assert result["cash_flow"]["reconciled"] is True
 assert result["equity"]["reconciled"] is True
 assert result["disclosures"]["complete"] is True
 assert result["ratios"]["ratios"]["Current ratio"]["value"] == Decimal("2")
 assert len(result["classification_register"]) == 4

def test_unapproved_schedule_is_rejected():
 rows=[dict(x) for x in SCHEDULES]
 rows[0]["approval_status"]="Pending"
 with pytest.raises(ReportingConfigurationError,match="not independently approved"):
  build(schedules=rows)

def test_schedule_requires_source_reference():
 rows=[dict(x) for x in SCHEDULES]
 rows[0]["source_reference"]=""
 with pytest.raises(ReportingConfigurationError,match="supporting source reference"):
  build(schedules=rows)

def test_mapping_schedule_conflict_blocks_publication():
 rows=[dict(x) for x in SCHEDULES]
 rows[0]["schedule_type"]="Investing"
 result=build(schedules=rows)
 assert result["publication_ready"] is False
 assert result["classification_exceptions"]

def test_cash_reconciliation_mismatch_blocks_publication():
 result=build(closing_cash="146")
 assert result["publication_ready"] is False
 assert result["cash_flow"]["reconciled"] is False

def test_excluded_account_is_not_reported():
 mappings=MAPPINGS+[ {"account":"Tax Suspense","classification":"Operating","treatment":"Exclude","description":"Excluded by policy","approval_status":"Approved"} ]
 rows=SCHEDULES+[ {"code":"TAX","account":"Tax Suspense","schedule_type":"Working Capital","signed_amount":"9","source_reference":"TAX-001","approval_status":"Approved"} ]
 result=build(cash_mappings=mappings,schedules=rows)
 assert result["publication_ready"] is True
 assert "TAX" not in [x["code"] for x in result["classification_register"]]


def test_unapproved_mapping_is_rejected():
 mappings=[dict(x) for x in MAPPINGS]
 mappings[0]["approval_status"]="Pending"
 with pytest.raises(ReportingConfigurationError,match="not independently approved"):
  build(cash_mappings=mappings)

def test_mapping_outside_effective_period_is_rejected():
 mappings=[dict(x) for x in MAPPINGS]
 mappings[0]["effective_from"]="2027-01-01"
 with pytest.raises(ReportingConfigurationError,match="not effective"):
  build(cash_mappings=mappings)
