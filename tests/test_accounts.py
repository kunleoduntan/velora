import os
import random
from datetime import date
from decimal import Decimal as Dc

import pytest
from sqlalchemy import func, select

import velora
from velora import db, get_doc, get_list, new_doc
from velora.db.tables import get_table
from velora.exceptions import DocStatusError, PermissionDenied, ValidationError
from velora.permissions import Session, session_as

from velora_accounts import common as c, ledger, seed


def _urls():
    urls = [("sqlite", None)]
    if os.environ.get("VELORA_TEST_PG_URL"):
        urls.append(("postgres", os.environ["VELORA_TEST_PG_URL"]))
    return urls


@pytest.fixture(params=[u[0] for u in _urls()])
def books(request, tmp_path):
    url = f"sqlite:///{tmp_path / 'books.db'}" if request.param == "sqlite" else os.environ["VELORA_TEST_PG_URL"]
    cfg = velora.configure(db_url=url, apps=["velora_accounts"], developer_mode=True)
    velora.init(cfg)
    with db.transaction() as conn:
        from sqlalchemy import MetaData
        md = MetaData()
        md.reflect(conn)
        md.drop_all(conn)
    velora.migrate()
    seed.seed_chart()
    c.set_strict_parties(False)                      # these tests predate the Customer/Supplier master and use free-text parties
    seed.ensure_fiscal_year(2026)
    seed.ensure_fiscal_year(2025)
    yield cfg
    velora.shutdown()


ACCOUNTANT = Session("ann", frozenset({"Accountant"}))
MANAGER = Session("mo", frozenset({"Accounts Manager"}))
VIEWER = Session("vi", frozenset({"Accounts User"}))
SALES = Session("sam", frozenset({"Sales User"}))
D26 = date(2026, 3, 10)


def line(account, debit=0, credit=0, **kw):
    return {"account": account, "debit": debit, "credit": credit, **kw}


def journal(lines, jtype="General", d=D26, submit=True, **kw):
    gj = new_doc("General Journal", journal_type=jtype, posting_date=d, **kw)
    for ln in lines:
        gj.append("lines", ln)
    gj.insert()
    return gj.submit() if submit else gj


def bal(account, **kw):
    return ledger.balance(account, **kw)


def gl_count(**flt):
    t = get_table("GL Entry")
    with db.transaction() as conn:
        q = select(func.count()).select_from(t)
        for k, v in flt.items():
            q = q.where(t.c[k] == v)
        return conn.execute(q).scalar()


def total_dr_cr():
    t = get_table("GL Entry")
    with db.transaction() as conn:
        d, cr = conn.execute(select(func.coalesce(func.sum(t.c.debit), 0), func.coalesce(func.sum(t.c.credit), 0))).one()
    return Dc(str(d)), Dc(str(cr))


def bad(fn, frag, exc=ValidationError):
    with pytest.raises(exc, match=frag):
        fn()


# ================================ chart of accounts ================================
def test_seed_creates_a_usable_chart_with_defaults_and_is_idempotent(books):
    assert seed.seed_chart() == 0
    accts = {a["name"]: a for a in get_list("Account", fields=["name", "root_type", "account_type", "is_group", "parent_account"], limit=500)}
    assert accts["Cash in Hand"]["root_type"] == "Asset" and accts["Trade Payables"]["root_type"] == "Liability" and accts["Sales Revenue"]["root_type"] == "Income"
    assert accts["Trade Receivables"]["account_type"] == "Receivable" and accts["Assets"]["is_group"]
    assert c.get_default("receivable") == "Trade Receivables" and c.get_default("wht_payable") == "WHT Payable"
    assert seed.ensure_fiscal_year(2026) == "FY2026"


def test_account_tree_rules(books):
    mk = lambda **kw: new_doc("Account", **kw).insert()
    bad(lambda: mk(account_name="Orphan"), "needs a root type")
    bad(lambda: mk(account_name="Petty", parent_account="Cash in Hand"), "not a group account")
    bad(lambda: mk(account_name="Gone", parent_account="Nope"), "does not exist")
    bad(lambda: mk(account_name="X", parent_account="Current Assets", root_type="Income"), "must match the parent")
    assert mk(account_name="Petty Cash", parent_account="Current Assets", account_type="Cash").root_type == "Asset"        # inherited
    bad(lambda: mk(account_name="Bad Bank", parent_account="Current Liabilities", account_type="Bank"), "must sit under Assets")
    bad(lambda: mk(account_name="Grp", parent_account="Current Assets", is_group=1, account_type="Bank"), "cannot have an account type")
    mk(account_name="A1", parent_account="Current Assets", account_number="1001")
    bad(lambda: mk(account_name="A2", parent_account="Current Assets", account_number="1001"), "already used by A1")
    g = get_doc("Account", "Current Assets")
    g.parent_account = "Current Assets"
    bad(g.save, "own parent")
    top = get_doc("Account", "Assets")
    top.parent_account = "Current Assets"                       # a root under its own child would be a loop
    bad(top.save, "loop|must match the parent")


def test_accounts_with_entries_are_frozen_and_protected(books):
    journal([line("Rent", 100), line("Accrued Expenses", credit=100)])
    a = get_doc("Account", "Rent")
    a.account_type = "Cost of Sales"
    bad(a.save, "already has ledger entries")
    bad(lambda: get_doc("Account", "Rent").delete(), "has ledger entries")
    bad(lambda: get_doc("Account", "Current Assets").delete(), "sub-accounts|referenced|linked|in use|Cannot delete")
    unused = new_doc("Account", account_name="Spare", parent_account="Operating Expenses").insert()
    unused.delete()                                                                                                         # an unused leaf can go
    bad(lambda: get_doc("Account", "Trade Receivables").delete(), "default account")


