from datetime import date
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as
from test_inventory_v012 import setup_inventory, MAKER, approve_and_submit
from velora_erp.finance.pricing import raw_price, round_price, price_row, get_inventory_cost


def _customer_and_revenue():
    customer = __import__("velora").get_list("Customer", fields=["name"], limit=1)[0]["name"]
    revenue = __import__("velora").get_list("Account", filters={"account_code": "4000"}, fields=["name"], limit=1)[0]["name"]
    return customer, revenue


def test_markup_margin_and_rounding_arithmetic():
    assert raw_price(100, 20, "Markup on Cost") == Decimal("120")
    assert raw_price(100, 20, "Margin on Selling Price") == Decimal("125")
    assert raw_price(100, 100, "Margin on Selling Price") is None
    assert round_price(122.5, 5) == Decimal("125.00")


def test_cost_floor_blocks_sales_order_below_inventory_cost(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, _ = _customer_and_revenue()
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="Selling Below Cost"):
                new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                    lines=[{"item_code": item.name, "description": "Below cost", "quantity": 2, "uom": "Each", "rate": 95}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_cost_floor_counts_invoice_line_discounts(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, revenue = _customer_and_revenue()
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="Selling Below Cost"):
                new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(),
                    party=customer, currency="NGN", exchange_rate=1, narration="Discounted below cost",
                    lines=[{"item_code": item.name, "quantity": 2, "uom": "Each", "rate": 120,
                            "discount_amount": 25, "amount": 190, "account": revenue, "description": "Stock item"}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_cost_floor_counts_foreign_exchange_rate(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, revenue = _customer_and_revenue()
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="Selling Below Cost"):
                new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(),
                    party=customer, currency="USD", exchange_rate=1500, narration="FX below cost",
                    lines=[{"item_code": item.name, "quantity": 1, "uom": "Each", "rate": 0.05,
                            "amount": 0.05, "account": revenue, "description": "Stock item"}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_group_item_default_price_hierarchy_and_fixed_price(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, _ = _customer_and_revenue()
        settings = get_doc("Inventory Settings", "Primary Inventory Settings")
        settings.enable_cost_based_selling_price = 1
        settings.default_selling_margin_percent = 5
        settings.selling_price_basis = "Markup on Cost"
        settings.save(ignore_permissions=True)
        group = get_doc("Customer Group", "CG")
        group.selling_margin_percent = 20
        group.save(ignore_permissions=True)
        product = get_doc("Inventory Item", item.name)
        product.selling_margin_percent = 10
        product.save(ignore_permissions=True)
        result = price_row(doctype="Sales Order", item_code=item.name, customer=customer, currency="NGN", exchange_rate=1,
            quantity=2, conversion_factor=1, price_basis="Automatic")
        assert result["price"] == Decimal("120.00")
        assert result["amount"] == Decimal("240.00")
        assert result["group_price"] == Decimal("120.00")
        assert result["item_price"] == Decimal("110.00")
        assert result["default_price"] == Decimal("105.00")
        product = get_doc("Inventory Item", item.name)
        product.pricing_mode = "Fixed Price"
        product.standard_selling_rate = 80
        product.save(ignore_permissions=True)
        with pytest.raises(ValidationError, match="Selling Below Cost"):
            new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                lines=[{"item_code": item.name, "description": "Fixed price below cost", "quantity": 1, "uom": "Each", "rate": 80}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_manual_price_does_not_bypass_cost_floor(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, _ = _customer_and_revenue()
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="Selling Below Cost"):
                new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                    lines=[{"item_code": item.name, "description": "Manual below cost", "quantity": 1, "uom": "Each",
                            "rate": 90, "price_basis": "Manual"}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_live_row_price_provider_returns_group_item_and_default_prices(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, _ = _customer_and_revenue()
        settings = get_doc("Inventory Settings", "Primary Inventory Settings")
        settings.enable_cost_based_selling_price = 1
        settings.default_selling_margin_percent = 5
        settings.save(ignore_permissions=True)
        group = get_doc("Customer Group", "CG")
        group.selling_margin_percent = 20
        group.save(ignore_permissions=True)
        from velora_erp.finance.pricing import get_row_prices
        rows = get_row_prices("Sales Order", {"customer": customer, "currency": "NGN", "exchange_rate": 1,
            "rows": [{"index": 0, "item_code": item.name, "quantity": 2, "price_basis": "Automatic"}]})
        assert rows[0]["price"] == Decimal("120.00")
        assert rows[0]["group_price"] == Decimal("120.00")
    finally:
        velora.shutdown()


def test_cost_floor_uses_current_stock_ledger_valuation_not_stale_standard_rate(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, _ = _customer_and_revenue()
        with session_as(MAKER):
            reconciliation = new_doc("Stock Reconciliation", posting_date=date.today(), warehouse=warehouse.name,
                remarks="Set current valuation above standard fallback",
                items=[{"item_code": item.name, "physical_qty": 5, "proposed_rate": 120}]).insert(ignore_permissions=True)
        approve_and_submit(reconciliation)
        cost, source = get_inventory_cost(item.name)
        assert cost == Decimal("120")
        assert source == "Current Stock Ledger valuation"
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="Selling Below Cost"):
                new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                    lines=[{"item_code": item.name, "description": "Below current carrying cost", "quantity": 1,
                            "uom": "Each", "rate": 110}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_framework_document_pricing_api_uses_installed_provider(tmp_path):
    from fastapi.testclient import TestClient
    from velora.api.app import create_app
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, _ = _customer_and_revenue()
        settings = get_doc("Inventory Settings", "Primary Inventory Settings")
        settings.enable_cost_based_selling_price = 1
        settings.default_selling_margin_percent = 10
        settings.save(ignore_permissions=True)
        client = TestClient(create_app(auto_init=False))
        response = client.post("/api/document-pricing/Sales%20Order", headers={
            "X-Velora-User": MAKER.user, "X-Velora-Roles": "Accountant",
        }, json={"customer": customer, "currency": "NGN", "exchange_rate": 1,
                 "rows": [{"index": 0, "item_code": item.name, "quantity": 2, "price_basis": "Automatic"}]})
        assert response.status_code == 200, response.text
        result = response.json()["data"][0]
        assert result["price"] == 110
        assert result["amount"] == 220
    finally:
        velora.shutdown()


def test_last_purchase_cost_refresh_includes_landed_cost(tmp_path):
    from test_inventory_v012 import APPROVER
    from velora_erp.finance.document_flow.conversion import create_document_from
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        supplier = __import__("velora").get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        expense = __import__("velora").get_list("Account", filters={"account_code": "5000"}, fields=["name"], limit=1)[0]["name"]
        with session_as(MAKER):
            order = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                lines=[{"item_code": item.name, "description": "Pricing cost receipt", "quantity": 2, "uom": "Each", "rate": 100}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            order = get_doc("Purchase Order", order.name)
            receipt = create_document_from("Purchase Order", order.name, "Purchase Receipt", {"warehouse": warehouse.name})
            receipt.submit(ignore_permissions=True)
            receipt = get_doc("Purchase Receipt", receipt.name)
            product = get_doc("Inventory Item", item.name)
            assert product.last_purchase_cost == 100
            voucher = new_doc("Landed Cost Voucher", voucher_date=date.today(), purchase_receipt=receipt.name,
                currency="NGN", exchange_rate=1, allocation_method="By Value", narration="Freight for cost floor",
                charges=[{"description": "Freight", "charge_account": expense, "amount": 40}],
                allocations=[{"item_code": item.name, "source_line": receipt.lines[0].name, "quantity": 2, "item_value": 200}]).insert(ignore_permissions=True)
        with session_as(APPROVER):
            voucher = get_doc("Landed Cost Voucher", voucher.name)
            voucher.approval_status = "Approved"
            voucher.save(ignore_permissions=True)
            voucher.submit(ignore_permissions=True)
        product = get_doc("Inventory Item", item.name)
        assert product.last_purchase_cost == 120
        assert product.last_purchase_reference == receipt.name
        cost, source = get_inventory_cost(item.name)
        assert cost == Decimal("120")
        assert "Last Purchase Cost" in source
    finally:
        velora.shutdown()


def test_fifo_delivery_rechecks_actual_issue_layer_cost(tmp_path):
    from velora_erp.finance.document_flow.conversion import create_document_from
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer = __import__("velora").get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = __import__("velora").get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        product = get_doc("Inventory Item", item.name)
        product.valuation_method = "FIFO"
        product.save(ignore_permissions=True)
        with session_as(MAKER):
            for price in (200, 100):
                order = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                    lines=[{"item_code": item.name, "description": "FIFO receipt", "quantity": 5, "uom": "Each", "rate": price}]).insert(ignore_permissions=True)
                order.submit(ignore_permissions=True)
                order = get_doc("Purchase Order", order.name)
                receipt = create_document_from("Purchase Order", order.name, "Purchase Receipt", {"warehouse": warehouse.name})
                receipt.submit(ignore_permissions=True)
            # Latest purchase cost is 100, so the 150 order price passes order-time validation.
            sales = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                lines=[{"item_code": item.name, "description": "FIFO sale", "quantity": 1, "uom": "Each", "rate": 150}]).insert(ignore_permissions=True)
            sales.submit(ignore_permissions=True)
            sales = get_doc("Sales Order", sales.name)
            delivery = create_document_from("Sales Order", sales.name, "Delivery Note", {"warehouse": warehouse.name})
            with pytest.raises(ValidationError, match="Selling Below Cost at Dispatch"):
                delivery.submit(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_sales_and_receipt_uom_conversion_factor_is_applied_to_stock_ledger(tmp_path):
    from velora_erp.finance.document_flow.conversion import create_document_from
    from velora_erp.finance.inventory.ledger import get_stock_balance
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer = __import__("velora").get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = __import__("velora").get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        with session_as(MAKER):
            order = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                lines=[{"item_code": item.name, "description": "Box of ten", "quantity": 2, "uom": "Box",
                        "conversion_factor": 10, "rate": 1000}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            order = get_doc("Purchase Order", order.name)
            receipt = create_document_from("Purchase Order", order.name, "Purchase Receipt", {"warehouse": warehouse.name})
            receipt.submit(ignore_permissions=True)
            balance = get_stock_balance(item.name, warehouse.name)
            assert balance["qty"] == 20
            assert balance["rate"] == 100
            sales = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                lines=[{"item_code": item.name, "description": "Box sale", "quantity": 1, "uom": "Box",
                        "conversion_factor": 10, "rate": 1100}]).insert(ignore_permissions=True)
            sales.submit(ignore_permissions=True)
            sales = get_doc("Sales Order", sales.name)
            delivery = create_document_from("Sales Order", sales.name, "Delivery Note", {"warehouse": warehouse.name})
            delivery.submit(ignore_permissions=True)
            balance = get_stock_balance(item.name, warehouse.name)
            assert balance["qty"] == 10
    finally:
        velora.shutdown()


def test_sales_order_applies_automatic_margin_price_before_calculating_total(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, _ = _customer_and_revenue()
        settings = get_doc("Inventory Settings", "Primary Inventory Settings")
        settings.enable_cost_based_selling_price = 1
        settings.default_selling_margin_percent = 15
        settings.selling_price_basis = "Markup on Cost"
        settings.save(ignore_permissions=True)
        with session_as(MAKER):
            order = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                lines=[{"item_code": item.name, "description": "Automatic price", "quantity": 2,
                        "uom": "Each", "conversion_factor": 1, "price_basis": "Automatic", "rate": 0}]).insert(ignore_permissions=True)
        assert order.lines[0].rate == 115
        assert order.lines[0].amount == 230
        assert order.lines[0].cost_rate == 100
        assert order.lines[0].price_note == "Default margin"
    finally:
        velora.shutdown()


def test_landed_cost_with_uom_conversion_is_allocated_per_stock_unit(tmp_path):
    from test_inventory_v012 import APPROVER
    from velora_erp.finance.document_flow.conversion import create_document_from
    from velora_erp.finance.inventory.ledger import get_stock_balance
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        supplier = __import__("velora").get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        expense = __import__("velora").get_list("Account", filters={"account_code": "5000"}, fields=["name"], limit=1)[0]["name"]
        with session_as(MAKER):
            order = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                lines=[{"item_code": item.name, "description": "Boxes of ten", "quantity": 2, "uom": "Box",
                        "conversion_factor": 10, "rate": 1000}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            receipt = create_document_from("Purchase Order", order.name, "Purchase Receipt", {"warehouse": warehouse.name})
            receipt.submit(ignore_permissions=True)
            voucher = new_doc("Landed Cost Voucher", voucher_date=date.today(), purchase_receipt=receipt.name,
                currency="NGN", exchange_rate=1, allocation_method="By Quantity", narration="Freight per stock unit",
                charges=[{"description": "Freight", "charge_account": expense, "amount": 200}],
                allocations=[{"item_code": item.name, "source_line": receipt.lines[0].name, "quantity": 20, "item_value": 2000}]).insert(ignore_permissions=True)
        with session_as(APPROVER):
            voucher = get_doc("Landed Cost Voucher", voucher.name)
            voucher.approval_status = "Approved"
            voucher.save(ignore_permissions=True)
            voucher.submit(ignore_permissions=True)
        balance = get_stock_balance(item.name, warehouse.name)
        product = get_doc("Inventory Item", item.name)
        assert balance["qty"] == 20
        assert balance["value"] == 2200
        assert balance["rate"] == 110
        assert product.last_purchase_cost == 110
    finally:
        velora.shutdown()



def test_explain_price_returns_cost_source_and_candidate_prices(tmp_path):
    from velora_erp.finance.pricing import get_row_prices
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, _ = _customer_and_revenue()
        settings = get_doc("Inventory Settings", "Primary Inventory Settings")
        settings.enable_cost_based_selling_price = 1
        settings.default_selling_margin_percent = 20
        settings.save(ignore_permissions=True)
        with session_as(MAKER):
            result = get_row_prices("Sales Order", {
                "customer": customer,
                "currency": "NGN",
                "exchange_rate": 1,
                "explain": {"item_code": item.name, "uom": "Each", "conversion_factor": 1},
            })
        assert result["applicable"] is True
        assert result["pricing_enabled"] is True
        assert result["cost_per_uom_base"] == Decimal("100.00")
        assert result["chosen_price"] == Decimal("120.00")
        assert result["cost_source"]
        assert result["candidates"][0]["basis"] == "default"
    finally:
        velora.shutdown()


def test_sales_margin_analysis_uses_invoice_cost_snapshot_and_base_currency(tmp_path):
    from velora_erp.finance.report.sales_margin_analysis.sales_margin_analysis import execute
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, revenue = _customer_and_revenue()
        settings = get_doc("Inventory Settings", "Primary Inventory Settings")
        settings.block_selling_below_cost = 1
        settings.save(ignore_permissions=True)
        with session_as(MAKER):
            invoice = new_doc(
                "Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(),
                party=customer, currency="NGN", exchange_rate=1, narration="Margin analysis test",
                lines=[{"item_code": item.name, "quantity": 1, "uom": "Each", "rate": 120,
                        "amount": 120, "account": revenue, "description": "Inventory sale"}],
            ).insert(ignore_permissions=True)
        approve_and_submit(invoice)
        with session_as(MAKER):
            report = execute({"from_date": date.today().isoformat(), "to_date": date.today().isoformat()})
        data = [row.values for row in report.rows if row.type == "data"]
        assert len(data) == 1
        assert data[0]["net_sales_base"] == Decimal("120.00")
        assert data[0]["cost_base"] == Decimal("100.00")
        assert data[0]["gross_profit_base"] == Decimal("20.00")
        assert data[0]["gross_margin_percent"] == Decimal("16.67")
    finally:
        velora.shutdown()


def _receive(item, warehouse, supplier, price, qty=5):
    from velora_erp.finance.document_flow.conversion import create_document_from
    order = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
        lines=[{"item_code": item.name, "description": "Cost history", "quantity": qty, "uom": "Each", "rate": price}]).insert(ignore_permissions=True)
    order.submit(ignore_permissions=True)
    create_document_from("Purchase Order", order.name, "Purchase Receipt", {"warehouse": warehouse.name}).submit(ignore_permissions=True)


def test_cost_basis_policy_last_average_fifo_highest_and_overrides(tmp_path):
    from velora_erp.finance.pricing import cost_basis_for, cost_methods
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        supplier = __import__("velora").get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        product = get_doc("Inventory Item", item.name)
        product.valuation_method = "FIFO"; product.save(ignore_permissions=True)
        with session_as(MAKER):
            for price in (200, 100, 150):                          # oldest -> newest, 5 units each
                _receive(item, warehouse, supplier, price)
        methods = cost_methods(item.name)
        assert methods["Last Purchase Cost"][0] == Decimal("150")
        assert methods["Simple Average of Last Purchases"][0] == Decimal("150") and methods["Weighted Average of Last Purchases"][0] == Decimal("150")   # equal quantities: both the same
        assert methods["FIFO (Oldest Stock on Hand)"][0] == Decimal("200")                    # the 200 layer is still untouched
        settings = get_doc("Inventory Settings", "Primary Inventory Settings")
        want = {"Last Purchase Cost": 150, "Simple Average of Last Purchases": 150, "Weighted Average of Last Purchases": 150, "FIFO (Oldest Stock on Hand)": 200, "Highest of These (Safest)": 200}
        for basis, cost in want.items():
            settings.selling_cost_basis = basis; settings.save(ignore_permissions=True)
            got, source = get_inventory_cost(item.name)
            assert got == Decimal(cost), (basis, got, source)
        # the average looks at 3 purchases by default; averaging only the last two gives (100+150)/2
        settings.selling_cost_basis = "Simple Average of Last Purchases"; settings.save(ignore_permissions=True)
        assert cost_methods(item.name, settings={"purchases_to_average": 2})["Simple Average of Last Purchases"][0] == Decimal("125")
        # item group, then item, override the company policy
        new_doc("Item Group", group_name="Factory Goods").insert(ignore_permissions=True)
        product = get_doc("Inventory Item", item.name)
        product.item_group = "Factory Goods"; product.save(ignore_permissions=True)
        group = get_doc("Item Group", "Factory Goods")
        group.selling_cost_basis = "FIFO (Oldest Stock on Hand)"; group.save(ignore_permissions=True)
        assert cost_basis_for(get_doc("Inventory Item", item.name)) == ("FIFO (Oldest Stock on Hand)", "Item Group Factory Goods")
        product = get_doc("Inventory Item", item.name)
        product.selling_cost_basis = "Last Purchase Cost"; product.save(ignore_permissions=True)
        assert cost_basis_for(get_doc("Inventory Item", item.name)) == ("Last Purchase Cost", "Item")
        assert get_inventory_cost(item.name)[0] == Decimal("150")
        with pytest.raises(ValidationError, match="between 3 and 5"):
            settings.purchases_to_average = 9; settings.save(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_minimum_profit_blocks_selling_at_cost_and_price_follows_the_chosen_cost(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, _ = _customer_and_revenue()
        supplier = __import__("velora").get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        with session_as(MAKER):
            for price in (200, 100):
                _receive(item, warehouse, supplier, price)
        settings = get_doc("Inventory Settings", "Primary Inventory Settings")
        settings.selling_cost_basis = "Highest of These (Safest)"
        settings.minimum_profit_percent = 10
        settings.enable_cost_based_selling_price = 1
        settings.default_selling_margin_percent = 20
        settings.save(ignore_permissions=True)
        # cost is the highest method (FIFO layer at 200): price = 200 x 1.20 = 240, minimum allowed = 220
        priced = price_row(doctype="Sales Order", item_code=item.name, customer=customer, currency="NGN", exchange_rate=1)
        assert priced["price"] == Decimal("240.00") and "Highest of" in priced["cost_source"]
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="minimum profit of 10"):
                new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                    lines=[{"item_code": item.name, "description": "At cost", "quantity": 1, "uom": "Each", "rate": 215, "price_basis": "Manual"}]).insert(ignore_permissions=True)
            ok = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                lines=[{"item_code": item.name, "description": "At floor", "quantity": 1, "uom": "Each", "rate": 220, "price_basis": "Manual"}]).insert(ignore_permissions=True)
            assert ok.name
        from velora_erp.finance.pricing import explain_item_price
        info = explain_item_price(item.name)
        assert info["cost_basis"] == "Highest of These (Safest)" and info["lowest_allowed_per_uom_base"] == Decimal("220.00")
        assert {"Last Purchase Cost", "FIFO (Oldest Stock on Hand)"} <= set(info["cost_methods"])
    finally:
        velora.shutdown()


def test_simple_and_weighted_average_differ_when_quantities_differ_and_price_is_explained_in_words(tmp_path):
    from velora_erp.finance.pricing import cost_methods, explain_item_price
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        customer, _ = _customer_and_revenue()
        supplier = __import__("velora").get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        with session_as(MAKER):
            _receive(item, warehouse, supplier, 100, qty=10)
            _receive(item, warehouse, supplier, 200, qty=30)
        m = cost_methods(item.name)
        assert m["Simple Average of Last Purchases"][0] == Decimal("150")          # (100 + 200) / 2
        assert m["Weighted Average of Last Purchases"][0] == Decimal("175")        # (10x100 + 30x200) / 40
        settings = get_doc("Inventory Settings", "Primary Inventory Settings")
        settings.selling_cost_basis = "Weighted Average of Last Purchases"
        settings.enable_cost_based_selling_price = 1; settings.default_selling_margin_percent = 20; settings.minimum_profit_percent = 5
        settings.save(ignore_permissions=True)
        story = "\n".join(explain_item_price(item.name, customer=customer)["narrative"])
        assert "Weighted Average of Last Purchases" in story and "Inventory Settings" in story
        assert "175.00" in story and "× (1 + 20" in story and "210.00" in story       # 175 x 1.20
        assert "35.00" in story and "20.00% on cost" in story                        # profit per unit
        assert "183.75" in story and "minimum profit of 5" in story                  # floor = 175 x 1.05
    finally:
        velora.shutdown()
