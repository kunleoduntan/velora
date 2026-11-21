from velora_erp.finance.reporting.reporting_centre import build_reporting_centre,drill_down_reporting_account,ReportingCentreError
import pytest

def test_reporting_centre_ready_only_with_approved_fingerprinted_statements():
 r=build_reporting_centre(legal_entity="ACME",currency="NGN",period={"year":2026},statements={"SFP":{"legal_entity":"ACME","currency":"NGN","status":"Approved","snapshot_fingerprint":"abc"}},prepared_by="CFO")
 assert r['status']=="Ready for review" and len(r['fingerprint'])==64

def test_reporting_centre_blocks_entity_and_currency_mismatch():
 r=build_reporting_centre(legal_entity="ACME",currency="NGN",period={},statements={"P&L":{"legal_entity":"OTHER","currency":"USD","status":"Draft"}},prepared_by="CFO")
 assert r['status']=="Blocked" and len(r['publication_blockers'])>=3

def test_account_drilldown_filters_entity_period_and_dimensions():
 rows=[{"account":"Cash","legal_entity":"A","posting_date":"2026-01-02","cost_center":"HQ","debit":10,"voucher_type":"JV","voucher_no":"1"},{"account":"Cash","legal_entity":"A","posting_date":"2026-02-02","cost_center":"HQ"},{"account":"Cash","legal_entity":"B","posting_date":"2026-01-02","cost_center":"HQ"}]
 r=drill_down_reporting_account(account="Cash",rows=rows,legal_entity="A",period_from="2026-01-01",period_to="2026-01-31",dimensions={"cost_center":"HQ"})
 assert r['row_count']==1 and r['rows'][0]['source_reference']=="JV: 1"

def test_account_drilldown_rejects_reversed_dates():
 with pytest.raises(ReportingCentreError): drill_down_reporting_account(account="Cash",rows=[],legal_entity="A",period_from="2026-02-01",period_to="2026-01-01")