def test_fiscal_year_rules(books):
    mk = lambda n, s, e: new_doc("Fiscal Year", year_name=n, start_date=s, end_date=e).insert()
    bad(lambda: mk("Dup", date(2026, 6, 1), date(2026, 12, 31)), "overlap fiscal year FY2026")
    bad(lambda: mk("Back", date(2027, 5, 1), date(2027, 1, 1)), "must end after it starts")
    bad(lambda: mk("Long", date(2027, 1, 1), date(2028, 6, 1)), "longer than 12 months")
    mk("FY2027", date(2027, 1, 1), date(2027, 12, 31))
    with session_as(MANAGER):
        f = get_doc("Fiscal Year", "FY2027"); f.is_closed = 1; f.save()
    bad(lambda: journal([line("Rent", 5), line("Accrued Expenses", credit=5)], d=date(2027, 2, 1)), "FY2027 is closed")
    bad(lambda: journal([line("Rent", 5), line("Accrued Expenses", credit=5)], d=date(2031, 2, 1)), "No fiscal year covers")
    bad(lambda: get_doc("Fiscal Year", "FY2027").delete(), "cannot be deleted")
    journal([line("Rent", 5), line("Accrued Expenses", credit=5)], d=date(2026, 12, 31))
    f = get_doc("Fiscal Year", "FY2026"); f.start_date = date(2026, 1, 2)
    bad(f.save, "already has ledger entries")


def test_only_a_manager_can_close_a_year(books):
    new_doc("Fiscal Year", year_name="FY2027", start_date=date(2027, 1, 1), end_date=date(2027, 12, 31)).insert()
    with session_as(ACCOUNTANT):
        f = get_doc("Fiscal Year", "FY2027"); f.is_closed = 1
        bad(f.save, "Only an Accounts Manager can close")


# ================================ the ledger ================================
def test_a_journal_posts_exact_balanced_entries_and_updates_balances(books):
    gj = journal([line("Rent", "1500.50"), line("Utilities", "499.50"), line("Accrued Expenses", credit="2000.00")], remarks="Q1 accrual")
    rows = ledger.voucher_rows("General Journal", gj.name)
    assert len(rows) == 3 and sum(Dc(str(r["debit"])) for r in rows) == sum(Dc(str(r["credit"])) for r in rows) == Dc("2000.00")
    assert all(r["fiscal_year"] == "FY2026" and r["posting_date"] == D26 for r in rows)
    assert bal("Rent") == Dc("1500.50") and bal("Accrued Expenses") == Dc("-2000.00") and ledger.is_posted("General Journal", gj.name)
    assert rows[0]["against"] == "Accrued Expenses"


@pytest.mark.parametrize("lines,frag", [
    ([line("Rent", 100), line("Utilities", credit=99)], r"must be equal; the difference is 1"),
    ([line("Rent", 100, 100), line("Utilities", credit=0)], "not both"),
    ([line("Rent", 0, 0), line("Utilities", credit=0)], "debit or a credit amount"),
    ([line("Rent", -5), line("Utilities", credit=-5)], "cannot be negative"),
    ([line("Rent", "10.005"), line("Utilities", credit="10.005")], "more than 2 decimal places"),
    ([line("Rent", 100)], "at least two lines"),
    ([line("Operating Expenses", 100), line("Utilities", credit=100)], "group account"),
    ([line("Ghost", 100), line("Utilities", credit=100)], "does not exist"),
])
def test_double_entry_rules(books, lines, frag):
    bad(lambda: journal(lines), frag)
    assert gl_count() == 0                                                                    # nothing reached the ledger


def test_money_is_exact_never_binary_float(books):
    journal([line("Rent", "0.10"), line("Utilities", "0.20"), line("Accrued Expenses", credit="0.30")])
    assert bal("Rent") + bal("Utilities") == Dc("0.30") and total_dr_cr() == (Dc("0.30"), Dc("0.30"))
    journal([line("Rent", 0.1), line("Utilities", 0.2), line("Accrued Expenses", credit=0.3)])      # floats from JSON clients behave too
    assert total_dr_cr()[0] == total_dr_cr()[1] == Dc("0.60")


def test_disabled_accounts_cannot_be_posted(books):
    a = get_doc("Account", "Rent"); a.disabled = 1; a.save()
    bad(lambda: journal([line("Rent", 10), line("Utilities", credit=10)]), "Rent is disabled")


def test_party_rules(books):
    ar = "Trade Receivables"
    bad(lambda: journal([line(ar, 100), line("Sales Revenue", credit=100)]), "a Customer is required")
    bad(lambda: journal([line(ar, 100, party_type="Supplier", party="X"), line("Sales Revenue", credit=100)]), "must be Customer")
    bad(lambda: journal([line("Rent", 100, party_type="Customer", party="X"), line("Sales Revenue", credit=100)]), "cannot carry a party")
    journal([line(ar, 100, party_type="Customer", party="ACME"), line("Sales Revenue", credit=100)])
    journal([line(ar, 40, party_type="Customer", party="BETA"), line("Sales Revenue", credit=40)])
    assert bal(ar, party="ACME") == 100 and bal(ar, party="BETA") == 40 and bal(ar) == 140
    bad(lambda: journal([line("Trade Payables", credit=5), line("Rent", 5)]), "Supplier / Employee is required")


def test_cash_and_bank_are_off_limits_to_ordinary_journals(books):
    bad(lambda: journal([line("Main Bank Account", 100), line("Sales Revenue", credit=100)]), "Receipt or Payment")
    for t in ("Adjusting", "Accrual", "Depreciation"):
        bad(lambda t=t: journal([line("Cash in Hand", credit=100), line("Rent", 100)], jtype=t), "bank/cash account")
    journal([line("Main Bank Account", 500), line("Share Capital", credit=500)], jtype="Opening Balance")        # the books must be able to START with cash
    journal([line("Main Bank Account", 100), line("Cash in Hand", credit=100)], jtype="Bank Transfer")
    bad(lambda: journal([line("Main Bank Account", 100), line("Main Bank Account", credit=100)], jtype="Bank Transfer"), "two different bank/cash")
    assert bal("Main Bank Account") == 600 and bal("Cash in Hand") == -100


