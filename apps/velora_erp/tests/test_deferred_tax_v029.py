from pathlib import Path
import json
from decimal import Decimal
import pytest
from velora.meta.registry import Registry
from velora_erp.finance.doctype.deferred_tax_assessment.deferred_tax_assessment import calculate_temporary_difference, calculate_deferred_tax_movement

APP_ROOT=Path(__file__).resolve().parents[1]

def test_deferred_tax_assessment_generates_non_posting_review_inbox():
    registry=Registry(); registry.load(["velora_erp", "velora_projectone"])
    assert {"Deferred Tax Assessment","Deferred Tax Assessment Line","Deferred Tax Posting Inbox","Deferred Tax Posting Inbox Line"} <= set(registry._doctypes)
    assert registry._doctypes["Deferred Tax Assessment"].is_submittable is False
    assert registry._doctypes["Deferred Tax Posting Inbox"].is_submittable is True

def test_taxable_temporary_difference_creates_deferred_tax_liability():
    result=calculate_temporary_difference(Decimal("150000"),Decimal("90000"),30)
    assert result == {"temporary_difference":Decimal("60000.00"),"difference_type":"Taxable","gross_deferred_tax":Decimal("18000.00"),"recognised_deferred_tax":Decimal("18000.00")}

def test_deductible_difference_requires_explicit_recognition_and_is_capped_by_tax_base():
    result=calculate_temporary_difference(80000,100000,30,False)
    assert result["difference_type"]=="Deductible"
    assert result["gross_deferred_tax"]==Decimal("6000.00")
    assert result["recognised_deferred_tax"]==Decimal("0.00")

def test_deferred_tax_movement_balances_dta_and_dtl_changes():
    result=calculate_deferred_tax_movement(25000,40000,10000,30000)
    assert result=={"delta_dta":Decimal("15000.00"),"delta_dtl":Decimal("10000.00"),"tax_expense":Decimal("-5000.00")}

def test_tax_rate_is_validated():
    with pytest.raises(Exception,match="Tax rate must be between"):
        calculate_temporary_difference(100,0,101)

def test_dta_requires_recoverability_evidence_and_rate_basis_fields():
    meta=json.loads((APP_ROOT/"velora_erp/finance/doctype/deferred_tax_assessment_line/deferred_tax_assessment_line.json").read_text())
    fields={f["fieldname"]:f for f in meta["fields"]}
    assert fields["tax_rate_basis"]["required"] is True
    assert fields["recoverability_basis"]["fieldtype"]=="Text"
    controller=(APP_ROOT/"velora_erp/finance/doctype/deferred_tax_assessment/deferred_tax_assessment.py").read_text()
    assert "probable future taxable profits" in controller
    assert "post_financial_transaction" not in controller
    assert "sync_deferred_tax_posting_inbox" in controller
    assert "def after_insert(self)" in controller
    assert "def on_update(self)" in controller
    inbox=(APP_ROOT/"velora_erp/finance/doctype/deferred_tax_posting_inbox/deferred_tax_posting_inbox.py").read_text()
    assert "ensure_approved(self,required=True)" in inbox
    assert "post_financial_transaction" in inbox


def test_assessment_builds_balanced_gl_proposal_without_posting():
    from types import SimpleNamespace
    from velora_erp.finance.doctype.deferred_tax_assessment.deferred_tax_assessment import build_deferred_tax_posting_lines
    doc=SimpleNamespace(deferred_tax_asset=Decimal("1500.00"),deferred_tax_liability=Decimal("4000.00"),previous_deferred_tax_asset=Decimal("1000.00"),previous_deferred_tax_liability=Decimal("3000.00"),deferred_tax_asset_account="DTA",deferred_tax_liability_account="DTL",deferred_tax_expense_account="DTEXP",deferred_tax_benefit_account="DTBEN")
    lines=build_deferred_tax_posting_lines(doc)
    assert [(x["account"],x["entry_type"],x["debit"],x["credit"]) for x in lines]==[("DTA","Deferred Tax Asset",Decimal("500.00"),0),("DTL","Deferred Tax Liability",0,Decimal("1000.00")),("DTEXP","Deferred Tax Expense",Decimal("500.00"),0)]
    assert sum(Decimal(str(x.get("debit",0))) for x in lines)==sum(Decimal(str(x.get("credit",0))) for x in lines)

def test_fixed_asset_purchase_has_explicit_cash_payment_option():
    meta=json.loads((APP_ROOT/"velora_erp/finance/doctype/fixed_asset_purchase/fixed_asset_purchase.json").read_text())
    fields={f["fieldname"]:f for f in meta["fields"]}
    assert "Immediate Cash Payment" in fields["purchase_type"]["options"]
    assert fields["bank_account"]["label"]=="Bank / Cash Account"
    controller=(APP_ROOT/"velora_erp/finance/doctype/fixed_asset_purchase/fixed_asset_purchase.py").read_text()
    assert 'Immediate Cash Payment' in controller and '_validate_payment_account' in controller


def test_cash_purchase_requires_cash_control_account(monkeypatch):
    from velora_erp.finance.doctype.fixed_asset_purchase import fixed_asset_purchase as module
    monkeypatch.setattr(module,"_account",lambda name,roots:{"root_type":"Asset","account_type":"CASH"})
    assert module._validate_payment_account("Immediate Cash Payment","CASH-GL")["account_type"]=="CASH"
    monkeypatch.setattr(module,"_account",lambda name,roots:{"root_type":"Asset","account_type":"BANK"})
    with pytest.raises(Exception,match="requires an active GL account configured with Account Type CASH"):
        module._validate_payment_account("Immediate Cash Payment","BANK-GL")
    assert module._validate_payment_account("Immediate Bank Payment","BANK-GL")["account_type"]=="BANK"


def test_deferred_tax_inbox_requires_approval_and_fingerprints_approved_payload():
    meta=json.loads((APP_ROOT/"velora_erp/finance/doctype/deferred_tax_posting_inbox/deferred_tax_posting_inbox.json").read_text())
    fields={f["fieldname"]:f for f in meta["fields"]}
    assert fields["approval_hash"]["read_only"] is True
    controller=(APP_ROOT/"velora_erp/finance/doctype/deferred_tax_posting_inbox/deferred_tax_posting_inbox.py").read_text()
    assert "ensure_approved(self,required=True)" in controller
    assert "An approved deferred tax proposal is immutable" in controller
    assert "Superseded" in controller
