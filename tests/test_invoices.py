"""Customer/Supplier master, Sales/Purchase Invoices, per-invoice settlement by Receipts and Payments, strict parties, reports, the upgrade patch."""
import random
from datetime import date, timedelta
from decimal import Decimal as Dc

import pytest

from velora import get_doc, get_list, new_doc
from velora.exceptions import DocStatusError, PermissionDenied, ValidationError
from velora.permissions import session_as
from velora.reporting.runner import run_report

from test_accounts import MANAGER, VIEWER, books  # noqa: F401
from velora_accounts import common as c, ledger, seed

BANK, D = "Main Bank Account", date(2026, 3, 1)
VAT_O, VAT_I = "VAT 7.5% Output", "VAT 7.5% Input"


@pytest.fixture
def inv(books):  # noqa: F811
    c.set_strict_parties(True)
    for n, days in (("Bola Stores", 30), ("Cato Ltd", 0)):
        new_doc("Customer", customer_name=n, credit_days=days).insert()
    for n in ("Acme Supplies", "Zenith Foods"):
        new_doc("Supplier", supplier_name=n, credit_days=14).insert()
    return books


def bal(account, **kw):
    return ledger.balance(account, **kw)


def sinv(items=((100000, VAT_O),), customer="Bola Stores", d=D, submit=True, **kw):
    doc = new_doc("Sales Invoice", customer=customer, posting_date=d, **kw)
    for i, (rate, tax) in enumerate(items, 1):
        doc.append("items", {"description": f"Item {i}", "quantity": 1, "rate": rate, "tax_code": tax})
    doc.insert()
    return doc.submit() if submit else doc


def pinv(items=((50000, VAT_I),), supplier="Acme Supplies", d=D, account="Office Expenses", submit=True, **kw):
    doc = new_doc("Purchase Invoice", supplier=supplier, posting_date=d, **kw)
    for i, (rate, tax) in enumerate(items, 1):
        doc.append("items", {"description": f"Item {i}", "quantity": 1, "rate": rate, "account": account, "tax_code": tax})
    doc.insert()
    return doc.submit() if submit else doc


def receipt(customer="Bola Stores", amount=107500, rows=(), submit=True, **kw):
    r = new_doc("Receipt", receipt_type="Customer", posting_date=kw.pop("d", D), bank_account=BANK, party=customer, amount=amount, **kw)
    for name, allocated, *disc in rows:
        r.append("invoices", {"invoice": name, "allocated": allocated, "discount": disc[0] if disc else 0})
    r.insert()
    return r.submit() if submit else r


def payment(supplier="Acme Supplies", amount=53750, rows=(), submit=True, **kw):
    p = new_doc("Payment", payment_type="Vendor", posting_date=kw.pop("d", D), bank_account=BANK, party_type="Supplier", party=supplier, amount=amount, **kw)
    for name, allocated, *disc in rows:
        p.append("invoices", {"invoice": name, "allocated": allocated, "discount": disc[0] if disc else 0})
    p.insert()
    return p.submit() if submit else p


def fresh(dt, name):
    return get_doc(dt, name)


def bad(fn, frag, exc=ValidationError):
    with pytest.raises(exc, match=frag):
        fn()


# ============================== masters ==============================
def test_customer_and_supplier_masters(inv):
    bad(lambda: new_doc("Customer", customer_name="Bola Stores").insert(), "already exists|Duplicate", Exception)
    bad(lambda: new_doc("Customer", customer_name="X", credit_days=-1).insert(), "cannot be negative")
    assert new_doc("Customer", customer_name="  Spaced  ").insert().name == "Spaced"
    s = new_doc("Supplier", supplier_name="Pay Me", bank_name="GTBank", account_number="0123456789", default_wht_rate=5).insert()
    assert (s.bank_name, s.account_number, s.status) == ("GTBank", "0123456789", "Active")


def test_tax_code_rules(inv):
    assert {t["name"] for t in get_list("Tax Code", fields=["name"])} == {"VAT 7.5% Output", "VAT 0% Output", "VAT 7.5% Input", "VAT 0% Input"}
    bad(lambda: new_doc("Tax Code", tax_name="Bad", tax_type="VAT Output", rate=101, account="VAT Output").insert(), "between 0 and 100")
    bad(lambda: new_doc("Tax Code", tax_name="Bad", tax_type="VAT Output", rate=5, account="Rent").insert(), "not a Tax account")
    bad(lambda: new_doc("Tax Code", tax_name="Bad", tax_type="VAT Output", rate=5, account="Assets").insert(), "group account")