def test_year_end_closing_only_touches_pl_and_retained_earnings(books):
    journal([line("Sales Revenue", 1000), line("Retained Earnings", credit=1000)], jtype="Year-End Closing")
    bad(lambda: journal([line("Sales Revenue", 1000), line("Share Capital", credit=1000)], jtype="Year-End Closing"), "Income, Expense and Retained Earnings")


def test_cancelling_flags_the_voucher_and_never_changes_an_amount(books):
    gj = journal([line("Rent", 300), line("Accrued Expenses", credit=300)])
    before = ledger.voucher_rows("General Journal", gj.name)
    assert not any(r["is_cancelled"] for r in before) and ledger.is_posted("General Journal", gj.name)
    gj.cancel()
    after = ledger.voucher_rows("General Journal", gj.name)
    strip = lambda rows: [{k: v for k, v in r.items() if k != "is_cancelled"} for r in rows]  # noqa: E731
    assert strip(after) == strip(before)                                                         # same accounts, same amounts, same dates: ONLY the flag changed
    assert all(r["is_cancelled"] == 1 for r in after) and not ledger.is_posted("General Journal", gj.name)
    rev = ledger.voucher_rows("General Journal", gj.name, reversals=True)
    assert len(rev) == 2 and all(r["is_reversal"] == 1 and r["is_cancelled"] == 1 for r in rev)  # the exact opposites, flagged too, so even a raw sum nets to zero
    assert {(r["account"], Dc(str(r["debit"])), Dc(str(r["credit"]))) for r in rev} == {("Rent", Dc(0), Dc(300)), ("Accrued Expenses", Dc(300), Dc(0))}
    assert bal("Rent") == 0 and bal("Accrued Expenses") == 0 and gl_count() == 4                 # nothing deleted: all four lines are still on record
    bad(gj.cancel, "Only a submitted document", DocStatusError)
    assert [r["reversal_of"] for r in rev] == [r["name"] for r in before]
    bad(lambda: ledger.cancel_voucher("General Journal", gj.name), "already been cancelled")


def test_a_cancelled_voucher_leaves_the_reports_but_can_be_shown_on_request(books):
    from velora.reporting.runner import run_report
    keep = journal([line("Rent", 100), line("Accrued Expenses", credit=100)])
    gone = journal([line("Rent", 300), line("Accrued Expenses", credit=300)])
    gone.cancel()
    gl = lambda **f: run_report("General Ledger", {"account": "Rent", "from_date": "2026-01-01", "to_date": "2026-12-31", **f})  # noqa: E731
    tidy = [r for r in gl().rows if r.values.get("voucher")]
    assert [r.values["voucher"] for r in tidy] == [f"General Journal {keep.name}"] and all("cancel" not in (r.values.get("voucher") or "") for r in tidy)    # no clutter
    shown = [r.values["voucher"] for r in gl(show_cancelled="1").rows if r.values.get("voucher")]
    assert shown.count(f"General Journal {gone.name} (cancelled)") == 2 and f"General Journal {keep.name}" in shown                           # the audit view has it all
    from velora.reporting.runner import run_report as rr
    tb = rr("Trial Balance", {"from_date": "2026-01-01", "to_date": "2026-12-31"})
    rent = next(r for r in tb.rows if r.type != "total" and "Rent" in str(r.values.get("account") or r.values.get("label") or r.values))
    assert 100 in [Dc(str(v)) for v in rent.values.values() if isinstance(v, (int, float, Dc))] and 400 not in [Dc(str(v)) for v in rent.values.values() if isinstance(v, (int, float, Dc))]   # only the live 100


def test_a_wrong_journal_is_fixed_by_cancelling_and_amending_and_the_books_stay_tidy(books):
    from velora.document import amend
    from velora.reporting.runner import run_report
    wrong = journal([line("Rent", 300), line("Accrued Expenses", credit=300)])                  # the mistake: it should have been 350
    wrong.cancel()
    assert bal("Rent") == 0 and bal("Accrued Expenses") == 0
    p = amend.copy_values("General Journal", wrong.name, "amend")
    assert p["suggested_name"] == f"{wrong.name}-1"
    v = p["values"]
    assert [(r["account"], r["debit"], r["credit"]) for r in v["lines"]] == [("Rent", 300, 0), ("Accrued Expenses", 0, 300)]
    v["lines"][0]["debit"], v["lines"][1]["credit"] = 350, 350
    fixed = new_doc("General Journal", **v).insert().submit()
    assert fixed.name == f"{wrong.name}-1" and fixed.amended_from == wrong.name
    assert bal("Rent") == 350 and bal("Accrued Expenses") == -350                                  # only the correction counts
    gl = [r.values["voucher"] for r in run_report("General Ledger", {"account": "Rent", "from_date": "2026-01-01", "to_date": "2026-12-31"}).rows if r.values.get("voucher")]
    assert gl == [f"General Journal {fixed.name}"]                                                  # the ledger shows ONE clean entry: no reversal clutter
    audit = [r.values["voucher"] for r in run_report("General Ledger", {"account": "Rent", "from_date": "2026-01-01", "to_date": "2026-12-31", "show_cancelled": "1"}).rows if r.values.get("voucher")]
    assert sorted(audit) == sorted([f"General Journal {wrong.name} (cancelled)"] * 2 + [f"General Journal {fixed.name}"])         # the full history, one click away
    assert gl_count() == 6                                                                          # nothing was ever deleted: 2 original + 2 cancelled mirrors + 2 corrected


