from decimal import Decimal
import pytest

from velora_erp.finance.reporting.ias7 import (
    ReportingConfigurationError, build_indirect_cash_flow, build_equity_movement,
    build_financial_disclosure_pack, calculate_financial_ratios,
    classify_cash_movements,
)

PERIOD = {"from_date": "2026-01-01", "to_date": "2026-12-31"}


def test_indirect_cash_flow_reconciles_and_uses_decimal():
    result = build_indirect_cash_flow(
        period=PERIOD, net_profit="100.10",
        adjustments=[{"code": "DEP", "label": "Depreciation", "amount": "20.00", "classification": "Operating"}],
        working_capital=[{"code": "AR", "label": "Increase in receivables", "amount": "-10", "classification": "Operating"}],
        investing=[{"code": "PPE", "label": "Purchase of PPE", "amount": "-30", "classification": "Investing"}],
        financing=[{"code": "LOAN", "label": "Loan proceeds", "amount": "15", "classification": "Financing"}],
        opening_cash="50.10", closing_cash="145.20")
    assert result["operating"]["net_cash"] == Decimal("110.10")
    assert result["net_change_in_cash"] == Decimal("95.10")
    assert result["reconciled"] is True


def test_cash_flow_unreconciled_is_publication_blocker():
    result = build_indirect_cash_flow(period=PERIOD, net_profit=10, adjustments=[], working_capital=[],
        investing=[], financing=[], opening_cash=5, closing_cash=20)
    assert result["reconciled"] is False
    assert result["publication_blockers"]


def test_unapproved_cash_flow_schedule_rejected():
    with pytest.raises(ReportingConfigurationError, match="not been approved"):
        build_indirect_cash_flow(period=PERIOD, net_profit=0,
            adjustments=[{"code": "X", "amount": 1, "classification_status": "Draft"}],
            working_capital=[], investing=[], financing=[], opening_cash=0, closing_cash=0)


def test_unmapped_cash_movement_is_exception_not_guessed():
    result = classify_cash_movements([{"account": "A", "amount": 10}], [])
    assert result["ready_for_review"] is False
    assert result["exceptions"][0]["reason"].startswith("No approved")


def test_non_cash_mapping_is_excluded_from_cash_and_flagged_for_disclosure():
    result = classify_cash_movements([{"account": "DEP", "amount": 20}],
        [{"account": "DEP", "classification": "Operating", "treatment": "Non-cash"}])
    assert result["classified"] == []
    assert "Non-cash movement" in result["exceptions"][0]["reason"]


def test_equity_rollforward_component_reconciliation():
    result = build_equity_movement(opening_balances={"Retained Earnings": 100},
        movements=[{"code": "P", "component": "Retained Earnings", "movement_type": "Profit or loss", "amount": 25}],
        closing_balances={"Retained Earnings": 125})
    assert result["reconciled"] is True


def test_equity_mismatch_blocks_publication():
    result = build_equity_movement(opening_balances={"Share Capital": 100}, movements=[], closing_balances={"Share Capital": 90})
    assert result["reconciled"] is False


def test_required_disclosure_note_must_be_approved():
    result = build_financial_disclosure_pack(period=PERIOD,
        notes=[{"code": "POLICY", "title": "Accounting policies", "required": True, "status": "Draft"}])
    assert result["complete"] is False


def test_not_applicable_note_requires_rationale():
    result = build_financial_disclosure_pack(period=PERIOD,
        notes=[{"code": "RELATED", "status": "Not Applicable", "rationale": ""}])
    assert result["complete"] is False


def test_ratios_do_not_silently_fill_missing_classifications():
    result = calculate_financial_ratios(current_assets=100, current_liabilities=50)
    assert result["ratios"]["Current ratio"]["value"] == Decimal("2")
    assert "total_debt" in result["missing_mapped_inputs"]
    assert result["publication_blockers"]
