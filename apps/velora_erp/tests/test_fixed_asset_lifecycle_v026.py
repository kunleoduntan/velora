from pathlib import Path
import json
from types import SimpleNamespace
from decimal import Decimal

from velora.meta.registry import Registry
from velora_erp.finance.doctype.fixed_asset_depreciation_run.fixed_asset_depreciation_run import depreciation_amount
from velora_erp.finance.doctype.fixed_asset_impairment.fixed_asset_impairment import calculate_impairment_movement

APP_ROOT = Path(__file__).resolve().parents[1]


def test_fixed_asset_depreciation_and_impairment_doctypes_register():
    registry = Registry()
    registry.load(["velora_erp", "velora_projectone"])
    assert {"Fixed Asset Depreciation Run", "Fixed Asset Depreciation Line", "Fixed Asset Impairment"} <= set(registry._doctypes)
    run = registry._doctypes["Fixed Asset Depreciation Run"]
    assert run.is_submittable is True
    assert run.get_field("lines").options == "Fixed Asset Depreciation Line"


def test_straight_line_depreciation_respects_residual_value():
    asset = SimpleNamespace(
        name="FA-1", depreciation_method="Straight Line", acquisition_cost=Decimal("12000"),
        revaluation_adjustment=0, residual_value=Decimal("1200"), carrying_amount=Decimal("12000"),
        useful_life_months=12, depreciation_rate=0, total_units_of_production=0,
    )
    category = SimpleNamespace(default_depreciation_method="Straight Line", default_reducing_balance_rate=0)
    amount = depreciation_amount(asset, category, 30)
    assert amount > 0
    assert amount < Decimal("1200")
    assert amount == Decimal("887.06")


def test_reducing_balance_uses_percentage_rate_and_carrying_amount():
    asset = SimpleNamespace(
        name="FA-2", depreciation_method="Reducing Balance", acquisition_cost=10000,
        revaluation_adjustment=0, residual_value=1000, carrying_amount=10000,
        useful_life_months=60, depreciation_rate=20, total_units_of_production=0,
    )
    category = SimpleNamespace(default_depreciation_method="Reducing Balance", default_reducing_balance_rate=20)
    amount = depreciation_amount(asset, category, 365)
    assert amount == Decimal("1798.77")


def test_units_of_production_depreciation_uses_period_output():
    asset = SimpleNamespace(
        name="FA-3", depreciation_method="Units of Production", acquisition_cost=10000,
        revaluation_adjustment=0, residual_value=1000, carrying_amount=10000,
        useful_life_months=60, depreciation_rate=0, total_units_of_production=10000,
    )
    category = SimpleNamespace(default_depreciation_method="Units of Production", default_reducing_balance_rate=0)
    assert depreciation_amount(asset, category, 30, units=500) == Decimal("450.00")


def test_depreciation_is_capped_at_residual_value():
    asset = SimpleNamespace(
        name="FA-4", depreciation_method="Straight Line", acquisition_cost=1000,
        revaluation_adjustment=0, residual_value=900, carrying_amount=905,
        useful_life_months=1, depreciation_rate=0, total_units_of_production=0,
    )
    category = SimpleNamespace(default_depreciation_method="Straight Line", default_reducing_balance_rate=0)
    assert depreciation_amount(asset, category, 365) == Decimal("5.00")


def test_impairment_loss_and_reversal_obey_reversal_ceiling():
    loss = calculate_impairment_movement("Recognise Impairment", 1000, 700, 0, 1000)
    assert loss == Decimal("300.00")
    reversal = calculate_impairment_movement("Reverse Impairment", 700, 1200, 300, 900)
    assert reversal == Decimal("200.00")


def test_impairment_reversal_cannot_exceed_pre_impairment_carrying_amount():
    reversal = calculate_impairment_movement("Reverse Impairment", 700, 1500, 300, 900)
    assert reversal == Decimal("200.00")


def test_acquisition_sources_expose_depreciation_method_fields():
    for relative in (
        "velora_erp/finance/doctype/fixed_asset_purchase_line/fixed_asset_purchase_line.json",
        "velora_erp/finance/doctype/purchase_invoice_line/purchase_invoice_line.json",
    ):
        data = json.loads((APP_ROOT / relative).read_text())
        names = {f["fieldname"] for f in data["fields"]}
        assert {"depreciation_method", "depreciation_rate", "total_units_of_production"} <= names
