"""Cancel for leases: modification, instalment payment and the lease itself, newest first."""
from datetime import date, timedelta
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc, get_list
from velora.permissions import Session, session_as
from velora.exceptions import ValidationError
from test_finance_operations_v025_integration import setup_ops, approve_submit
from velora_erp.finance.engine import get_account_balance

MAKER = Session("ops-maker@example.test", frozenset({"Accountant"}))
APPROVER = Session("ops-approver@example.test", frozenset({"Finance Manager"}))


def test_lease_modification_payment_and_lease_cancel_newest_first(tmp_path):
    accounts, supplier, category = setup_ops(tmp_path)
    try:
        start = date.today(); end = start + timedelta(days=365)
        due_dates = [start + timedelta(days=30 * n) for n in range(1, 13)]
        with session_as(MAKER):
            lease = new_doc("Fixed Asset Lease", lease_type="Lease In (Lessee)",
                asset_name="Lease Remeasurement Asset", asset_category=category.name, counterparty=supplier.name,
                lease_start_date=start, lease_end_date=end, classification="IFRS 16 Lessee",
                payment_frequency="Monthly", payment_timing="Arrears", discount_rate=12, currency="NGN", exchange_rate=1,
                rou_asset_account=accounts["1600"].name, lease_liability_account=accounts["2300"].name,
                interest_expense_account=accounts["5200"].name, accumulated_depreciation_account=accounts["1690"].name,
                depreciation_expense_account=accounts["5400"].name,
                payments=[{"due_date":d,"payment_amount":100} for d in due_dates]).insert()
        lease = approve_submit(lease)
        first = lease.payments[0]
        with session_as(MAKER):
            payment = new_doc("Payment", payment_date=due_dates[0], posting_date=due_dates[0], purpose="Lease Payment",
                currency="NGN", exchange_rate=1, payment_method="Bank Transfer", cash_account=accounts["1000"].name,
                lease_reference=lease.name, lease_due_date=due_dates[0], narration="First lease instalment",
                lines=[{"account":accounts["2300"].name,"amount":first.principal_reduction,"description":"Lease principal"},
                       {"account":accounts["5200"].name,"amount":first.interest_expense,"description":"Lease interest"}]).insert()
        approve_submit(payment)
        remaining_dates = due_dates[1:]
        with session_as(MAKER):
            modification = new_doc("Fixed Asset Lease Modification", lease=lease.name,
                effective_date=due_dates[0], modification_reason="Change in Discount Rate",
                reason_details="Updated incremental borrowing rate following reassessment.", discount_rate=10,
                payments=[{"due_date":d,"payment_amount":100} for d in remaining_dates]).insert()
        modification = approve_submit(modification)
        refreshed = get_doc("Fixed Asset Lease", lease.name, ignore_permissions=True)
        assert modification.posting_batch
        assert refreshed.lease_liability_balance == modification.remeasured_liability
        assert any(p.payment_status == "Superseded" for p in refreshed.payments)
        assert sum(1 for p in refreshed.payments if p.payment_status == "Scheduled") == 11
        liability_after_payment = Decimal(str(get_doc("Fixed Asset Lease", lease.name, ignore_permissions=True).payments[0].closing_liability))
        import pytest
        from velora.exceptions import ValidationError
        def cancel(doc):
            with session_as(APPROVER):
                d = get_doc(doc.doctype, doc.name); d.cancel(reason="Corrected"); return d
        with pytest.raises(ValidationError):
            cancel(payment)                                          # the modification sits on top of the first instalment
        cancel(modification)
        back = get_doc("Fixed Asset Lease", lease.name, ignore_permissions=True)
        assert not any(p.payment_status == "Superseded" for p in back.payments)
        assert sum(1 for p in back.payments if p.payment_status == "Scheduled") == 11
        assert get_doc("Fixed Asset", back.right_of_use_asset, ignore_permissions=True).acquisition_cost == back.present_value
        cancel(payment)
        again = get_doc("Fixed Asset Lease", lease.name, ignore_permissions=True)
        assert sum(1 for p in again.payments if p.payment_status == "Scheduled") == 12
        cancel(lease)
        assert get_account_balance(accounts["1600"].name) == 0 and get_account_balance(accounts["2300"].name) == 0
    finally:
        velora.shutdown()
