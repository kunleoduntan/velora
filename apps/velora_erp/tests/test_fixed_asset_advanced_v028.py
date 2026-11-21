from pathlib import Path
import json
from decimal import Decimal
from types import SimpleNamespace
import pytest

from velora.meta.registry import Registry
from velora_erp.finance.doctype.fixed_asset_cgu_impairment.fixed_asset_cgu_impairment import allocate_cgu_impairment
from velora_erp.finance.doctype.fixed_asset_lease_modification.fixed_asset_lease_modification import present_value_remaining

APP_ROOT = Path(__file__).resolve().parents[1]


def test_advanced_asset_accounting_doctypes_register():
    registry = Registry()
    registry.load(["velora_erp"])
    required = {
        "Fixed Asset Depreciation Book", "Fixed Asset Book Balance",
        "Fixed Asset Component", "Fixed Asset Component Depreciation Line",
        "Fixed Asset Lease Modification", "Fixed Asset Lease Modification Payment",
        "Fixed Asset CGU", "Fixed Asset CGU Asset", "Fixed Asset CGU Impairment",
        "Fixed Asset CGU Impairment Line",
    }
    assert required <= set(registry._doctypes)
    assert registry._doctypes["Fixed Asset Depreciation Book"].get_field("book_type").choices == ["Financial", "Tax", "Management"]
    assert registry._doctypes["Fixed Asset Lease Modification"].is_submittable is True
    assert registry._doctypes["Fixed Asset CGU Impairment"].is_submittable is True


def test_financial_book_is_only_book_type_that_posts_to_gl(monkeypatch):
    from velora_erp.finance.doctype.fixed_asset_depreciation_book.fixed_asset_depreciation_book import FixedAssetDepreciationBook
    monkeypatch.setattr("velora_erp.finance.doctype.fixed_asset_depreciation_book.fixed_asset_depreciation_book.get_list", lambda *a, **k: [])
    for book_type, expected in (("Financial", 1), ("Tax", 0), ("Management", 0)):
        doc = FixedAssetDepreciationBook.__new__(FixedAssetDepreciationBook)
        doc.book_code = book_type.upper(); doc.book_name = book_type
        doc.book_type = book_type; doc.accounting_framework = "IFRS" if book_type == "Financial" else "Tax"
        doc.is_default = 0; doc.disabled = 0; doc.name = book_type
        doc.validate()
        assert doc.posts_to_gl == expected


def test_cgu_impairment_allocation_is_exact_to_cents_and_respects_floors():
    allocated = allocate_cgu_impairment(
        {"FA-1": Decimal("100.00"), "FA-2": Decimal("200.00")},
        Decimal("240.00"),
        {"FA-1": Decimal("90.00"), "FA-2": Decimal("0.00")},
    )
    assert allocated == {"FA-1": Decimal("10.00"), "FA-2": Decimal("50.00")}
    assert sum(allocated.values()) == Decimal("60.00")


def test_cgu_allocation_rejects_loss_beyond_asset_recoverable_floors():
    with pytest.raises(Exception, match="Assess goodwill and other CGU assets first"):
        allocate_cgu_impairment({"FA-1": 100, "FA-2": 100}, 150, {"FA-1": 90, "FA-2": 90})


def test_cgu_allocation_rounding_never_overallocates():
    for loss in (Decimal("0.01"), Decimal("0.02"), Decimal("0.05"), Decimal("1.00")):
        result = allocate_cgu_impairment({"A": 1, "B": 1, "C": 1}, Decimal("3") - loss)
        assert sum(result.values()) == loss


def test_lease_remeasurement_present_value_uses_actual_day_fraction():
    payments = [
        SimpleNamespace(due_date="2027-01-01", payment_amount=100),
        SimpleNamespace(due_date="2028-01-01", payment_amount=100),
    ]
    assert present_value_remaining(payments, 10, "2026-01-01") == Decimal("173.57")


def test_lease_remeasurement_requires_increasing_due_dates():
    payments = [
        SimpleNamespace(due_date="2027-01-01", payment_amount=100),
        SimpleNamespace(due_date="2027-01-01", payment_amount=100),
    ]
    with pytest.raises(Exception, match="strictly increasing"):
        present_value_remaining(payments, 10, "2026-01-01")


def test_nonfinancial_depreciation_book_does_not_post_to_gl_by_contract():
    book = json.loads((APP_ROOT / "velora_erp/finance/doctype/fixed_asset_depreciation_book/fixed_asset_depreciation_book.json").read_text())
    fields = {f["fieldname"]: f for f in book["fields"]}
    assert fields["posts_to_gl"]["read_only"] is True
    run = json.loads((APP_ROOT / "velora_erp/finance/doctype/fixed_asset_depreciation_run/fixed_asset_depreciation_run.json").read_text())
    assert any(f["fieldname"] == "depreciation_book" for f in run["fields"])
    controller = (APP_ROOT / "velora_erp/finance/doctype/fixed_asset_depreciation_run/fixed_asset_depreciation_run.py").read_text()
    assert 'book.book_type in ("Tax","Management")' in controller
    assert 'post_financial_transaction' in controller


def test_component_costs_are_supported_on_both_acquisition_sources():
    asset = json.loads((APP_ROOT / "velora_erp/finance/doctype/fixed_asset/fixed_asset.json").read_text())
    assert next(f for f in asset["fields"] if f["fieldname"] == "components")["options"] == "Fixed Asset Component"
    for relative in (
        "velora_erp/finance/doctype/fixed_asset_purchase/fixed_asset_purchase.json",
        "velora_erp/finance/doctype/purchase_invoice/purchase_invoice.json",
    ):
        meta = json.loads((APP_ROOT / relative).read_text())
        assert next(f for f in meta["fields"] if f["fieldname"] == "asset_components")["options"] == "Fixed Asset Component"


def test_component_depreciation_is_recorded_as_separate_ledger_lines():
    controller = (APP_ROOT / "velora_erp/finance/doctype/fixed_asset_depreciation_run/fixed_asset_depreciation_run.py").read_text()
    assert 'component_line.expense_account' in controller
    assert 'component_line.accumulated_depreciation_account' in controller
    assert 'db_update_child("Fixed Asset Component"' in controller


def test_book_reconciliation_report_is_registered():
    path = APP_ROOT / "velora_erp/finance/report/fixed_asset_book_reconciliation/fixed_asset_book_reconciliation.json"
    meta = json.loads(path.read_text())
    assert meta["type"] == "script"
    assert (path.parent / "fixed_asset_book_reconciliation.py").exists()
