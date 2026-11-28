"""Actions from a Fixed Asset (revalue, dispose, impair, transfer, adjust component) and the IAS 16 rule that depreciation is up to date first."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as

from test_finance_operations_v025_integration import setup_ops, approve_submit, MAKER
from velora_erp.finance.document_flow.conversion import create_document_from
from velora_erp.finance.document_flow.registry import get_document_flows

D = lambda v: Decimal(str(v or 0))
ACTIONS = ["Fixed Asset Revaluation", "Fixed Asset Disposal", "Fixed Asset Impairment", "Fixed Asset Transfer", "Fixed Asset Component Adjustment"]


def _asset(tmp_path, acquired=None):
    accounts, supplier, category = setup_ops(tmp_path)
    with session_as(MAKER):
        p = new_doc("Fixed Asset Purchase", purchase_date=acquired or date.today(), purchase_type="Supplier Credit", supplier=supplier.name, supplier_payable_account=accounts["2100"].name,
                    currency="NGN", exchange_rate=1, items=[{"asset_name": "Truck", "asset_category": category.name, "quantity": 1, "unit_cost": 1200,
                                                             "asset_account": accounts["1500"].name, "useful_life_months": 12, "residual_value": 0}]).insert()
    p = approve_submit(p)
    return accounts, get_doc("Fixed Asset", p.created_assets, ignore_permissions=True)


def test_an_active_asset_offers_its_actions_and_each_opens_prefilled_and_unsaved(tmp_path):
    accounts, asset = _asset(tmp_path)
    try:
        offered = [f["target_doctype"] for f in get_document_flows("Fixed Asset", doc=asset)]
        assert offered == ACTIONS
        with session_as(MAKER):
            d = create_document_from("Fixed Asset", asset.name, "Fixed Asset Disposal")
        assert d["prefill"] and d["doctype"] == "Fixed Asset Disposal"
        v = d["values"]
        assert v["asset"] == asset.name and D(v["carrying_amount"]) == D(asset.carrying_amount)
        assert v["asset_account"] == asset.asset_account and v["accumulated_depreciation_account"] == asset.accumulated_depreciation_account
        with session_as(MAKER):
            r = create_document_from("Fixed Asset", asset.name, "Fixed Asset Revaluation")["values"]
            t = create_document_from("Fixed Asset", asset.name, "Fixed Asset Transfer")["values"]
            i = create_document_from("Fixed Asset", asset.name, "Fixed Asset Impairment")["values"]
        assert D(r["previous_carrying_amount"]) == D(asset.carrying_amount) and i["action"] == "Recognise Impairment"
        assert t["asset"] == asset.name
        for target in ACTIONS:
            assert get_list(target, fields=["name"], limit=1, ignore_permissions=True) == [], f"{target}: nothing is saved until the user saves"
        with pytest.raises(ValidationError):
            create_document_from("Fixed Asset", asset.name, "Sales Invoice")
    finally:
        velora.shutdown()


def test_the_prefilled_disposal_saves_submits_and_a_disposed_asset_offers_nothing(tmp_path):
    accounts, asset = _asset(tmp_path)
    try:
        with session_as(MAKER):
            v = create_document_from("Fixed Asset", asset.name, "Fixed Asset Disposal")["values"]
            disp = new_doc("Fixed Asset Disposal", **v, disposal_type="Scrap", physical_verification_done=1, verified_by="Asset Manager", verification_date=date.today(),
                           loss_account=accounts["5300"].name, reason="Beyond repair").insert()
        approve_submit(disp)
        asset = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
        assert asset.status == "Disposed"
        assert get_document_flows("Fixed Asset", doc=asset) == []
        with pytest.raises(ValidationError, match="Disposed"):
            create_document_from("Fixed Asset", asset.name, "Fixed Asset Revaluation")
    finally:
        velora.shutdown()


def test_rest_api_returns_a_prefill_not_a_saved_document(tmp_path):
    from fastapi.testclient import TestClient
    from velora.api.app import create_app
    accounts, asset = _asset(tmp_path)
    try:
        client = TestClient(create_app(auto_init=False))
        h = {"X-Velora-User": MAKER.user, "X-Velora-Roles": "Accountant"}
        acts = client.get(f"/api/document-flow/Fixed%20Asset/{asset.name}/actions", headers=h)
        assert acts.status_code == 200, acts.text
        assert [a["label"] for a in acts.json()["data"]] == ["Revalue", "Dispose", "Impairment Test", "Transfer", "Adjust Component"]
        res = client.post(f"/api/document-flow/Fixed%20Asset/{asset.name}/create", headers=h, json={"target_doctype": "Fixed Asset Revaluation"})
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["name"] is None and data["prefill"]["asset"] == asset.name and data["source_document"] == asset.name
    finally:
        velora.shutdown()


def test_disposal_and_revaluation_need_depreciation_up_to_date(tmp_path):
    # acquired two months ago, never depreciated
    acquired = (date.today().replace(day=1) - timedelta(days=40)).replace(day=1)
    accounts, asset = _asset(tmp_path, acquired=acquired)
    try:
        asset = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
        if not asset.depreciation_start_date or asset.depreciation_start_date > date.today().replace(day=1) - timedelta(days=1):
            pytest.skip("this category starts depreciation later; the rule does not apply")
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="Run depreciation"):
                new_doc("Fixed Asset Disposal", asset=asset.name, disposal_date=date.today(), disposal_type="Scrap", physical_verification_done=1, verified_by="M", verification_date=date.today(),
                        loss_account=accounts["5300"].name, reason="x").insert()
            with pytest.raises(ValidationError, match="Run depreciation"):
                new_doc("Fixed Asset Revaluation", asset=asset.name, revaluation_date=date.today(), valuation_method="Fair Value", new_carrying_amount=1500,
                        revaluation_surplus_account=accounts["3000"].name, reason="x").insert()
    finally:
        velora.shutdown()
