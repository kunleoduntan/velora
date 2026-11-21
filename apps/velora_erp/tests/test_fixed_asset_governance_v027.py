from pathlib import Path
import json
from decimal import Decimal

from velora.meta.registry import Registry
from velora_erp.finance.doctype.fixed_asset_transfer.fixed_asset_transfer import assignment_changes

APP_ROOT = Path(__file__).resolve().parents[1]


def test_asset_transfer_and_history_doctypes_register():
    registry = Registry()
    registry.load(["velora_erp"])
    assert {"Fixed Asset Transfer", "Fixed Asset History Log"} <= set(registry._doctypes)
    transfer = registry._doctypes["Fixed Asset Transfer"]
    assert transfer.is_submittable is True
    assert transfer.get_field("asset").options == "Fixed Asset"
    history = registry._doctypes["Fixed Asset History Log"]
    assert history.is_submittable is False


def test_transfer_requires_at_least_one_changed_assignment():
    current = {"location": "HQ", "cost_centre": "CC-OPS", "business_unit": "Operations"}
    assert assignment_changes(current, current) == {}
    assert assignment_changes(current, {**current, "location": "Branch 2"}) == {
        "location": ("HQ", "Branch 2")
    }


def test_transfer_metadata_keeps_source_assignment_read_only():
    path = APP_ROOT / "velora_erp/finance/doctype/fixed_asset_transfer/fixed_asset_transfer.json"
    fields = {f["fieldname"]: f for f in json.loads(path.read_text())["fields"]}
    for name in ("from_location", "from_cost_centre", "from_business_unit"):
        assert fields[name]["read_only"] is True


def test_fixed_asset_reconciliation_is_registered_as_script_report():
    path = APP_ROOT / "velora_erp/finance/report/fixed_asset_reconciliation/fixed_asset_reconciliation.json"
    meta = json.loads(path.read_text())
    assert meta["type"] == "script"
    assert meta["ref_doctype"] == "Fixed Asset"
    assert (path.parent / "fixed_asset_reconciliation.py").exists()


def test_capitalised_purchase_invoice_posts_asset_linked_acquisition_lines(monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    from velora_erp.finance import invoices

    monkeypatch.setattr(invoices, "row", lambda doctype, name, *fields: {"control_account": "AP-CTRL"})
    line = SimpleNamespace(
        name="PIL-1", description="Office generator", is_fixed_asset=True,
        created_assets="FA-1, FA-2", quantity=2, amount=Decimal("2000.00"),
        account="FA-COST", cost_centre="CC-OPS", business_unit="Operations",
        tax_amount=0, matched_quantity=0, item_code=None,
    )
    source = SimpleNamespace(
        party="SUP-1", name="PI-1", grand_total=Decimal("2000.00"),
        invoice_date=date(2026, 11, 15), posting_date=date(2026, 11, 15),
        currency="NGN", exchange_rate=1, lines=[line], party_reference=None, due_date=date(2026, 12, 15), narration="Asset acquisition",
    )
    instruction = invoices.InvoicePostingAdapter("Purchase").build_posting(source)
    asset_lines = [entry for entry in instruction.lines if entry.asset]
    assert [entry.asset for entry in asset_lines] == ["FA-1", "FA-2"]
    assert sum((entry.debit for entry in asset_lines), Decimal("0")) == Decimal("2000.00")
