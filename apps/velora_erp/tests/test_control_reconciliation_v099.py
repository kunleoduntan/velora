from decimal import Decimal
import pytest

from velora_erp.finance.control_reconciliation import (
    ControlReconciliationError,
    build_control_reconciliation_exception,
    build_control_reconciliation_pack,
    reconcile_control,
)


def test_control_reconciliation_returns_deterministic_reviewable_exception():
    kwargs = dict(
        control_type="Inventory", control_account="STOCK", gl_balance="1250.00",
        source_balances=[
            {"source_type": "Inventory Item", "source_name": "ITEM-1", "balance": "1000"},
            {"source_type": "Inventory Item", "source_name": "ITEM-2", "balance": "200"},
        ], tolerance="0.01", as_of_date="2026-11-16", currency="NGN",
    )
    result = reconcile_control(**kwargs)
    assert result["status"] == "Exception"
    assert result["difference"] == Decimal("-50.00")
    assert result["reconciliation_id"] == reconcile_control(**kwargs)["reconciliation_id"]
    exception = build_control_reconciliation_exception(result)
    assert exception["status"] == "Open"
    assert exception["difference"] == Decimal("-50.00")
    assert exception["journal_created"] is False
    assert exception["automatic_adjustment"] is False


def test_control_reconciliation_pack_blocks_close_when_exceptions_exist():
    good = reconcile_control(control_type="Payables", control_account="AP", gl_balance=-50,
        source_balances=[{"source_type": "Supplier Invoice", "source_name": "PI-1", "balance": -50}])
    bad = reconcile_control(control_type="Receivables", control_account="AR", gl_balance=100,
        source_balances=[{"source_type": "Sales Invoice", "source_name": "SI-1", "balance": 90}])
    pack = build_control_reconciliation_pack(company="Example Ltd", as_of_date="2026-11-16",
        reconciliations=[good, bad], prepared_by="Finance User")
    assert pack["status"] == "Exceptions Outstanding"
    assert pack["reconciliation_count"] == 2
    assert pack["reconciled_count"] == 1
    assert pack["exception_count"] == 1
    assert pack["publication_blockers"] == [bad["reconciliation_id"]]
    assert pack["posting_side_effects"] is False


def test_control_reconciliation_rejects_duplicate_sources_and_bad_currency():
    duplicate = [
        {"source_type": "Invoice", "source_name": "INV-1", "balance": 10},
        {"source_type": "Invoice", "source_name": "INV-1", "balance": 10},
    ]
    with pytest.raises(ControlReconciliationError, match="Duplicate source"):
        reconcile_control(control_type="Receivables", control_account="AR", gl_balance=20, source_balances=duplicate)
    with pytest.raises(ControlReconciliationError, match="currency"):
        reconcile_control(control_type="Receivables", control_account="AR", gl_balance=10,
            source_balances=[{"source_type": "Invoice", "source_name": "INV-1", "balance": 10, "currency": "USD"}], currency="NGN")


def test_control_reconciliation_rejects_nonfinite_values_and_negative_tolerance():
    with pytest.raises(ControlReconciliationError, match="finite"):
        reconcile_control(control_type="Inventory", control_account="STOCK", gl_balance="NaN", source_balances=[])
    with pytest.raises(ControlReconciliationError, match="negative"):
        reconcile_control(control_type="Inventory", control_account="STOCK", gl_balance=0, source_balances=[], tolerance="-0.01")


def test_control_reconciliation_pack_rejects_duplicate_reconciliation_ids():
    result = reconcile_control(control_type="Inventory", control_account="STOCK", gl_balance=0, source_balances=[])
    with pytest.raises(ControlReconciliationError, match="unique"):
        build_control_reconciliation_pack(company="Co", as_of_date="2026-11-16",
            reconciliations=[result, result], prepared_by="User")


def test_current_state_adapters_refuse_historical_as_of_dates():
    from datetime import date, timedelta
    from velora_erp.finance.reconciliation_adapters import _require_current_operational_snapshot
    historical = (date.today() - timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="current-state balances only"):
        _require_current_operational_snapshot(historical, "Fixed assets")
    assert _require_current_operational_snapshot(date.today().isoformat(), "Fixed assets") == date.today()