def test_the_upgrade_patch_tidies_vouchers_cancelled_under_the_old_reversal_scheme(books):
    """Before 0.4 a cancel posted visible reversal lines. The patch flags those vouchers so old and new cancellations look the same in the reports."""
    from velora_accounts.patches.v0_4 import flag_cancelled_vouchers
    from velora.reporting.runner import run_report
    keep = journal([line("Rent", 100), line("Accrued Expenses", credit=100)])
    old = journal([line("Rent", 300), line("Accrued Expenses", credit=300)])
    from velora import db as _db
    with _db.transaction():                                                                          # (a voucher is always written in ONE transaction)
      for r in ledger.voucher_rows("General Journal", old.name):                                     # what the OLD cancel did: mirror lines, nothing flagged
        new_doc("GL Entry", posting_date=r["posting_date"], account=r["account"], debit=r["credit"], credit=r["debit"], party_type=r["party_type"], party=r["party"], voucher_type="General Journal",
                voucher_no=old.name, against=r["against"], remarks="Reversal", cost_center=r["cost_center"], fiscal_year=r["fiscal_year"], is_reversal=1, reversal_of=r["name"]).insert(ignore_permissions=True)
    gl = lambda **f: [r.values["voucher"] for r in run_report("General Ledger", {"account": "Rent", "from_date": "2026-01-01", "to_date": "2026-12-31", **f}).rows if r.values.get("voucher")]  # noqa: E731
    assert len(gl()) == 3 and any("reversal" in v for v in gl()) is False and gl_count() == 6        # before: the old voucher and its mirror both clutter the statement
    flag_cancelled_vouchers.execute()
    assert gl() == [f"General Journal {keep.name}"]                                                  # after: exactly as if it had been cancelled today
    assert sorted(gl(show_cancelled="1")) == sorted([f"General Journal {keep.name}"] + [f"General Journal {old.name} (cancelled)"] * 2)
    assert bal("Rent") == 100 and gl_count() == 6                                                    # amounts untouched, nothing deleted
    assert all(r["is_cancelled"] == 1 for r in ledger.voucher_rows("General Journal", old.name)) and not any(r["is_cancelled"] for r in ledger.voucher_rows("General Journal", keep.name))
    flag_cancelled_vouchers.execute()                                                                # safe to run again
    assert gl() == [f"General Journal {keep.name}"] and gl_count() == 6


def test_ledger_entries_can_never_be_edited_or_deleted_by_anyone(books):
    journal([line("Rent", 300), line("Accrued Expenses", credit=300)])
    e = get_doc("GL Entry", get_list("GL Entry", fields=["name"], limit=1)[0]["name"])
    e.debit = 1
    bad(e.save, "cannot be edited")
    bad(lambda: get_doc("GL Entry", e.name).delete(), "cannot be deleted")
    with session_as(MANAGER):
        bad(lambda: new_doc("GL Entry", account="Rent", debit=5, posting_date=D26).insert(), "permission|Permission", PermissionDenied)      # no one can write the ledger directly
    assert gl_count() == 2


def test_a_voucher_posts_once(books):
    gj = journal([line("Rent", 10), line("Accrued Expenses", credit=10)])
    bad(lambda: ledger.post("General Journal", gj.name, D26, [ledger.Leg("Rent", debit=1), ledger.Leg("Accrued Expenses", credit=1)]), "already been posted")


def test_reversing_journal_creates_its_automatic_reversal(books):
    gj = journal([line("Prepayments", 600), line("Rent", credit=600)], jtype="Reversing", reverse_on=date(2026, 4, 1))
    rev = get_list("General Journal", filters=[["reversal_of", "=", gj.name]], fields=["name", "posting_date", "docstatus", "is_auto_reversal"])
    assert len(rev) == 1 and rev[0]["docstatus"] == 1 and rev[0]["is_auto_reversal"] and rev[0]["posting_date"] == date(2026, 4, 1)
    assert bal("Prepayments", as_of=date(2026, 3, 31)) == 600 and bal("Prepayments", as_of=date(2026, 4, 1)) == 0       # visible until the reverse date
    bad(lambda: get_doc("General Journal", rev[0]["name"]).cancel(), f"Cancel {gj.name} instead")
    gj.cancel()
    assert get_doc("General Journal", rev[0]["name"]).docstatus == 2 and bal("Prepayments") == 0 and bal("Rent") == 0
    bad(lambda: journal([line("Prepayments", 1), line("Rent", credit=1)], jtype="Reversing"), "needs a 'Reverse On'")
    bad(lambda: journal([line("Prepayments", 1), line("Rent", credit=1)], jtype="Reversing", reverse_on=D26), "after the posting date")
    bad(lambda: journal([line("Prepayments", 1), line("Rent", credit=1)], jtype="General", reverse_on=date(2026, 5, 1)), "only for Reversing")
    bad(lambda: journal([line("Prepayments", 1), line("Rent", credit=1)], jtype="Reversing", reverse_on=date(2031, 1, 1)), "No fiscal year covers")


def test_lock_date_blocks_posting_and_cancelling_for_everyone(books):
    gj = journal([line("Rent", 10), line("Accrued Expenses", credit=10)], d=date(2026, 1, 15))
    with session_as(ACCOUNTANT):
        bad(lambda: c.set_lock_date(date(2026, 1, 31)), "Only an Accounts Manager")
    with session_as(MANAGER):
        c.set_lock_date(date(2026, 1, 31))
    bad(lambda: journal([line("Rent", 1), line("Accrued Expenses", credit=1)], d=date(2026, 1, 31)), "locked up to 2026-01-31")
    bad(gj.cancel, "locked up to")
    journal([line("Rent", 1), line("Accrued Expenses", credit=1)], d=date(2026, 2, 1))                    # the day after is open
    with session_as(MANAGER):
        c.set_lock_date(None)
    gj.cancel()                                                                                          # unlocking (an audited setting change) re-opens it
    assert bal("Rent") == 1


# ================================ receipts ================================
def receipt(**kw):
    r = new_doc("Receipt", **{"posting_date": D26, "bank_account": "Main Bank Account", **{k: v for k, v in kw.items() if k != "lines"}})
    for ln in kw.get("lines", []):
        r.append("lines", ln)
    r.insert()
    return r


