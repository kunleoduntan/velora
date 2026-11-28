"""WHT on a receipt flows to the tax ledger beside every other source; sample print formats render; amounts read in words."""
from datetime import date
from decimal import Decimal

import velora
from velora import get_list, new_doc
from velora.permissions import session_as

from test_cash_transactions import MAKER, approve, setup_cash
from velora_erp.print_samples import install_samples
from velora_erp.tax.report.wht_all_sources.wht_all_sources import execute

D = Decimal


def test_receipt_wht_line_reaches_the_all_sources_report_and_prints(tmp_path):
    from test_invoices_v08 import APPROVER, approve_submit
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        wht = new_doc("Account", account_code="1300", account_name="WHT Credit", account_group="A", account_type="CLEARING", allow_manual_posting=1).insert(ignore_permissions=True)
        jur = new_doc("Tax Jurisdiction", jurisdiction_code="NG", jurisdiction_name="Nigeria", level="Federal").insert(ignore_permissions=True)
        approve_submit(new_doc("Tax Rule", rule_code="WHT5C", rule_name="WHT 5", tax_type="WHT", jurisdiction=jur.name, method="Percentage", rate=5, effective_from=date(date.today().year, 1, 1),
                               tax_account=wht.name).insert(ignore_permissions=True))
        with session_as(MAKER):
            r = new_doc("Receipt", receipt_date=date.today(), posting_date=date.today(), purpose="Customer Receipt", currency="NGN", exchange_rate=1, cash_account=accounts["1000"].name,
                        narration="Settlement net of withholding tax",
                        lines=[{"account": accounts["1100"].name, "amount": 2500, "party_type": "Customer", "party": customer.name, "description": "Invoice settlement", "entry_side": "Credit"},
                               {"account": wht.name, "amount": 125, "entry_side": "Debit", "description": "WHT 5% deducted by customer", "tax_code": "WHT5C", "tax_rate": 5, "taxable_amount": 2500, "tax_amount": 125}]).insert()
        r = approve(r)
        y = date.today().year
        with session_as(APPROVER):
            rb = execute({"from_date": date(y, 1, 1), "to_date": date(y, 12, 31)})
        text = str(getattr(rb, "rows", None) or rb.__dict__)
        assert "Receipt" in text and "125" in text
        from velora import printing
        out = install_samples()
        assert len(out["installed"]) == 3 and install_samples()["installed"] == []
        with session_as(APPROVER):
            for fmt in printing.formats_for("Receipt"):
                page = printing.render(fmt["id"], "Receipt", r.name)
                assert r.name in page and "YOUR ORGANISATION NAME" in page
            html = printing.render(printing.formats_for("Receipt")[0]["id"], "Receipt", r.name)
            assert "naira" in html
    finally:
        velora.shutdown()
