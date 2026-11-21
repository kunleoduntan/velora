import json
from decimal import Decimal
from pathlib import Path

from velora.meta.registry import Registry
from velora_erp.finance.doctype.fixed_asset_lease.fixed_asset_lease import lease_pv

APP_ROOT = Path(__file__).resolve().parents[1]
DOCTYPES = APP_ROOT / "velora_erp" / "finance" / "doctype"

def test_enterprise_finance_operations_doctypes_register():
    registry = Registry()
    registry.load(["velora_erp"])
    expected = {
        "Financial Voucher", "Batch Bank Transaction", "Bank Transaction Line",
        "Bank Transaction Processor", "Bank Statement Transaction",
        "Bank Transaction Coding Rule", "Accrual", "Accrual Line",
        "Fixed Asset Category", "Fixed Asset", "Fixed Asset Request",
        "Fixed Asset Request Line", "Fixed Asset Purchase", "Fixed Asset Purchase Line",
        "Fixed Asset Lease", "Fixed Asset Lease Payment",
        "Fixed Asset Revaluation", "Fixed Asset Disposal",
    }
    assert expected <= set(registry._doctypes)

def test_financial_voucher_is_the_native_journal_voucher_not_a_duplicate():
    registry = Registry(); registry.load(["velora_erp"])
    voucher = registry._doctypes["Financial Voucher"]
    assert voucher.is_submittable
    assert voucher.get_field("lines").options == "Financial Voucher Line"
    assert "Journal Voucher" not in registry._doctypes

def test_bank_and_fixed_asset_sections_are_collapsible():
    expected = {
        "Bank Transaction Processor": ["CSV Statement Import", "Imported Statement Lines", "Generated Posting Batch"],
        "Batch Bank Transaction": ["Bank Transactions", "Approval"],
        "Accrual": ["Accrual Lines", "Approval"],
        "Fixed Asset Request": ["Requested Assets", "Approval"],
        "Fixed Asset Purchase": ["Asset Purchase Details", "Approval"],
        "Fixed Asset Lease": ["Lease Payment Schedule", "Accounting", "Approval"],
        "Fixed Asset Revaluation": ["Approval"],
        "Fixed Asset Disposal": ["Approval"],
    }
    for doctype, labels in expected.items():
        folder = doctype.lower().replace(" ", "_")
        data = json.loads((DOCTYPES / folder / f"{folder}.json").read_text())
        sections = {f["label"]: f for f in data["fields"] if f["fieldtype"] == "Section Break"}
        for label in labels:
            assert sections[label]["collapsible"] is True

def test_lease_present_value_and_payment_timing():
    class Payment:
        def __init__(self, amount): self.payment_amount = amount
    payments = [Payment("100.00") for _ in range(12)]
    arrears = lease_pv(payments, "12", "Monthly", "Arrears")
    advance = lease_pv(payments, "12", "Monthly", "In Advance")
    assert arrears == Decimal("1125.51")
    assert advance > arrears
    assert lease_pv([Payment("100"), Payment("100")], "0", "Monthly") == Decimal("200.00")