def test_customer_receipt_clears_the_customer_account(books):
    journal([line("Trade Receivables", 100000, party_type="Customer", party="ACME"), line("Sales Revenue", credit=100000)])
    r = receipt(receipt_type="Customer", party="ACME", amount=60000, reference_no="TRF-1")
    assert (r.total, r.bank_amount) == (60000, 60000)
    r.submit()
    assert bal("Main Bank Account") == 60000 and bal("Trade Receivables", party="ACME") == 40000
    r.cancel()
    assert bal("Main Bank Account") == 0 and bal("Trade Receivables", party="ACME") == 100000


def test_receipt_with_wht_and_gateway_fee_posts_the_net_to_the_bank(books):
    r = receipt(receipt_type="Customer", party="ACME", amount=100000, wht_rate=5, fee_amount=150, method="Gateway", gateway="paystack", gateway_reference="T123")
    assert (r.wht_amount, r.fee_amount, r.bank_amount) == (5000, 150, 94850)
    r.submit()
    assert bal("Main Bank Account") == 94850 and bal("WHT Receivable") == 5000 and bal("Gateway Fees") == 150 and bal("Trade Receivables", party="ACME") == -100000
    assert total_dr_cr()[0] == total_dr_cr()[1] == 100000
    manual = receipt(receipt_type="Customer", party="ACME", amount=1000, wht_amount="33.33")                # a manual WHT amount when no rate is given
    assert manual.bank_amount == Dc("966.67") and manual.wht_account == "WHT Receivable"


def test_other_receipt_splits_across_accounts(books):
    r = receipt(receipt_type="Other", lines=[{"account": "Interest Income", "amount": 700}, {"account": "Other Income", "amount": 300, "narration": "Scrap sale"}])
    assert r.amount == r.total == 1000
    r.submit()
    assert bal("Main Bank Account") == 1000 and bal("Interest Income") == -700 and bal("Other Income") == -300


@pytest.mark.parametrize("kw,frag", [
    (dict(receipt_type="Customer", amount=10), "Choose the customer"),
    (dict(receipt_type="Customer", party="A", amount=0), "greater than zero"),
    (dict(receipt_type="Customer", party="A", amount=10, lines=[{"account": "Other Income", "amount": 1}]), "remove the lines"),
    (dict(receipt_type="Other"), "at least one line"),
    (dict(receipt_type="Other", lines=[{"account": "Cash in Hand", "amount": 5}]), "Bank Transfer journal"),
    (dict(receipt_type="Other", lines=[{"account": "Other Income", "amount": -5}]), "greater than zero"),
    (dict(receipt_type="Customer", party="A", amount=100, wht_amount=60, fee_amount=40), "leave nothing"),
    (dict(receipt_type="Customer", party="A", amount=100, wht_rate=5, wht_account="Rent"), "not a Tax account"),
    (dict(receipt_type="Customer", party="A", amount=100, bank_account="Rent"), "not a Bank or Cash"),
    (dict(receipt_type="Customer", party="A", amount=100, bank_account="Current Assets"), "group account"),
    (dict(receipt_type="Customer", party="A", amount=10.005), "more than 2 decimal"),
    (dict(receipt_type="Customer", party="A", amount=100, gateway_reference="X"), "Name the gateway"),
])
def test_receipt_validation(books, kw, frag):
    bad(lambda: receipt(**kw), frag)


def test_gateway_reference_can_only_be_used_once_so_retried_webhooks_cannot_double_post(books):
    r = receipt(receipt_type="Customer", party="A", amount=500, gateway="paystack", gateway_reference="REF1")
    r.submit()
    bad(lambda: receipt(receipt_type="Customer", party="A", amount=500, gateway="paystack", gateway_reference="REF1"), "already recorded on")
    receipt(receipt_type="Customer", party="A", amount=500, gateway="flutterwave", gateway_reference="REF1")        # another gateway's ref is separate
    r.cancel()
    receipt(receipt_type="Customer", party="A", amount=500, gateway="paystack", gateway_reference="REF1")          # a cancelled receipt frees its reference


def test_receipt_cannot_post_into_a_closed_period(books):
    r = receipt(receipt_type="Customer", party="A", amount=10, posting_date=date(2031, 1, 1))
    bad(r.submit, "No fiscal year covers")
    assert gl_count() == 0 and get_doc("Receipt", r.name).docstatus == 0


# ================================ payments ================================
def payment(**kw):
    p = new_doc("Payment", **{"posting_date": D26, "bank_account": "Main Bank Account", **{k: v for k, v in kw.items() if k != "lines"}})
    for ln in kw.get("lines", []):
        p.append("lines", ln)
    p.insert()
    return p


def test_vendor_payment_with_wht_splits_bank_and_tax(books):
    journal([line("Professional Fees", 100000), line("Trade Payables", credit=100000, party_type="Supplier", party="LAWFIRM")])
    p = payment(payment_type="Vendor", party="LAWFIRM", amount=100000, wht_rate=5)
    assert (p.wht_amount, p.bank_amount) == (5000, 95000)
    p.submit()
    assert bal("Trade Payables", party="LAWFIRM") == 0 and bal("Main Bank Account") == -95000 and bal("WHT Payable") == -5000
    p.cancel()
    assert bal("Main Bank Account") == 0 and bal("Trade Payables", party="LAWFIRM") == -100000


def test_direct_payment_and_staff_payee(books):
    p = payment(payment_type="Other", lines=[{"account": "Rent", "amount": 8000}, {"account": "VAT Input", "amount": 600}], wht_rate=10, remarks="Office rent")
    assert (p.total, p.wht_amount, p.bank_amount) == (8600, 860, 7740)
    p.submit()
    assert bal("Rent") == 8000 and bal("VAT Input") == 600 and bal("Main Bank Account") == -7740 and bal("WHT Payable") == -860
    s = payment(payment_type="Vendor", party_type="Employee", party="STAFF1", amount=500)
    s.submit()
    assert bal("Trade Payables", party="STAFF1") == 500


