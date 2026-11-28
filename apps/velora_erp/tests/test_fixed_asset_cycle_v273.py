"""Fixed asset lifecycle: the asset register must reconcile to the general ledger after purchase, depreciation, revaluation and disposal."""
from datetime import date, timedelta
from decimal import Decimal
import velora
from velora import get_doc, get_list, new_doc
from velora.permissions import session_as
from velora.reporting.runner import run_report
from test_finance_operations_v025_integration import setup_ops, approve_submit, MAKER

D = lambda v: Decimal(str(v or 0))


def _reconciled():
    result = run_report("Fixed Asset Reconciliation", {})
    rows = [r.values for r in result.rows if r.type == "data"]
    return rows, [r for r in rows if r["status"] != "Reconciled"]


def _ledger_totals():
    rows = get_list("Account Ledger Record", fields=["debit", "credit"], limit=10000)
    return sum(D(r["debit"]) for r in rows), sum(D(r["credit"]) for r in rows)


def test_register_reconciles_to_ledger_through_the_whole_lifecycle(tmp_path):
    accounts, supplier, category = setup_ops(tmp_path)
    try:
        with session_as(MAKER):
            req = new_doc("Fixed Asset Request", request_date=date.today(), purpose="Server", items=[{"description": "Server", "asset_category": category.name, "quantity": 1, "estimated_unit_cost": 1200}]).insert()
        approve_submit(req)
        with session_as(MAKER):
            purchase = new_doc("Fixed Asset Purchase", purchase_date=date.today(), request_reference=req.name, purchase_type="Supplier Credit",
                               supplier=supplier.name, supplier_payable_account=accounts["2100"].name, currency="NGN", exchange_rate=1,
                               items=[{"asset_name": "Server 01", "asset_category": category.name, "quantity": 1, "unit_cost": 1200, "asset_account": accounts["1500"].name,
                                       "useful_life_months": 12, "residual_value": 0}]).insert()
        purchase = approve_submit(purchase)
        asset = get_doc("Fixed Asset", purchase.created_assets, ignore_permissions=True)
        rows, bad = _reconciled()
        assert rows and not bad, f"after purchase: {bad}"
        assert get_doc("Account", accounts["1500"].name).name  # sanity
        # ---- one month of straight-line depreciation: 1200 / 12 = 100
        book = get_list("Fixed Asset Depreciation Book", filters={"is_default": 1, "disabled": 0}, fields=["name"], limit=1)
        book_args = {"depreciation_book": book[0]["name"]} if book else {}
        start = asset.depreciation_start_date or date.today()
        with session_as(MAKER):
            run = new_doc("Fixed Asset Depreciation Run", **book_args, period_start=start, period_end=start + timedelta(days=29),
                          posting_date=start + timedelta(days=29), approval_status="Pending", lines=[{"asset": asset.name}]).insert()
        run = approve_submit(run)
        asset = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
        assert D(asset.accumulated_depreciation) > 0 and D(asset.carrying_amount) == D(asset.acquisition_cost) - D(asset.accumulated_depreciation)
        rows, bad = _reconciled()
        assert not bad, f"after depreciation: {bad}"
        # ---- the depreciation expense in the ledger equals what the register accumulated
        exp = sum(D(r["debit"]) - D(r["credit"]) for r in get_list("Account Ledger Record", filters={"account": accounts["5400"].name}, fields=["debit", "credit"], limit=1000))
        assert exp == D(asset.accumulated_depreciation)
        # ---- upward revaluation: the register and the ledger must still agree
        asset = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
        with session_as(MAKER):
            reval = new_doc("Fixed Asset Revaluation", asset=asset.name, revaluation_date=start + timedelta(days=29), valuation_method="Market Comparable",
                            new_carrying_amount=D(asset.carrying_amount) + 100, revaluation_surplus_account=accounts["3000"].name, reason="Independent valuation").insert()
        approve_submit(reval)
        asset = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
        assert D(asset.revaluation_adjustment) == D(100)
        rows, bad = _reconciled()
        assert not bad, f"after revaluation: {bad}"
        # ---- sale at carrying amount + 50
        with session_as(MAKER):
            disposal = new_doc("Fixed Asset Disposal", asset=asset.name, disposal_date=start + timedelta(days=30), disposal_type="Sale",
                               disposal_proceeds=D(asset.carrying_amount) + 50, disposal_costs=0, proceeds_account=accounts["1000"].name, buyer="Buyer", physical_verification_done=1, verified_by="Asset Manager", verification_date=date.today(), gain_account=accounts["4000"].name, loss_account=accounts["5300"].name, reason="Sold").insert()
        disposal = approve_submit(disposal)
        asset = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
        assert asset.status == "Disposed" and D(disposal.gain_loss) == D(50)
        rows, bad = _reconciled()
        assert not bad, f"after disposal: {bad}"
        dr, cr = _ledger_totals()
        assert dr == cr, "ledger must balance"
        # cost and accumulated depreciation are fully removed from the control accounts
        for code in ("1500", "1590"):
            net = sum(D(r["debit"]) - D(r["credit"]) for r in get_list("Account Ledger Record", filters={"account": accounts[code].name}, fields=["debit", "credit"], limit=1000))
            assert net == 0, f"{code} must be nil after disposal, is {net}"
    finally:
        velora.shutdown()


def test_repairs_tagged_to_an_asset_appear_in_the_maintenance_report(tmp_path):
    accounts, supplier, category = setup_ops(tmp_path)
    try:
        with session_as(MAKER):
            req = new_doc("Fixed Asset Request", request_date=date.today(), purpose="Server", items=[{"description": "Server", "asset_category": category.name, "quantity": 1, "estimated_unit_cost": 1200}]).insert()
        approve_submit(req)
        with session_as(MAKER):
            purchase = new_doc("Fixed Asset Purchase", purchase_date=date.today(), request_reference=req.name, purchase_type="Supplier Credit",
                               supplier=supplier.name, supplier_payable_account=accounts["2100"].name, currency="NGN", exchange_rate=1,
                               items=[{"asset_name": "Server 01", "asset_category": category.name, "quantity": 1, "unit_cost": 1200, "asset_account": accounts["1500"].name,
                                       "useful_life_months": 12, "residual_value": 0}]).insert()
        purchase = approve_submit(purchase)
        asset = get_doc("Fixed Asset", purchase.created_assets, ignore_permissions=True)
        T = date.today()
        with session_as(MAKER):
            jev = new_doc("Journal Entry Voucher", title="Repair", voucher_date=T, posting_date=T, currency="NGN", exchange_rate=1, narration="Fan replaced",
                          lines=[{"trans_date": T, "transaction_description": "Fan replacement", "account_type": "Account GL", "party": accounts["5000"].name,
                                  "trans_effect": "Debit", "amount": 75, "corresponding_account": accounts["1000"].name, "repair_asset": asset.name}]).insert(ignore_permissions=True)
        approve_submit(jev)
        result = run_report("Fixed Asset Maintenance Cost", {"asset": asset.name})
        data = [r.values for r in result.rows if r.type == "data"]
        assert len(data) == 1 and D(data[0]["amount"]) == 75
    finally:
        velora.shutdown()