# ============================== invoices ==============================
def test_sales_invoice_posts_receivable_income_and_vat(inv):
    i = sinv([(100000, VAT_O), (20000.50, "VAT 0% Output")])
    assert (i.net_total, i.tax_total, i.grand_total) == (Dc("120000.50"), Dc("7500.00"), Dc("127500.50"))
    assert (i.outstanding, i.status, i.due_date) == (i.grand_total, "Unpaid", D + timedelta(days=30))              # terms from the customer
    assert bal("Trade Receivables", party="Bola Stores") == Dc("127500.50") and bal("Sales Revenue") == Dc("-120000.50") and bal("VAT Output") == Dc("-7500")
    assert sinv(customer="Cato Ltd").due_date == D                                                                  # 0 days: due immediately
    assert sinv(due_date=D + timedelta(days=5)).due_date == D + timedelta(days=5)


def test_vat_rounds_per_line_to_the_kobo(inv):
    i = sinv([(Dc("33.33"), VAT_O)])
    assert (i.items[0].amount, i.items[0].tax_amount) == (Dc("33.33"), Dc("2.50"))                                  # 2.49975 -> 2.50
    j = new_doc("Sales Invoice", customer="Bola Stores", posting_date=D)
    j.append("items", {"description": "x", "quantity": 3, "rate": Dc("0.335"), "tax_code": VAT_O})
    assert j.insert().items[0].amount == Dc("1.01")


def test_purchase_invoice_posts_expense_input_vat_and_payable(inv):
    p = pinv([(50000, VAT_I)])
    assert (p.grand_total, p.status, p.due_date) == (Dc("53750.00"), "Unpaid", D + timedelta(days=14))
    assert bal("Office Expenses") == 50000 and bal("VAT Input") == 3750 and bal("Trade Payables", party="Acme Supplies") == -53750


def test_duplicate_supplier_invoice_numbers_are_refused(inv):
    pinv(supplier_invoice_no="INV-0042")
    bad(lambda: pinv(supplier_invoice_no="INV-0042"), r"INV-0042 from Acme Supplies is already recorded as PINV-")
    pinv(supplier_invoice_no="INV-0042", supplier="Zenith Foods")                                                     # another supplier may reuse it
    first = [x for x in get_list("Purchase Invoice", fields=["name"], filters=[["supplier", "=", "Acme Supplies"]])][0]["name"]
    get_doc("Purchase Invoice", first).cancel()
    pinv(supplier_invoice_no="INV-0042")                                                                              # a cancelled one frees the number


def test_invoice_validation(inv):
    new_doc("Customer", customer_name="Blocked Co", status="Blocked").insert()
    bad(lambda: sinv(customer="Blocked Co"), "is blocked")
    bad(lambda: sinv(customer="Nobody"), "does not exist|Nobody", Exception)
    bad(lambda: new_doc("Sales Invoice", customer="Bola Stores", posting_date=D).insert(), "Add at least one item|required|mandatory", Exception)
    bad(lambda: sinv([(0, None)]), "rate must be greater than zero")
    bad(lambda: sinv([(100, VAT_I)]), "VAT Input code; this invoice needs VAT Output")
    bad(lambda: sinv([(100, "Nope")]), "Nope", Exception)
    bad(lambda: sinv(due_date=D - timedelta(days=1)), "due date cannot be before")
    for acc in ("Main Bank Account", "Trade Receivables", "VAT Output", "Rent"):
        d = new_doc("Sales Invoice", customer="Bola Stores", posting_date=D)
        d.append("items", {"description": "x", "quantity": 1, "rate": 10, "account": acc})
        bad(d.insert, "not a valid income account")
    for acc in ("Sales Revenue", "Trade Payables", "Main Bank Account"):
        d = new_doc("Purchase Invoice", supplier="Acme Supplies", posting_date=D)
        d.append("items", {"description": "x", "quantity": 1, "rate": 10, "account": acc})
        bad(d.insert, "not a valid expense / asset account")