@pytest.mark.parametrize("kw,frag", [
    (dict(payment_type="Vendor", amount=10), "who is being paid"),
    (dict(payment_type="Other"), "at least one line"),
    (dict(payment_type="Other", lines=[{"account": "Main Bank Account", "amount": 5}]), "Bank Transfer journal"),
    (dict(payment_type="Vendor", party="A", amount=100, wht_amount=100), "leaves nothing"),
])
def test_payment_validation(books, kw, frag):
    bad(lambda: payment(**kw), frag)


def test_missing_default_accounts_give_an_actionable_message(books):
    with session_as(MANAGER):
        from velora.settings import set_setting
        set_setting("accounts.defaults", {})
    bad(lambda: payment(payment_type="Vendor", party="A", amount=10).submit(), "No default payable account is set")
    bad(lambda: receipt(receipt_type="Customer", party="A", amount=100, wht_rate=5), "No default wht receivable account")


def test_default_accounts_are_validated(books):
    with session_as(MANAGER):
        bad(lambda: c.set_default("receivable", "Rent"), "must be a Receivable account")
        bad(lambda: c.set_default("nonsense", "Rent"), "Unknown default")
        bad(lambda: c.set_default("receivable", "Assets"), "group account")
        c.set_default("receivable", "Trade Receivables")
    with session_as(ACCOUNTANT):
        bad(lambda: c.set_default("receivable", "Trade Receivables"), "Only an Accounts Manager")


# ================================ journal voucher (batch) ================================
def voucher(rows, **kw):
    jv = new_doc("Journal Voucher", voucher_date=D26, title="March adjustments", **kw)
    for r in rows:
        jv.append("lines", r)
    jv.insert()
    return jv


def jv_row(dr, cr, amount, **kw):
    return {"debit_account": dr, "credit_account": cr, "amount": amount, **kw}


def test_voucher_creates_one_general_journal_per_line(books):
    jv = voucher([jv_row("Rent", "Accrued Expenses", 1000, narration="Rent"), jv_row("Utilities", "Accrued Expenses", 250),
                  jv_row("Depreciation Expense", "Accumulated Depreciation", 400, journal_type="Depreciation", posting_date=date(2026, 3, 31))])
    assert jv.total_amount == 1650
    jv.submit()
    refs = [r.created_ref for r in jv.lines]
    assert len(set(refs)) == 3 and all(r.status == "Created" and r.created_type == "General Journal" for r in jv.lines)
    gjs = {g["name"]: g for g in get_list("General Journal", fields=["name", "journal_type", "posting_date", "docstatus", "source_ref", "reference"])}
    assert len(gjs) == 3 and all(g["docstatus"] == 1 and g["source_ref"] == jv.name and g["reference"] == "March adjustments" for g in gjs.values())
    assert gjs[refs[2]]["journal_type"] == "Depreciation" and gjs[refs[2]]["posting_date"] == date(2026, 3, 31) and gjs[refs[0]]["journal_type"] == "General"
    assert bal("Rent") == 1000 and bal("Accrued Expenses") == -1250 and bal("Depreciation Expense") == 400
    stored = get_doc("Journal Voucher", jv.name)
    assert [r.created_ref for r in stored.lines] == refs                                                   # the link to what was created is persisted


def test_voucher_lines_with_the_same_group_become_one_journal(books):
    jv = voucher([jv_row("Rent", "Accrued Expenses", 100, group_ref="A"), jv_row("Utilities", "Accrued Expenses", 50, group_ref="A"), jv_row("Rent", "Prepayments", 5)])
    jv.submit()
    refs = [r.created_ref for r in jv.lines]
    assert refs[0] == refs[1] != refs[2]
    assert len(get_doc("General Journal", refs[0]).lines) == 4 and len(get_doc("General Journal", refs[2]).lines) == 2
    bad(lambda: voucher([jv_row("Rent", "Accrued Expenses", 1, group_ref="G", posting_date=date(2026, 3, 1)), jv_row("Rent", "Accrued Expenses", 1, group_ref="G", posting_date=date(2026, 3, 2))]), "differ in date")


def test_voucher_party_lines(books):
    jv = voucher([jv_row("Trade Receivables", "Sales Revenue", 900, party_type="Customer", party="ACME")])
    jv.submit()
    assert bal("Trade Receivables", party="ACME") == 900
    bad(lambda: voucher([jv_row("Trade Receivables", "Sales Revenue", 9)]), "Line 1: Row 1: Trade Receivables is a Receivable account|Line 1:.*Customer is required")


@pytest.mark.parametrize("rows,frag", [
    ([], "at least one line"),
    ([jv_row("Rent", "Rent", 5)], "must differ"),
    ([jv_row("Rent", "Utilities", 0)], "greater than zero"),
    ([jv_row("Rent", "Utilities", 5), jv_row("Main Bank Account", "Sales Revenue", 5)], "Line 2: Row 1: Main Bank Account is a bank/cash account"),
    ([jv_row("Rent", "Ghost", 5)], "Line 1: .*does not exist"),
    ([jv_row("Operating Expenses", "Utilities", 5)], "Line 1: .*group account"),
    ([jv_row("Rent", "Utilities", "5.001")], "more than 2 decimal"),
])
def test_voucher_is_checked_line_by_line_before_anything_posts(books, rows, frag):
    bad(lambda: voucher(rows), frag)
    assert gl_count() == 0


def test_voucher_is_all_or_nothing_at_submit(books):
    with session_as(MANAGER):
        c.set_lock_date(date(2026, 1, 31))
    jv = voucher([jv_row("Rent", "Accrued Expenses", 100), jv_row("Utilities", "Accrued Expenses", 50), jv_row("Rent", "Accrued Expenses", 7, posting_date=date(2026, 1, 15))])
    bad(jv.submit, "Line 3: .*locked up to 2026-01-31")
    assert gl_count() == 0 and get_list("General Journal", fields=["name"]) == []                          # lines 1 and 2 were NOT created
    stored = get_doc("Journal Voucher", jv.name)
    assert stored.docstatus == 0 and all(r.status == "Pending" and not r.created_ref for r in stored.lines)
    with session_as(MANAGER):
        c.set_lock_date(None)
    stored.submit()                                                                                       # fixed: now it goes through, once
    assert gl_count() == 6


