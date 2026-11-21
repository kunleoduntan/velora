import pytest
from decimal import Decimal
from velora_erp.finance.reporting.group_consolidation import *

P={"from_date":"2026-01-01","to_date":"2026-12-31"}
def entities():
 return [{"entity_id":"A","functional_currency":"USD","period":P,"balances":{"1000":"100","2000":"-100"}},{"entity_id":"B","functional_currency":"EUR","period":P,"balances":{"1000":"50","2000":"-50"}}]

def test_group_translation_and_balances():
 r=build_group_consolidation(group_id="G",presentation_currency="USD",period=P,entities=entities(),exchange_rates={"EUR":"1.1"})
 assert r["status"]=="Ready for elimination review"
 assert r["group_balances_before_eliminations"]["1000"]==Decimal("155.0")
 assert not r["eliminations_posted"]

def test_period_mismatch_blocks():
 e=entities(); e[1]["period"]={"from_date":"2026-02-01","to_date":"2026-12-31"}
 r=build_group_consolidation(group_id="G",presentation_currency="USD",period=P,entities=e,exchange_rates={"EUR":"1.1"})
 assert r["status"]=="Blocked"

def test_intercompany_differences_are_not_eliminated():
 ic=[{"transaction_id":"IC1","seller_entity":"A","buyer_entity":"B","seller_account":"4000","buyer_account":"5000","currency":"USD","seller_amount":"100","buyer_amount":"99"}]
 r=build_group_consolidation(group_id="G",presentation_currency="USD",period=P,entities=entities(),exchange_rates={"EUR":"1.1"},intercompany_items=ic)
 assert r["status"]=="Blocked" and r["intercompany_elimination_proposals"][0]["status"]=="Unmatched"

def test_approval_is_not_decided_by_role_in_code():
 p={"status":"Proposed","difference":Decimal("0")}
 assert approve_elimination_proposal(proposal=p,approved_by="x",reviewer_role="preparer")["posted"] is False
 assert approve_elimination_proposal(proposal=p,approved_by="cfo",reviewer_role="approver")["posted"] is False

def test_missing_rate_blocks():
 r=build_group_consolidation(group_id="G",presentation_currency="USD",period=P,entities=entities(),exchange_rates={})
 assert r["status"]=="Blocked"