def test_a_submitted_invoice_cannot_be_edited_and_cancelling_mirrors_the_ledger(inv):
    i = sinv()
    i.remarks = "changed"
    bad(i.save, "cannot be edited", DocStatusError)
    fresh("Sales Invoice", i.name).cancel()
    assert bal("Trade Receivables") == 0 and bal("Sales Revenue") == 0 and bal("VAT Output") == 0
    f = fresh("Sales Invoice", i.name)
    assert (f.status, f.outstanding, f.docstatus) == ("Cancelled", 0, 2)


# ============================== settling invoices with receipts ==============================
def test_a_receipt_settles_an_invoice_fully(inv):
    i = sinv()
    r = receipt(rows=[(i.name, 107500)])
    f = fresh("Sales Invoice", i.name)
    assert (f.outstanding, f.status) == (0, "Paid") and (r.allocated_total, r.on_account, r.discount_total) == (Dc("107500"), 0, 0)
    assert r.invoices[0].outstanding == Dc("107500") and r.invoices[0].due_date == i.due_date                         # snapshot taken at validation
    assert bal("Trade Receivables", party="Bola Stores") == 0 and bal(BANK) == 107500


def test_partial_payments_walk_the_invoice_through_its_statuses(inv):
    i = sinv()
    receipt(amount=40000, rows=[(i.name, 40000)])
    f = fresh("Sales Invoice", i.name)
    assert (f.outstanding, f.status) == (Dc("67500"), "Partly Paid")
    receipt(amount=67500, rows=[(i.name, 67500)])
    assert fresh("Sales Invoice", i.name).status == "Paid"


def test_one_receipt_can_settle_several_invoices_and_the_rest_stays_on_account(inv):
    a, b = sinv(), sinv([(50000, None)])
    r = receipt(amount=200000, rows=[(a.name, 107500), (b.name, 50000)])
    assert (r.allocated_total, r.on_account) == (Dc("157500"), Dc("42500"))
    assert fresh("Sales Invoice", a.name).status == "Paid" and fresh("Sales Invoice", b.name).status == "Paid"
    assert bal("Trade Receivables", party="Bola Stores") == -42500                                                      # a credit balance: they have paid in advance
    c2 = receipt(amount=10000)                                                                                          # no rows at all: all on account, as before
    assert c2.on_account == 10000 and bal("Trade Receivables", party="Bola Stores") == -52500


def test_wht_suffered_still_settles_the_gross_invoice(inv):
    i = sinv([(100000, None)])
    r = receipt(amount=100000, wht_rate=5, rows=[(i.name, 100000)])
    assert bal(BANK) == 95000 and bal("WHT Receivable") == 5000 and fresh("Sales Invoice", i.name).status == "Paid"


def test_settlement_discount_is_written_off_and_balances(inv):
    i = sinv([(100000, None)])
    r = receipt(amount=95000, rows=[(i.name, 95000, 5000)])
    f = fresh("Sales Invoice", i.name)
    assert (f.outstanding, f.status, r.discount_total) == (0, "Paid", Dc("5000")) and bal("Discount Allowed") == 5000
    assert bal("Trade Receivables", party="Bola Stores") == 0 and bal(BANK) == 95000
    assert sum(x["debit"] - x["credit"] for x in get_list("GL Entry", fields=["debit", "credit"], limit=1000)) == 0


def test_receipt_allocation_rules(inv):
    i, other = sinv(), sinv(customer="Cato Ltd")
    draft = sinv(submit=False)
    cases = [
        (lambda: receipt(rows=[(draft.name, 1000)], amount=1000, submit=False), "is not a submitted invoice"),
        (lambda: receipt(rows=[(other.name, 1000)], amount=1000, submit=False), "belongs to Cato Ltd, not Bola Stores"),
        (lambda: receipt(rows=[(i.name, 200000)], amount=300000, submit=False), "has only 107,500.00 outstanding"),
        (lambda: receipt(rows=[(i.name, 500), (i.name, 500)], amount=1000, submit=False), "appears twice"),
        (lambda: receipt(rows=[(i.name, 0)], amount=1000, submit=False), "enter the amount to settle"),
        (lambda: receipt(rows=[(i.name, -5)], amount=1000, submit=False), "cannot be negative"),
        (lambda: receipt(rows=[(i.name, 5000)], amount=1000, submit=False), "settle 5,000.00 but the amount is only 1,000.00"),
        (lambda: receipt(rows=[("SINV-99999", 5)], amount=100, submit=False), "SINV-99999|not a submitted"),
    ]
    for fn, frag in cases:
        bad(fn, frag, Exception)
    r = new_doc("Receipt", receipt_type="Other", posting_date=D, bank_account=BANK)
    r.append("lines", {"account": "Other Income", "amount": 10})
    r.append("invoices", {"invoice": i.name, "allocated": 10})
    bad(r.insert, "only be settled by a Customer receipt")
    r2 = new_doc("Receipt", receipt_type="Customer", posting_date=D, bank_account=BANK, party="Bola Stores", amount=10)
    r2.append("invoices", {"invoice": i.name, "allocated": 10, "discount": 1000000})
    bad(r2.insert, "has only 107,500.00 outstanding")