def test_cancelling_a_voucher_cancels_every_journal_it_made(books):
    jv = voucher([jv_row("Rent", "Accrued Expenses", 100), jv_row("Utilities", "Accrued Expenses", 50, group_ref="G"), jv_row("Rent", "Accrued Expenses", 5, group_ref="G")])
    jv.submit()
    refs = {r.created_ref for r in jv.lines}
    jv.cancel()
    assert all(get_doc("General Journal", r).docstatus == 2 for r in refs)
    assert all(r.status == "Cancelled" for r in get_doc("Journal Voucher", jv.name).lines)
    assert bal("Rent") == 0 and bal("Utilities") == 0 and bal("Accrued Expenses") == 0 and total_dr_cr()[0] == total_dr_cr()[1]


# ================================ permissions ================================
def test_roles(books):
    with session_as(VIEWER):
        assert len(get_list("Account", fields=["name"], limit=5)) == 5
        bad(lambda: new_doc("General Journal", posting_date=D26).insert(), "permission", PermissionDenied)
    with session_as(SALES):
        bad(lambda: get_list("GL Entry", fields=["name"]), "permission", PermissionDenied)
        bad(lambda: new_doc("Account", account_name="Hack", root_type="Asset").insert(), "permission", PermissionDenied)
    with session_as(ACCOUNTANT):
        gj = journal([line("Rent", 10), line("Accrued Expenses", credit=10)])                              # an Accountant records and submits ...
        bad(gj.cancel, "permission", PermissionDenied)                                                               # ... but only a manager cancels
        bad(lambda: new_doc("Account", account_name="Hack2", root_type="Asset").insert().delete(), "permission", PermissionDenied)
    with session_as(MANAGER):
        get_doc("General Journal", gj.name).cancel()
        bad(lambda: get_doc("GL Entry", get_list("GL Entry", fields=["name"], limit=1)[0]["name"]).delete(), "no 'delete' permission", PermissionDenied)   # not even a manager


# ================================ trial balance ================================
def test_trial_balance_balances_and_respects_periods(books):
    from velora_accounts.accounts.report.trial_balance.trial_balance import execute, trial_balance_data
    journal([line("Main Bank Account", 10000), line("Share Capital", credit=10000)], jtype="Opening Balance", d=date(2025, 12, 31))
    journal([line("Rent", 700), line("Accrued Expenses", credit=700)], d=date(2025, 11, 1))                          # LAST year's expense
    journal([line("Rent", 300), line("Accrued Expenses", credit=300)], d=date(2026, 2, 1))
    journal([line("Utilities", 50), line("Accrued Expenses", credit=50)], d=date(2026, 5, 1))
    data, unclosed = trial_balance_data(date(2026, 3, 1), date(2026, 6, 30))
    assert data["Rent"] == [300, 0, 0] and unclosed == 700                                                          # opening = this FY's 300; last year's 700 is reported, not lost
    assert data["Utilities"][1:] == [50, 0] and data["Main Bank Account"][0] == 10000
    res = execute({"from_date": "2026-03-01", "to_date": "2026-06-30"}).build().to_dict()
    totals = res["rows"][-1]["values"]
    assert res["rows"][-1]["type"] == "total"
    assert totals["od"] == totals["oc"] and totals["pd"] == totals["pc"] and totals["cd"] == totals["cc"]            # debits = credits, always
    assert totals["od"] == 11000 and totals["pd"] == 50 and totals["cd"] == 11050                                    # 10000 bank + 300 rent + 700 unclosed prior-year expense
    names = [r["values"].get("account") for r in res["rows"]]
    assert "Rent" in names and "Utilities" in names and "Cash in Hand" not in names                                  # empty accounts are not listed
    labels = [r["values"].get("account") for r in res["rows"] if r["type"] in ("header", "subtotal")]
    assert "Assets" in labels and "Total Assets" in labels and "Total unclosed" in labels
    unclosed_row = next(r for r in res["rows"] if "Unclosed profit/loss" in str(r["values"].get("account")))
    assert unclosed_row["values"]["od"] == 700 and unclosed_row["values"]["cd"] == 700


def test_trial_balance_report_runs_through_the_report_service_with_permissions(books):
    from velora.reporting.runner import run_report
    journal([line("Rent", 10), line("Accrued Expenses", credit=10)])
    res = run_report("Trial Balance", {"from_date": "2026-01-01", "to_date": "2026-12-31"})
    assert res.rows[-1].type == "total"
    with session_as(VIEWER):
        assert run_report("Trial Balance", {}).rows
    with session_as(SALES):
        bad(lambda: run_report("Trial Balance", {}), "may not run the report", PermissionDenied)


# ================================ randomised invariants ================================
def test_ledger_invariants_hold_for_hundreds_of_random_journals_and_cancellations(books):
    rnd = random.Random(20261108)
    leaves = [a["name"] for a in get_list("Account", filters=[["is_group", "=", 0]], fields=["name", "account_type"], limit=500)
              if a["account_type"] not in ("Bank", "Cash", "Receivable", "Payable")]
    posted = []
    for i in range(150):
        n = rnd.choice([2, 2, 3, 4])
        accts = rnd.sample(leaves, n)
        amounts = [Dc(rnd.randint(1, 99999)) / 100 for _ in range(n - 1)]
        legs = [line(a, amt) if rnd.random() < .5 else line(a, credit=amt) for a, amt in zip(accts, amounts)]
        net = sum(l["debit"] - l["credit"] for l in legs)
        legs.append(line(accts[-1], credit=net) if net > 0 else line(accts[-1], -net))
        d = date(2026, rnd.randint(1, 12), rnd.randint(1, 28))
        posted.append(journal(legs, d=d))
        if rnd.random() < .25:
            posted.pop(rnd.randrange(len(posted))).cancel()
    dr, cr = total_dr_cr()
    assert dr == cr and dr > 0                                                                                       # the ledger is balanced after every operation
    live = [r for gj in posted for r in ledger.voucher_rows("General Journal", gj.name)]
    for acct in leaves:                                                                                              # balances equal the sum of the NON-cancelled journals
        expect = sum(Dc(str(r["debit"])) - Dc(str(r["credit"])) for r in live if r["account"] == acct)
        assert bal(acct) == expect, acct
    from velora_accounts.accounts.report.trial_balance.trial_balance import execute
    t = execute({"from_date": "2026-01-01", "to_date": "2026-12-31"}).build().to_dict()["rows"][-1]["values"]
    assert t["cd"] == t["cc"] and t["pd"] == t["pc"] and t["od"] == t["oc"]


