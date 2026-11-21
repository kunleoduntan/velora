from pathlib import Path

import pytest

import velora
from velora import get_list, new_doc
from velora.exceptions import ValidationError
from velora_erp.setup import after_install


def test_finance_master_data_end_to_end(tmp_path):
    db_path = tmp_path / "veloraerp-finance.db"
    velora.configure(db_url=f"sqlite:///{db_path}", apps=["velora_erp"], developer_mode=True)
    velora.init()
    try:
        velora.migrate()
        after_install()
        from velora.upgrade.patches import run as run_patches
        assert run_patches(["velora_erp"], "post_model_sync") == [
            "velora_erp.patches.v0_2.seed_account_types",
            "velora_erp.patches.v0_3.add_finance_ledger_indexes",
            "velora_erp.patches.v0_4.seed_finance_workspace_and_statements",
            "velora_erp.patches.v0_5.extend_finance_workspace",
            "velora_erp.patches.v0_6.extend_party_ledger_support",
            "velora_erp.patches.v0_7.extend_cash_management_workspace",
            "velora_erp.patches.v0_8.extend_invoice_workspace",
            "velora_erp.patches.v0_10.ensure_commercial_workspaces",
            "velora_erp.patches.v0_11.extend_return_and_landed_cost_workspace",
            "velora_erp.patches.v0_12.ensure_inventory_workspace",
            "velora_erp.patches.v0_13.extend_inventory_workspace",
            "velora_erp.patches.v0_14.extend_inventory_valuation_workspace",
            "velora_erp.patches.v0_15.extend_inventory_pricing_workspace",
            "velora_erp.patches.v0_17.extend_sales_workspace",
            "velora_erp.patches.v0_21.extend_sales_service_workspace",
            "velora_erp.patches.v0_22.ensure_intercompany_account_type",
            "velora_erp.patches.v0_23.ensure_finance_operations_workspaces",
            "velora_erp.patches.v0_24.extend_fixed_asset_workspace",
            "velora_erp.patches.v0_29.extend_deferred_tax_workspace",
            "velora_erp.patches.v0_30.extend_fixed_asset_lifecycle_workspace",
            "velora_erp.patches.v0_31.extend_deferred_tax_approval_inbox",
            "velora_erp.patches.v0_32.extend_period_close_workspace",
            "velora_erp.patches.v0_32.extend_financial_reporting_workspace",
            "velora_erp.patches.v2_71.backfill_invoice_settlement",
            "velora_erp.patches.v2_73.split_salary_structure_tables",
            "velora_erp.patches.v2_83.extend_inventory_workspace",
            "velora_erp.patches.v2_84.apply_record_scopes",
            "velora_erp.patches.v2_85.approval_policy_and_investment_settings",
            "velora_erp.patches.v2_85.extend_inventory_workspace",
            "velora_erp.patches.v2_85.compute_item_selling_prices",
            "velora_erp.patches.v2_87.release_old_default_authority",
            "velora_erp.patches.v2_87.compute_order_fulfilment",
            "velora_erp.patches.v2_89.convert_legacy_reversals",
        ]

        assert len(get_list("Account Type", fields=["name"], limit=100)) == 33

        new_doc("Account Group", group_code="ASSETS", group_name="Assets", root_type="Asset", is_group=1).insert(ignore_permissions=True)
        new_doc("Account Group", group_code="CASH", group_name="Cash and Bank", root_type="Asset", parent_group="ASSETS", is_group=1).insert(ignore_permissions=True)
        bank = new_doc("Account", account_code="100001", account_name="Main Bank", account_group="CASH", account_type="BANK", is_control_account=1, control_account_type="Bank").insert(ignore_permissions=True)
        contra = new_doc("Account", account_code="100002", account_name="Accumulated Depreciation", account_group="ASSETS", account_type="ACCUM_DEPRECIATION").insert(ignore_permissions=True)
        assert bank.root_type == "Asset" and bank.normal_balance == "Debit"
        assert contra.root_type == "Asset" and contra.normal_balance == "Credit"

        with pytest.raises(ValidationError, match="belongs to Liability"):
            new_doc("Account", account_code="200001", account_name="Supplier Control", account_group="ASSETS", account_type="PAYABLE").insert(ignore_permissions=True)

        new_doc("Cost Centre", cost_centre_code="HQ", cost_centre_name="Head Office", is_group=1).insert(ignore_permissions=True)
        new_doc("Cost Centre", cost_centre_code="FIN", cost_centre_name="Finance", parent_cost_centre="HQ").insert(ignore_permissions=True)

        new_doc("Accounting Dimension", dimension_code="REGION", dimension_name="Region", value_source="Dimension Values").insert(ignore_permissions=True)
        parent_value = new_doc("Dimension Value", dimension="REGION", value_code="SOUTH", value_name="South", is_group=1).insert(ignore_permissions=True)
        new_doc("Dimension Value", dimension="REGION", value_code="LAG", value_name="Lagos", parent_value=parent_value.name).insert(ignore_permissions=True)

        new_doc("Financial Statement Row", row_code="ASSETS_ROW", row_label="Assets", statement_type="Statement of Financial Position", row_type="Section", can_contain_rows=1).insert(ignore_permissions=True)
        new_doc("Financial Statement Row", row_code="BANK_ROW", row_label="Cash and Cash Equivalents", statement_type="Statement of Financial Position", parent_row="ASSETS_ROW", row_type="Account Summary").insert(ignore_permissions=True)
        new_doc("Account Statement Mapping", mapping_code="BANK_MAP", account=bank.name, statement_row="BANK_ROW", mapping_basis="Account").insert(ignore_permissions=True)

        with pytest.raises(ValidationError, match="already mapped"):
            new_doc("Account Statement Mapping", mapping_code="BANK_MAP_2", account=bank.name, statement_row="BANK_ROW", mapping_basis="Account").insert(ignore_permissions=True)
    finally:
        velora.shutdown()