def test_cancelling_a_receipt_gives_the_invoice_back(inv):
    i = sinv()
    r = receipt(rows=[(i.name, 107500)])
    bad(lambda: fresh("Sales Invoice", i.name).cancel(), r"(\(part-\)settled: cancel the receipts/payments that settled it first|it is used by submitted Receipt)")
    fresh("Receipt", r.name).cancel()
    f = fresh("Sales Invoice", i.name)
    assert (f.outstanding, f.status) == (Dc("107500"), "Unpaid") and bal(BANK) == 0
    fresh("Sales Invoice", i.name).cancel()                                                                               # now it can go


def test_two_receipts_cannot_settle_more_than_is_owed(inv):
    """Both validate while 100,000 is outstanding; the SECOND one's submit must be refused by the row lock/recheck and leave nothing behind."""
    i = sinv([(100000, None)])
    first, second = receipt(amount=100000, rows=[(i.name, 100000)], submit=False), receipt(amount=100000, rows=[(i.name, 100000)], submit=False)
    first.submit()
    bad(second.submit, "has only 0.00 outstanding")
    assert fresh("Receipt", second.name).docstatus == 0 and len(ledger.voucher_rows("Receipt", second.name)) == 0
    assert fresh("Sales Invoice", i.name).outstanding == 0 and bal(BANK) == 100000                                         # the first stands, the second changed nothing


def test_the_locked_recheck_catches_a_race_the_validation_cannot_see(inv, monkeypatch):
    """In a real race the second receipt's validation reads a stale outstanding. Blind the validation and prove the row-locked settle() still refuses."""
    from velora_accounts import settlement
    i = sinv([(100000, None)])
    first, second = receipt(amount=100000, rows=[(i.name, 100000)], submit=False), receipt(amount=100000, rows=[(i.name, 100000)], submit=False)
    first.submit()
    monkeypatch.setattr(settlement, "prepare", lambda doc, *a, **k: (sum((c.D(r.allocated) for r in doc.invoices), Dc(0)), sum((c.D(r.discount) for r in doc.invoices), Dc(0))))
    bad(second.submit, r"has only 0.00 outstanding, so 100,000.00 cannot be settled against it")
    assert len(ledger.voucher_rows("Receipt", second.name)) == 0 and fresh("Sales Invoice", i.name).outstanding == 0 and bal(BANK) == 100000


def test_settle_and_unsettle_enforce_their_limits_directly(inv):
    from velora_accounts import invoices
    i = sinv([(100000, None)])
    bad(lambda: invoices.settle("Sales Invoice", i.name, Dc("100000.01")), "cannot be settled against it")
    assert invoices.settle("Sales Invoice", i.name, Dc("100000")) == 0 and fresh("Sales Invoice", i.name).status == "Paid"
    bad(lambda: invoices.settle("Sales Invoice", i.name, Dc("0.01")), "has only 0.00 outstanding")
    assert invoices.unsettle("Sales Invoice", i.name, Dc("100000")) == Dc("100000") and fresh("Sales Invoice", i.name).status == "Unpaid"
    bad(lambda: invoices.unsettle("Sales Invoice", i.name, Dc("0.01")), "would exceed its total")
    draft = sinv([(10, None)], submit=False)
    bad(lambda: invoices.settle("Sales Invoice", draft.name, Dc("1")), "is not a submitted invoice")


def test_a_cancelled_receipt_of_a_cancelled_invoice_chain_is_consistent(inv):
    i = sinv()
    r = receipt(amount=50000, rows=[(i.name, 50000)])
    fresh("Receipt", r.name).cancel()
    again = receipt(amount=107500, rows=[(i.name, 107500)])
    assert fresh("Sales Invoice", i.name).status == "Paid" and again.docstatus == 1


