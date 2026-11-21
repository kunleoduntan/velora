from decimal import Decimal, ROUND_HALF_UP
from velora import Document, throw, get_doc, new_doc
from velora_erp.finance.invoices import validate_invoice, submit_invoice
from velora_erp.finance.source_documents import ensure_approved
from velora_erp.finance.doctype._utils import db_update_child


class PurchaseInvoice(Document):
    # Cancelling this document unlinks or removes these by itself (see finance/cancellation.py), so they do not block it.
    ignore_linked_doctypes = ("Recognition Schedule", "Schedule Recognition", "Intercompany Cost Allocation", "Fixed Asset", "Receipt", "Payment")

    def validate(self):
        validate_invoice(self, "Purchase")
        from velora_erp.finance.fulfilment import check_not_over_billed
        check_not_over_billed(self, source_doctype="Purchase Order")

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        # Create subledger asset identities inside the same submit transaction so
        # the central invoice adapter can tag the acquisition ledger lines by asset.
        created_by_line = {}
        for line in self.lines or []:
            if not getattr(line, "is_fixed_asset", False):
                continue
            category = get_doc("Fixed Asset Category", line.asset_category, ignore_permissions=True)
            quantity = int(line.quantity)
            total_base = (Decimal(str(line.amount)) * Decimal(str(self.exchange_rate or 1))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            unit_cost = (total_base / Decimal(quantity)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            residual_base = (Decimal(str(line.residual_value or 0)) * Decimal(str(self.exchange_rate or 1))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            created = []
            for index in range(quantity):
                name = line.asset_name if quantity == 1 else f"{line.asset_name} {index + 1}"
                asset = new_doc(
                    "Fixed Asset", asset_name=name, asset_category=line.asset_category,
                    acquisition_date=self.invoice_date,
                    acquisition_cost=unit_cost, accumulated_depreciation=0,
                    impairment_loss=0, revaluation_adjustment=0, residual_value=residual_base,
                    useful_life_months=line.useful_life_months, asset_account=line.account,
                    accumulated_depreciation_account=category.accumulated_depreciation_account,
                    cost_centre=line.cost_centre, business_unit=line.business_unit,
                    source_purchase=self.name, status="Active",
                    depreciation_method=line.depreciation_method or category.default_depreciation_method or "Straight Line",
                    depreciation_rate=line.depreciation_rate or category.default_reducing_balance_rate,
                    depreciation_expense_account=category.depreciation_expense_account,
                    depreciation_start_date=self.invoice_date,
                    total_units_of_production=line.total_units_of_production,
                    impairment_account=category.impairment_account,
                    impairment_expense_account=category.impairment_expense_account,
                    impairment_reversal_account=category.impairment_reversal_account,
                    components=[{"component_code":c.component_code,"component_name":c.component_name,"acquisition_cost":(Decimal(str(c.acquisition_cost))*Decimal(str(self.exchange_rate or 1))).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP),"residual_value":(Decimal(str(c.residual_value or 0))*Decimal(str(self.exchange_rate or 1))).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP),"useful_life_months":c.useful_life_months,"depreciation_method":c.depreciation_method,"depreciation_rate":c.depreciation_rate,"depreciation_start_date":c.depreciation_start_date or self.invoice_date,"carrying_amount":(Decimal(str(c.acquisition_cost))*Decimal(str(self.exchange_rate or 1))).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP),"accumulated_depreciation":0,"depreciation_expense_account":c.depreciation_expense_account or category.depreciation_expense_account,"accumulated_depreciation_account":c.accumulated_depreciation_account or category.accumulated_depreciation_account,"total_units_of_production":c.total_units_of_production,"units_produced_to_date":0} for c in (self.asset_components or []) if c.asset_line_name==line.asset_name],
                )
                asset.flags.trusted_source=True
                asset.insert(ignore_permissions=True)
                created.append(asset.name)
            line.created_assets = ", ".join(created)
            created_by_line[line.name] = (created, unit_cost)

        submit_invoice(self, "Purchase")
        if getattr(self, "update_stock", 0):
            from velora_erp.finance.inventory.ledger import post_stock_movement, is_stock_item
            own = [l for l in (self.lines or []) if is_stock_item(getattr(l, "item_code", None)) and not getattr(l, "purchase_receipt", None)]
            if own:
                # The invoice already debited Inventory and credited the supplier; only the stock ledger is written here.
                post_stock_movement(source=self, posting_date=self.posting_date, warehouse=self.warehouse, lines=own, direction=1,
                    rate_field="valuation_rate", accounting_event=None, remarks=f"Purchase Invoice {self.name} (Update Stock)")
        from velora_erp.finance.fulfilment import refresh_for
        refresh_for(self)                                                       # orders and receipts behind this invoice show Billed %
        from velora_erp.finance.asset_history import record_asset_history
        for line in self.lines or []:
            if line.name not in created_by_line:
                continue
            created, unit_cost = created_by_line[line.name]
            db_update_child("Purchase Invoice Line", line.name, created_assets=", ".join(created))
            for asset_name in created:
                asset = get_doc("Fixed Asset", asset_name, ignore_permissions=True)
                record_asset_history(asset, "Acquisition", self.invoice_date, self.doctype, self.name,
                    from_values={}, to_values={"status": "Active", "acquisition_cost": str(unit_cost),
                    "carrying_amount": str(asset.carrying_amount)}, reason=f"Capitalised from Purchase Invoice {self.name}")


    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Purchase Invoice cannot be deleted.")
