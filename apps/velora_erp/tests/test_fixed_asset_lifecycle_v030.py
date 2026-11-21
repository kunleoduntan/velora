from decimal import Decimal

from velora.meta.registry import Registry
from velora_erp.finance.doctype.fixed_asset_lease_termination.fixed_asset_lease_termination import calculate_lease_termination
from velora_erp.finance.doctype.fixed_asset_cgu_impairment_reversal.fixed_asset_cgu_impairment_reversal import maximum_impairment_reversal


def test_v030_lifecycle_doctypes_register():
    registry = Registry()
    registry.load(["velora_erp"])
    for name in (
        "Fixed Asset Component Adjustment",
        "Fixed Asset Lease Termination",
        "Fixed Asset CGU Impairment Reversal",
        "Fixed Asset CGU Impairment Reversal Line",
        "Fixed Asset CGU Other Asset",
        "Fixed Asset CGU Other Asset Impairment Line",
        "Fixed Asset CGU Other Asset Reversal Line",
    ):
        assert name in registry._doctypes


def test_lease_termination_full_and_partial_calculation():
    partial = calculate_lease_termination(100000, 90000, 5000, 25)
    assert partial == {
        "liability_derecognised": Decimal("25000.00"),
        "rou_derecognised": Decimal("22500.00"),
        "gain_loss": Decimal("-2500.00"),
    }
    full = calculate_lease_termination(100000, 90000, 5000, 100)
    assert full["liability_derecognised"] == Decimal("100000.00")
    assert full["rou_derecognised"] == Decimal("90000.00")
    assert full["gain_loss"] == Decimal("5000.00")


def test_cgu_impairment_reversal_respects_no_impairment_ceiling():
    assert maximum_impairment_reversal(650, 400, 900) == Decimal("250.00")
    assert maximum_impairment_reversal(650, 100, 900) == Decimal("100.00")
    assert maximum_impairment_reversal(950, 100, 900) == Decimal("0.00")


def test_legacy_component_impairment_defaults_to_profit_or_loss():
    from types import SimpleNamespace
    from velora_erp.finance.doctype.fixed_asset_component_adjustment.fixed_asset_component_adjustment import tracked_component_impairment
    reserve, pnl = tracked_component_impairment(SimpleNamespace(
        impairment_against_revaluation_surplus=0,
        impairment_charged_to_expense=0,
        impairment_loss=Decimal("125.00"),
    ))
    assert reserve == 0
    assert pnl == Decimal("125.00")


def test_deferred_tax_auto_population_uses_financial_and_tax_book_balances(monkeypatch):
    from types import SimpleNamespace
    from velora_erp.finance.doctype.deferred_tax_assessment import deferred_tax_assessment as module

    monkeypatch.setattr(module, "get_doc", lambda *a, **k: SimpleNamespace(book_type="Tax", disabled=0))
    def fake_get_list(doctype, **kwargs):
        if doctype == "Fixed Asset":
            return [{"name": "FA-1", "carrying_amount": Decimal("900.00"), "status": "Active"}]
        if doctype == "Fixed Asset Book Balance":
            return [{"asset": "FA-1", "carrying_amount": Decimal("700.00")}]
        raise AssertionError(doctype)
    monkeypatch.setattr(module, "get_list", fake_get_list)

    class Assessment:
        auto_populate_fixed_asset_books = 1
        tax_depreciation_book = "TAX-BOOK"
        default_tax_rate = 30
        default_tax_rate_basis = "Enacted tax rate reference"
        lines = None
        def append(self, fieldname, values):
            assert fieldname == "lines"
            self.lines.append(SimpleNamespace(**values))
        def _link_children(self):
            self.linked = True

    doc = Assessment()
    module.populate_fixed_asset_book_differences(doc)
    assert len(doc.lines) == 1
    line = doc.lines[0]
    assert line.source_asset == "FA-1"
    assert line.financial_carrying_amount == Decimal("900.00")
    assert line.tax_base == Decimal("700.00")
    assert line.tax_rate == 30
    assert line.recognise_deferred_tax_asset == 0
    assert doc.linked is True


def test_cgu_impairment_allocates_to_goodwill_before_other_assets(monkeypatch):
    from types import SimpleNamespace
    from velora_erp.finance.doctype.fixed_asset_cgu_impairment import fixed_asset_cgu_impairment as module

    goodwill = SimpleNamespace(name="CGU-ROW-1", reference_code="GW-1", asset_type="Goodwill",
        carrying_amount=Decimal("500"), accumulated_impairment=Decimal("0"), individual_recoverable_floor=Decimal("0"),
        impairment_account="Accum Impairment", impairment_expense_account="Impairment Expense",
        revaluation_surplus=Decimal("0"), revaluation_surplus_account=None,
        impairment_ceiling_carrying_amount=Decimal("500"), impairment_against_revaluation_surplus=Decimal("0"),
        impairment_charged_to_expense=Decimal("0"))
    intangible = SimpleNamespace(name="CGU-ROW-2", reference_code="IA-1", asset_type="Intangible Asset",
        carrying_amount=Decimal("1000"), accumulated_impairment=Decimal("0"), individual_recoverable_floor=Decimal("100"),
        impairment_account="Accum Impairment", impairment_expense_account="Impairment Expense",
        revaluation_surplus=Decimal("0"), revaluation_surplus_account=None,
        impairment_ceiling_carrying_amount=Decimal("1000"), impairment_against_revaluation_surplus=Decimal("0"),
        impairment_charged_to_expense=Decimal("0"))
    cgu = SimpleNamespace(disabled=0, assets=[], other_assets=[goodwill, intangible])
    monkeypatch.setattr(module, "get_doc", lambda *a, **k: cgu)
    monkeypatch.setattr(module, "validate_approval_transition", lambda doc: None)
    monkeypatch.setattr(module, "row", lambda doctype, name, *fields: {"disabled": 0, "root_type": "Asset" if name == "Accum Impairment" else "Expense"})

    class Assessment:
        cgu="CGU-1"; valuation_reference="IAS36-VAL-1"; recoverable_amount=Decimal("700")
        revaluation_surplus_account=None; lines=[]; other_asset_lines=[]
        def append(self, fieldname, values):
            getattr(self, fieldname).append(SimpleNamespace(**values))
        def _link_children(self): self.linked=True

    doc=Assessment()
    module.FixedAssetCGUImpairment.validate(doc)
    allocations={line.reference_code: line.allocated_impairment for line in doc.other_asset_lines}
    assert allocations == {"GW-1": Decimal("500.00"), "IA-1": Decimal("300.00")}
    assert doc.impairment_loss == Decimal("800.00")
    assert doc.linked is True


def test_component_adjustment_supports_partial_disposal():
    registry = Registry()
    registry.load(["velora_erp"])
    choices = registry._doctypes["Fixed Asset Component Adjustment"].get_field("adjustment_type").choices
    assert "Partially Dispose Component" in choices
    assert "Add Component" in choices
    assert "Retire Component" in choices
    assert "Impair Component" in choices
    assert "Reverse Component Impairment" in choices
    assert "Revalue Component" in choices