# ============================== paying suppliers ==============================
def test_a_payment_settles_purchase_invoices_with_wht_and_discount(inv):
    p = pinv([(100000, None)])
    pay = payment(amount=95000, wht_rate=5, rows=[(p.name, 90000, 5000)])
    f = fresh("Purchase Invoice", p.name)
    assert (f.outstanding, f.status) == (Dc("5000"), "Partly Paid") and (pay.allocated_total, pay.discount_total, pay.on_account) == (Dc("90000"), Dc("5000"), Dc("5000"))
    assert bal(BANK) == -90250 and bal("WHT Payable") == -4750 and bal("Discount Received") == -5000
    assert bal("Trade Payables", party="Acme Supplies") == 0                                                       # 100,000 invoiced, 95,000 + 5,000 discount applied; the unspent 5,000 sits on account
    assert sum(x["debit"] - x["credit"] for x in get_list("GL Entry", fields=["debit", "credit"], limit=1000)) == 0
    fresh("Payment", pay.name).cancel()
    f = fresh("Purchase Invoice", p.name)
    assert (f.outstanding, f.status) == (Dc("100000"), "Unpaid") and bal(BANK) == 0 and bal("Discount Received") == 0


def test_payment_allocation_rules(inv):
    p, other = pinv(), pinv(supplier="Zenith Foods")
    bad(lambda: payment(rows=[(other.name, 100)], amount=100, submit=False), "belongs to Zenith Foods")
    bad(lambda: payment(rows=[(p.name, 99999999)], amount=99999999, submit=False), "has only 53,750.00 outstanding")
    pay = new_doc("Payment", payment_type="Other", posting_date=D, bank_account=BANK)
    pay.append("lines", {"account": "Rent", "amount": 10})
    pay.append("invoices", {"invoice": p.name, "allocated": 10})
    bad(pay.insert, "only be settled by a Vendor payment")
    a, b = payment(amount=53750, rows=[(p.name, 53750)], submit=False), payment(amount=53750, rows=[(p.name, 53750)], submit=False)
    a.submit()
    bad(b.submit, "has only 0.00 outstanding")


# ============================== strict parties ==============================
def test_unknown_customers_and_suppliers_are_refused_everywhere_in_strict_mode(inv):
    bad(lambda: receipt(customer="Typo Stores", amount=10, submit=False), r"Customer 'Typo Stores' does not exist")
    bad(lambda: payment(supplier="Typo Supplies", amount=10, submit=False), r"Supplier 'Typo Supplies' does not exist")
    j = new_doc("General Journal", journal_type="General", posting_date=D)
    j.append("lines", {"account": "Trade Receivables", "debit": 5, "party_type": "Customer", "party": "Typo Stores"})
    j.append("lines", {"account": "Sales Revenue", "credit": 5})
    bad(j.insert, r"Customer 'Typo Stores' does not exist")
    from test_batches import BBT, make  # the batch pre-flight reports it per row
    bad(lambda: make(BBT, [{"inflow": 10, "party_type": "Customer", "party": "Typo Stores"}]).insert(), r"Row 1: Customer 'Typo Stores' does not exist")
    j2 = new_doc("General Journal", journal_type="General", posting_date=D)                                                # Employee has no master: not checked
    j2.append("lines", {"account": "Trade Payables", "credit": 5, "party_type": "Employee", "party": "EMP-1"})
    j2.append("lines", {"account": "Rent", "debit": 5})
    j2.insert()


def test_strict_mode_is_a_manager_setting_and_can_be_relaxed_for_imports(inv):
    with session_as(VIEWER):
        bad(lambda: c.set_strict_parties(False), "Only an Accounts Manager", Exception)
    with session_as(MANAGER):
        c.set_strict_parties(False)
    assert receipt(customer="Free Text Ltd", amount=10).docstatus == 1                                                      # legacy/import mode
    c.set_strict_parties(True)
    bad(lambda: receipt(customer="Free Text Ltd", amount=10, submit=False), "does not exist")


# ============================== reports ==============================
def values(res):
    return [r.values for r in res.rows]