# ================== the ledger enforces its own rules, whoever calls it ==================
L = ledger.Leg


@pytest.mark.parametrize("legs,frag", [
    ([L("Rent", debit=100), L("Utilities", credit=90)], r"must be equal; the difference is 10"),
    ([L("Rent", debit=100), L("Utilities", credit=100), L("Cash in Hand", credit=1)], "must be equal"),
    ([L("Rent", debit=100, credit=100), L("Utilities", credit=0)], "not both"),
    ([L("Rent"), L("Utilities")], "debit or a credit amount"),
    ([L("Rent", debit=-5), L("Utilities", credit=-5)], "cannot be negative"),
    ([L("Rent", debit="1.005"), L("Utilities", credit="1.005")], "more than 2 decimal"),
    ([L("Rent", debit=5)], "at least two lines"),
    ([L("Trade Receivables", debit=5), L("Sales Revenue", credit=5)], "Customer is required"),
    ([L("Rent", debit=5, party_type="Customer", party="X"), L("Sales Revenue", credit=5)], "cannot carry a party"),
    ([L("Operating Expenses", debit=5), L("Utilities", credit=5)], "group account"),
])
def test_ledger_post_rejects_invalid_vouchers_directly(books, legs, frag):
    bad(lambda: ledger.post("Direct Voucher", "DV-1", D26, legs), frag)
    assert gl_count() == 0                                                  # all-or-nothing: not even one row of a bad voucher


def test_ledger_post_dates_and_idempotence_directly(books):
    ok = [L("Rent", debit=5), L("Utilities", credit=5)]
    bad(lambda: ledger.post("Direct Voucher", "DV-2", date(2031, 1, 1), ok), "No fiscal year covers")
    with session_as(MANAGER):
        c.set_lock_date(D26)
    bad(lambda: ledger.post("Direct Voucher", "DV-2", D26, ok), "locked up to")
    with session_as(MANAGER):
        c.set_lock_date(None)
    assert ledger.post("Direct Voucher", "DV-2", D26, ok) == 2
    bad(lambda: ledger.post("Direct Voucher", "DV-2", D26, ok), "already been posted")
    assert ledger.reverse("Direct Voucher", "DV-2") == 2 and ledger.reverse("Direct Voucher", "DV-404") == 0
    bad(lambda: ledger.reverse("Direct Voucher", "DV-2"), "already been cancelled")
    assert gl_count() == 4 and bal("Rent") == 0


def test_financial_statement_execution_and_transaction_drilldown_are_permission_scoped(books):
    from velora.reporting.layouts import execute_statement, statement_drilldown
    journal([line("Rent", 250), line("Utilities", 50), line("Accrued Expenses", credit=300)], d=date(2026, 11, 10))
    definition = {
        "rows": [{"code": "RENT", "description": "Rent", "type": "account", "account_no": "Rent"}],
        "columns": [{"code": "NOV", "caption": "November", "type": "net_change", "date_mode": "custom"}],
    }
    filters = {"from_date": "2026-11-01", "to_date": "2026-11-30"}
    with session_as(ACCOUNTANT):
        report = execute_statement(definition, filters)
        assert report["rows"][0]["values"]["NOV"] == pytest.approx(250)
        detail = statement_drilldown(definition, filters, "RENT", "NOV")
        assert len(detail["entries"]) == 1
        assert detail["entries"][0]["voucher_type"] == "General Journal"
        assert detail["entries"][0]["voucher_no"]
        assert detail["entries"][0]["debit"] == pytest.approx(250)
    with session_as(SALES):
        with pytest.raises(PermissionDenied):
            execute_statement(definition, filters)


def test_financial_report_formula_cells_do_not_allow_ledger_drilldown(books):
    from velora.reporting.layouts import statement_drilldown
    definition = {
        "rows": [
            {"code": "RENT", "type": "account", "account_no": "Rent"},
            {"code": "TOTAL", "type": "formula", "formula": "[RENT]+1"},
        ],
        "columns": [{"code": "NOV", "type": "net_change"}],
    }
    with session_as(ACCOUNTANT):
        with pytest.raises(ValidationError, match="no transaction-level"):
            statement_drilldown(definition, {"from_date": "2026-11-01", "to_date": "2026-11-30"}, "TOTAL", "NOV")



def test_financial_drilldown_can_be_restricted_to_one_account(books):
    from velora.reporting.layouts import statement_drilldown
    journal([line("Rent", 125), line("Utilities", 75), line("Accrued Expenses", credit=200)], d=date(2026, 11, 11))
    definition = {
        "rows": [{"code": "EXPENSES", "type": "account_category", "category": "Expense", "description": "Expenses"}],
        "columns": [{"code": "NOV", "type": "net_change"}],
    }
    filters = {"from_date": "2026-11-01", "to_date": "2026-11-30"}
    with session_as(ACCOUNTANT):
        result = statement_drilldown(definition, filters, "EXPENSES", "NOV", account_filter="Rent")
        assert result["accounts"] == ["Rent"]
        assert {entry["account"] for entry in result["entries"]} == {"Rent"}
        with pytest.raises(ValidationError, match="not part of this statement row"):
            statement_drilldown(definition, filters, "EXPENSES", "NOV", account_filter="Accrued Expenses")
