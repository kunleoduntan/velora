"""Exchange-rate master, base-currency columns and rate-driven purchase lines."""
from datetime import date, timedelta
from decimal import Decimal
import velora
from velora import get_doc, get_list, new_doc
from velora.permissions import session_as
from test_document_flow import MAKER
from test_inventory_v012 import setup_inventory, approve_and_submit
from velora_erp.finance.multicurrency import lookup_rate

D = lambda v: Decimal(str(v or 0))


def _acct(code):
    return get_list("Account", filters={"account_code": code}, fields=["name"], limit=1)[0]["name"]


def test_rate_master_lookup_and_base_columns_on_orders_and_invoices(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        today = date.today()
        new_doc("Currency Exchange Rate", from_currency="usd", to_currency="NGN", effective_date=today - timedelta(days=30), rate=1400).insert(ignore_permissions=True)
        new_doc("Currency Exchange Rate", from_currency="USD", to_currency="NGN", effective_date=today - timedelta(days=2), rate=1500).insert(ignore_permissions=True)
        assert lookup_rate("USD", "NGN", today - timedelta(days=10)) == D(1400)
        assert lookup_rate("USD", "NGN", today) == D(1500)
        assert round(lookup_rate("NGN", "USD", today), 6) == round(D(1) / D(1500), 6)
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        with session_as(MAKER):
            so = new_doc("Sales Order", document_date=today, party=customer, currency="USD", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "x", "quantity": 4, "uom": "Each", "rate": 200, "revenue_account": _acct("4000")}]).insert(ignore_permissions=True)
        assert D(so.exchange_rate) == D(1500), "an unset rate is taken from the master"
        assert D(so.total_amount) == D(800) and D(so.base_total_amount) == D(1200000)
        assert D(so.lines[0].base_amount) == D(1200000) and D(so.lines[0].base_rate) == D(300000)
        # a purchase invoice line can be entered as rate x quantity less discount; base columns follow
        with session_as(MAKER):
            pi = new_doc("Purchase Invoice", invoice_date=today, posting_date=today, due_date=today, party=supplier, currency="USD", exchange_rate=1450, narration="Imports",
                         lines=[{"account": _acct("5000"), "description": "Freight", "quantity": 10, "uom": "Each", "rate": 50, "discount_percentage": 10, "amount": 1}]).insert(ignore_permissions=True)
        assert D(pi.lines[0].amount) == D(450) and D(pi.net_amount) == D(450)
        assert D(pi.base_net_amount) == D(450) * D(1450) and D(pi.base_grand_total) == D(450) * D(1450)
        assert D(pi.lines[0].base_rate) == D(50) * D(1450)
    finally:
        velora.shutdown()