def test_general_ledger_statement_with_running_balance(inv):
    i = sinv([(100000, None)], d=date(2026, 1, 10))
    receipt(amount=30000, rows=[(i.name, 30000)], d=date(2026, 2, 5))
    receipt(amount=20000, rows=[(i.name, 20000)], d=date(2026, 3, 5))
    res = run_report("General Ledger", {"account": "Trade Receivables", "party": "Bola Stores", "from_date": "2026-02-01", "to_date": "2026-03-31"})
    rows = values(res)
    assert rows[0]["remarks"] == "Opening balance" and rows[0]["balance"] == 100000
    assert [r["balance"] for r in rows[1:3]] == [70000, 50000] and rows[1]["credit"] == 30000 and rows[1]["voucher"].startswith("Receipt RCT-")
    assert rows[-1]["remarks"] == "Totals / closing balance" and rows[-1]["balance"] == 50000 and rows[-1]["credit"] == 50000
    by_party = run_report("General Ledger", {"party": "Bola Stores", "from_date": "2026-01-01", "to_date": "2026-12-31"})
    assert values(by_party)[-1]["balance"] == 50000                                                                         # a customer statement needs no account
    first = get_list("Receipt", filters=[["total", "=", 30000]], fields=["name"])[0]["name"]
    fresh("Receipt", first).cancel()
    again = values(run_report("General Ledger", {"account": "Trade Receivables", "party": "Bola Stores", "from_date": "2026-01-01", "to_date": "2026-12-31"}))
    assert not any("Receipt" in (r.get("voucher") or "") and r["credit"] == 30000 for r in again) and again[-1]["balance"] == 80000      # the cancelled receipt leaves the statement; the 30,000 is owed again
    full = values(run_report("General Ledger", {"account": "Trade Receivables", "party": "Bola Stores", "from_date": "2026-01-01", "to_date": "2026-12-31", "show_cancelled": "1"}))
    assert sum("(cancelled)" in (r.get("voucher") or "") for r in full) == 2 and full[-1]["balance"] == 80000                       # "show cancelled entries": still on record, and the balance is the same
    bad(lambda: run_report("General Ledger", {}), "Choose an account and/or a customer/supplier", Exception)


def test_aged_receivables_buckets_by_days_overdue(inv):
    today = date(2026, 6, 30)
    for days, amount in ((-5, 100), (10, 200), (45, 300), (75, 400), (120, 500)):                                         # due dates 5 days ahead ... 120 days ago
        sinv([(amount, None)], customer="Cato Ltd", d=today - timedelta(days=days + 1), due_date=today - timedelta(days=days))
    paid = sinv([(999, None)], customer="Cato Ltd", d=D)
    receipt(customer="Cato Ltd", amount=999, rows=[(paid.name, 999)])                                                      # fully paid: not listed
    res = run_report("Aged Receivables", {"as_of": today.isoformat()})
    v = values(res)
    assert [r.values["party"] for r in res.rows if r.type == "data"] == ["Cato Ltd"]
    row = next(x for x in v if x.get("party") == "Cato Ltd")
    assert (row["not_due"], row["d30"], row["d60"], row["d90"], row["d91"], row["total"]) == (100, 200, 300, 400, 500, 1500)
    assert v[-1]["total"] == 1500


def test_aged_payables(inv):
    pinv([(1000, None)], d=date(2026, 1, 1), due_date=date(2026, 1, 31))
    res = values(run_report("Aged Payables", {"as_of": "2026-06-30"}))
    assert next(x for x in res if x.get("party") == "Acme Supplies")["d91"] == 1000


def test_reports_respect_permissions(inv):
    from velora.permissions import Session
    with session_as(VIEWER):
        assert run_report("Aged Receivables", {}).rows is not None
    with session_as(Session("sam", frozenset({"Sales User"}))):
        bad(lambda: run_report("General Ledger", {"account": "Rent"}), "may not run the report", PermissionDenied)


