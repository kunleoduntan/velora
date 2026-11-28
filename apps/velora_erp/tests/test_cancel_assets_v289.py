"""Cancel for the fixed asset family: every change an asset event made is put back, newest first."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as
from test_finance_operations_v025_integration import setup_ops, approve_submit, MAKER, APPROVER

D = lambda v: Decimal(str(v or 0))


def _cancel(doc, reason="Wrong figures"):
    with session_as(APPROVER):
        d = get_doc(doc.doctype, doc.name)
        d.cancel(reason=reason)
        d.reload()
    return d


def _asset(accounts, supplier, category):
    with session_as(MAKER):
        req = new_doc("Fixed Asset Request", request_date=date.today(), purpose="Server",
                      items=[{"description": "Server", "asset_category": category.name, "quantity": 1, "estimated_unit_cost": 1200}]).insert()
    approve_submit(req)
    with session_as(MAKER):
        purchase = new_doc("Fixed Asset Purchase", purchase_date=date.today(), request_reference=req.name, purchase_type="Supplier Credit",
                           supplier=supplier.name, supplier_payable_account=accounts["2100"].name, currency="NGN", exchange_rate=1,
                           items=[{"asset_name": "Server 01", "asset_category": category.name, "quantity": 1, "unit_cost": 1200,
                                   "asset_account": accounts["1500"].name, "useful_life_months": 12, "residual_value": 0}]).insert()
    purchase = approve_submit(purchase)
    return req, purchase, get_doc("Fixed Asset", purchase.created_assets, ignore_permissions=True)


def _depreciate(asset):
    book = get_list("Fixed Asset Depreciation Book", filters={"is_default": 1, "disabled": 0}, fields=["name"], limit=1)
    args = {"depreciation_book": book[0]["name"]} if book else {}
    start = asset.depreciation_start_date or date.today()
    with session_as(MAKER):
        run = new_doc("Fixed Asset Depreciation Run", **args, period_start=start, period_end=start + timedelta(days=29),
                      posting_date=start + timedelta(days=29), approval_status="Pending", lines=[{"asset": asset.name}]).insert()
    return approve_submit(run), start


def _state(name):
    a = get_doc("Fixed Asset", name, ignore_permissions=True)
    return (D(a.accumulated_depreciation), D(a.carrying_amount), D(a.revaluation_adjustment), a.status, a.last_depreciation_date)


def _net(accounts, code):
    return sum(D(r["debit"]) - D(r["credit"]) for r in get_list("Account Ledger Record", filters={"account": accounts[code].name}, fields=["debit", "credit"], limit=1000))


def test_asset_events_cancel_newest_first_and_the_asset_is_restored(tmp_path):
    accounts, supplier, category = setup_ops(tmp_path)
    try:
        req, purchase, asset = _asset(accounts, supplier, category)
        fresh = _state(asset.name)
        run, start = _depreciate(asset)
        after_run = _state(asset.name)
        assert after_run != fresh and after_run[0] > 0
        with session_as(MAKER):
            reval = new_doc("Fixed Asset Revaluation", asset=asset.name, revaluation_date=start + timedelta(days=29), valuation_method="Market Comparable",
                            new_carrying_amount=after_run[1] + 100, revaluation_surplus_account=accounts["3000"].name, reason="Valuation").insert()
        approve_submit(reval)
        assert _state(asset.name)[2] == 100

        with session_as(APPROVER):                                   # the depreciation cannot go while the revaluation sits on top of it
            with pytest.raises(ValidationError, match="later activity"):
                get_doc(run.doctype, run.name).cancel(reason="x")
        assert get_doc("Fixed Asset Depreciation Run", run.name).docstatus == 1

        _cancel(reval)
        assert _state(asset.name) == after_run
        _cancel(run)
        assert _state(asset.name) == fresh                           # exactly as it was after purchase
        assert _net(accounts, "5400") == 0 and _net(accounts, "1590") == 0
        assert [h["event_type"] for h in get_list("Fixed Asset History Log", filters={"asset": asset.name}, fields=["event_type"], limit=50)] == ["Acquisition"]

        again, _ = _depreciate(get_doc("Fixed Asset", asset.name, ignore_permissions=True))      # and the same period can be run again
        assert _state(asset.name) == after_run
    finally:
        velora.shutdown()


def test_cancelling_a_disposal_brings_the_asset_back_and_the_purchase_removes_it(tmp_path):
    accounts, supplier, category = setup_ops(tmp_path)
    try:
        req, purchase, asset = _asset(accounts, supplier, category)
        with session_as(MAKER):
            disposal = new_doc("Fixed Asset Disposal", asset=asset.name, disposal_date=date.today(), disposal_type="Sale", disposal_proceeds=1300,
                               disposal_costs=0, proceeds_account=accounts["1000"].name, buyer="Buyer", physical_verification_done=1, verified_by="Asset Manager",
                               verification_date=date.today(), gain_account=accounts["4000"].name, loss_account=accounts["5300"].name, reason="Sold").insert()
        disposal = approve_submit(disposal)
        assert _state(asset.name)[3] == "Disposed"
        with session_as(APPROVER):                                   # the purchase is blocked while the asset is disposed
            with pytest.raises(ValidationError):
                get_doc("Fixed Asset Purchase", purchase.name).cancel(reason="x")
        _cancel(disposal)
        assert _state(asset.name)[3] == "Active" and _state(asset.name)[1] == 1200 and _net(accounts, "1500") == 1200
        _cancel(purchase)
        assert _net(accounts, "1500") == 0 and _net(accounts, "2100") == 0
        assert get_list("Fixed Asset", filters={"name": asset.name}, fields=["name"]) == [] or get_doc("Fixed Asset", asset.name, ignore_permissions=True).docstatus == 2
        assert get_doc("Fixed Asset Request", req.name, ignore_permissions=True).status == "Approved"
    finally:
        velora.shutdown()
