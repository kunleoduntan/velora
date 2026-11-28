from decimal import Decimal
import pytest
from velora_erp.finance.ageing import AgeingError, ageing_bucket, build_ageing_report, build_dunning_candidates

def test_ageing_bucket_boundaries():
 assert [ageing_bucket(x) for x in (0,1,30,31,60,61,90,91)]==["Not Due","1-30 Days","1-30 Days","31-60 Days","31-60 Days","61-90 Days","61-90 Days","Over 90 Days"]
def test_ageing_report_groups_by_currency_and_preserves_party_invoice_rows():
 r=build_ageing_report(party_type="Customer",as_of_date="2026-11-15",open_items=[{"party_type":"Customer","party":"C1","invoice":"SI1","due_date":"2026-11-20","currency":"NGN","outstanding_amount":100},{"party_type":"Customer","party":"C1","invoice":"SI2","due_date":"2026-10-01","currency":"NGN","outstanding_amount":200},{"party_type":"Customer","party":"C2","invoice":"SI3","due_date":"2026-08-01","currency":"USD","outstanding_amount":50}])
 assert r["totals_by_currency"]["NGN"]["Not Due"]==100
 assert r["totals_by_currency"]["NGN"]["31-60 Days"]==200
 assert r["totals_by_currency"]["USD"]["Over 90 Days"]==50 and r["cross_currency_total"] is None
 assert r["rows"][0]["invoice"]=="SI2"
def test_ageing_excludes_zero_balances_and_rejects_negative():
 r=build_ageing_report(party_type="Supplier",as_of_date="2026-11-15",open_items=[{"party":"S1","invoice":"PI0","due_date":"2026-10-01","currency":"NGN","outstanding_amount":0}]); assert not r["rows"]
 with pytest.raises(AgeingError,match="non-negative"):
  build_ageing_report(party_type="Supplier",as_of_date="2026-11-15",open_items=[{"party":"S1","invoice":"PI1","due_date":"2026-10-01","currency":"NGN","outstanding_amount":-1}])
def test_ageing_rejects_invalid_party_currency_and_dates():
 with pytest.raises(AgeingError,match="wrong party type"):
  build_ageing_report(party_type="Customer",as_of_date="2026-11-15",open_items=[{"party_type":"Supplier","due_date":"2026-01-01","currency":"NGN","outstanding_amount":1}])
 with pytest.raises(AgeingError,match="three-letter"):
  build_ageing_report(party_type="Customer",as_of_date="2026-11-15",open_items=[{"due_date":"2026-01-01","currency":"N","outstanding_amount":1}])
def test_dunning_candidates_are_review_only_and_exclude_disputed():
 r=build_ageing_report(party_type="Customer",as_of_date="2026-11-15",open_items=[{"party":"C1","invoice":"SI1","due_date":"2026-10-01","currency":"NGN","outstanding_amount":500},{"party":"C1","invoice":"SI2","due_date":"2026-10-01","currency":"NGN","outstanding_amount":800,"disputed":True}])
 d=build_dunning_candidates(ageing_report=r,minimum_days_overdue=30,minimum_amount_by_currency={"NGN":100})
 assert len(d["candidates"])==1 and d["messages_sent"]==0 and d["candidates"][0]["message_sent"] is False
def test_dunning_rejects_untrusted_report_and_invalid_threshold():
 with pytest.raises(AgeingError,match="validated ageing"):
  build_dunning_candidates(ageing_report={})
 r=build_ageing_report(party_type="Supplier",as_of_date="2026-11-15",open_items=[])
 with pytest.raises(AgeingError,match="positive integer"):
  build_dunning_candidates(ageing_report=r,minimum_days_overdue=0)