# ============================== the upgrade patch ==============================
def test_the_patch_adds_what_an_older_company_lacks_and_never_overrides(inv):
    from velora_accounts.patches.v0_3 import add_invoicing_defaults
    from velora.settings import get_setting, set_setting
    for t in get_list("Tax Code", fields=["name"]):
        get_doc("Tax Code", t["name"]).delete()
    old = {k: v for k, v in get_setting("accounts.defaults").items() if k not in ("discount_allowed", "discount_received", "sales_income", "prepayments")}
    old["gateway_fees"] = "Bank Charges"                                                                                    # a deliberate choice that must survive
    set_setting("accounts.defaults", old)                                                                                   # (an account that is still a default cannot be deleted)
    for name in ("Discount Allowed", "Discount Received"):
        get_doc("Account", name).delete()
    add_invoicing_defaults.execute()
    d = get_setting("accounts.defaults")
    assert d["discount_allowed"] == "Discount Allowed" and d["sales_income"] == "Sales Revenue" and d["prepayments"] == "Prepayments" and d["gateway_fees"] == "Bank Charges"
    assert len(get_list("Tax Code", fields=["name"])) == 4 and {a["name"] for a in get_list("Account", fields=["name"]) if "Discount" in a["name"]} == {"Discount Allowed", "Discount Received"}
    assert seed.ensure_invoicing_setup() == {"accounts": [], "defaults": [], "tax_codes": [], "parties": [], "skipped_parties": []}      # idempotent
    from velora.upgrade import patches
    assert "velora_accounts.patches.v0_3.add_invoicing_defaults" in patches.discover("velora_accounts")["post_model_sync"]


def test_the_patch_gives_existing_free_text_parties_a_master_so_nobody_is_locked_out(inv):
    from velora_accounts.patches.v0_3 import add_invoicing_defaults
    c.set_strict_parties(False)                                                                                         # the company before the master existed
    receipt(customer="Legacy Ltd", amount=500)
    payment(supplier="Old Supplier", amount=300)
    j = new_doc("General Journal", journal_type="General", posting_date=D)
    j.append("lines", {"account": "Trade Receivables", "debit": 5, "party_type": "Customer", "party": " Padded "})
    j.append("lines", {"account": "Sales Revenue", "credit": 5})
    j.insert().submit()
    c.set_strict_parties(True)
    bad(lambda: receipt(customer="Legacy Ltd", amount=10, submit=False), "does not exist")                              # strict mode would lock them out ...
    out = seed.ensure_invoicing_setup()
    assert sorted(out["parties"]) == ["Customer: Legacy Ltd", "Supplier: Old Supplier"] and out["skipped_parties"] == [" Padded "]
    assert receipt(customer="Legacy Ltd", amount=10).docstatus == 1 and payment(supplier="Old Supplier", amount=10).docstatus == 1      # ... and now it does not
    assert bal("Trade Receivables", party="Legacy Ltd") == -510                                                          # their old balance is intact
    add_invoicing_defaults.execute()                                                                                    # idempotent


# ============================== the invariant that matters ==============================
def test_random_invoices_receipts_and_payments_keep_every_balance_honest(inv):
    rng = random.Random(11)
    customers, suppliers = ["Bola Stores", "Cato Ltd"], ["Acme Supplies", "Zenith Foods"]
    sales, purchases, receipts, payments = [], [], [], []
    for _ in range(40):
        action = rng.choice(["s", "p", "r", "y", "x", "x"])
        try:
            if action == "s":
                sales.append(sinv([(Dc(rng.randint(100, 500000)) / 100, rng.choice([VAT_O, None]))], customer=rng.choice(customers)))
            elif action == "p":
                purchases.append(pinv([(Dc(rng.randint(100, 500000)) / 100, rng.choice([VAT_I, None]))], supplier=rng.choice(suppliers)))
            elif action in "ry":
                pool, doc_fn, store, ptype = (sales, receipt, receipts, "customer") if action == "r" else (purchases, payment, payments, "supplier")
                live = [x for x in pool if fresh(x.doctype, x.name).docstatus == 1 and fresh(x.doctype, x.name).outstanding > 0]
                if not live:
                    continue
                target = rng.choice(live)
                f = fresh(target.doctype, target.name)
                settle = Dc(rng.randint(1, int(f.outstanding * 100))) / 100
                disc = min(Dc(rng.randint(0, 200)) / 100, f.outstanding - settle) if rng.random() < 0.3 else Dc(0)
                extra = Dc(rng.randint(0, 5000)) / 100
                who = target.customer if action == "r" else target.supplier
                kw = {"customer": who} if action == "r" else {"supplier": who}
                store.append(doc_fn(amount=settle + extra, rows=[(target.name, settle, disc)], **kw))
            else:
                pool = receipts + payments
                if pool:
                    d = rng.choice(pool)
                    if fresh(d.doctype, d.name).docstatus == 1:
                        fresh(d.doctype, d.name).cancel()
        except ValidationError:
            continue
    assert sum(x["debit"] - x["credit"] for x in get_list("GL Entry", fields=["debit", "credit"], limit=100000)) == 0
    for dt, vs, party_field, control, sign in (("Sales Invoice", receipts, "customer", "Trade Receivables", 1), ("Purchase Invoice", payments, "supplier", "Trade Payables", -1)):
        invs = [fresh(dt, x["name"]) for x in get_list(dt, filters=[["docstatus", "=", 1]], fields=["name"], limit=1000)]
        for party in {getattr(i, party_field) for i in invs} | {v.party for v in vs}:
            outstanding = sum((i.outstanding for i in invs if getattr(i, party_field) == party), Dc(0))
            on_account = sum((fresh(v.doctype, v.name).on_account for v in vs if v.party == party and fresh(v.doctype, v.name).docstatus == 1), Dc(0))
            assert sign * bal(control, party=party) == outstanding - on_account, (dt, party)                                 # ledger == invoices - credits on account
        for i in invs:
            settled = sum((c.D(r.allocated) + c.D(r.discount) for v in vs if fresh(v.doctype, v.name).docstatus == 1 for r in v.invoices if r.invoice == i.name), Dc(0))
            assert i.outstanding == i.grand_total - settled and 0 <= i.outstanding <= i.grand_total


def test_genuinely_simultaneous_receipts_cannot_over_settle_an_invoice(inv):
    """PostgreSQL only (SQLite serialises writers): 8 threads each try to settle the SAME 100,000 invoice with 60,000. Exactly one can succeed."""
    import threading
    from velora.db import get_engine
    if get_engine().dialect.name != "postgresql":
        pytest.skip("SQLite serialises writers; concurrency is verified on PostgreSQL")
    i = sinv([(100000, None)])
    drafts = [receipt(amount=60000, rows=[(i.name, 60000)], submit=False).name for _ in range(8)]
    ok, refused, other = [], [], []

    def work(name):
        try:
            fresh("Receipt", name).submit()
            ok.append(name)
        except ValidationError as e:
            refused.append(str(e))
        except Exception as e:  # noqa: BLE001
            other.append(repr(e))
    threads = [threading.Thread(target=work, args=(n,)) for n in drafts]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not other, other
    assert len(ok) == 1 and len(refused) == 7 and all("outstanding" in m for m in refused)
    f = fresh("Sales Invoice", i.name)
    assert f.outstanding == Dc("40000") and f.status == "Partly Paid" and bal(BANK) == 60000
    assert len(get_list("GL Entry", filters=[["voucher_type", "=", "Receipt"]], fields=["name"], limit=100)) == 2          # exactly ONE receipt posted (2 legs)


def test_a_wrong_receipt_is_cancelled_and_amended_and_the_invoice_settles_correctly(inv):
    from velora.document import amend
    i = sinv([(100000, None)], d=date(2026, 1, 10))
    r = receipt(amount=30000, rows=[(i.name, 30000)], d=date(2026, 2, 5))                         # keyed in as 30,000: it should have been 40,000
    assert fresh("Sales Invoice", i.name).outstanding == 70000
    fresh("Receipt", r.name).cancel()
    assert fresh("Sales Invoice", i.name).outstanding == 100000                                       # cancelling puts the invoice back to unpaid
    p = amend.copy_values("Receipt", r.name, "amend")
    assert p["suggested_name"] == f"{r.name}-1" and p["values"]["amended_from"] == r.name
    v = p["values"]
    assert [(x["invoice"], x["allocated"]) for x in v["invoices"]] == [(i.name, 30000)]               # the allocation is copied, ready to change
    v["amount"] = 40000                                                                               # the correction (the totals recompute themselves)
    v["invoices"][0]["allocated"] = 40000
    new = new_doc("Receipt", **v).insert().submit()
    assert new.name == f"{r.name}-1" and fresh("Sales Invoice", i.name).outstanding == 60000          # settled by the amendment only
    live = [x["voucher"] for x in values(run_report("General Ledger", {"account": "Trade Receivables", "party": "Bola Stores", "from_date": "2026-01-01", "to_date": "2026-12-31"})) if x.get("voucher")]
    assert f"Receipt {new.name}" in live and not any(f"Receipt {r.name}" == x for x in live)           # the statement shows the amended receipt, not the cancelled one
    with pytest.raises(Exception, match="already been amended"):
        amend.copy_values("Receipt", r.name, "amend")
