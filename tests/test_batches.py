"""Batch Bank Transaction, Expense Batch, Bank Transaction Processor: the router, pre-flight, all-or-nothing, duplicates, amortisation, Excel."""
import io
import random
from datetime import date
from decimal import Decimal as Dc

import pytest
from openpyxl import Workbook, load_workbook

from velora import get_doc, get_list, new_doc
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import session_as

from test_accounts import ACCOUNTANT, MANAGER, VIEWER, books  # noqa: F401  (fixture + sessions)
from velora_accounts import amortisation, batch_io, common as c, ledger, seed

BBT, EXB, BTP = "Batch Bank Transaction", "Expense Batch", "Bank Transaction Processor"
D = date(2026, 3, 10)
BANK = "Main Bank Account"


@pytest.fixture
def bk(books):  # noqa: F811
    seed.ensure_fiscal_year(2027)
    new_doc("Account", account_name="GTB Savings", parent_account="Current Assets", account_type="Bank").insert()
    return books


def make(dt=BBT, rows=(), **kw):
    base = {BBT: dict(batch_date=D, bank_account=BANK, title="t"), EXB: dict(batch_date=D, petty_cash_account="Cash in Hand", title="t"),
            BTP: dict(bank_account=BANK, statement_from=date(2026, 3, 1), statement_to=date(2026, 3, 31), title="t")}[dt]
    d = new_doc(dt, **{**base, **kw})
    for r in rows:
        d.append("lines", r)
    return d


def bal(account, **kw):
    return ledger.balance(account, **kw)


def vouchers(doc):
    return [(r.created_type, r.created_ref) for r in doc.lines if r.created_ref]


# ============================== the router ==============================
def test_every_row_becomes_the_right_voucher(bk):
    b = make(BBT, [
        {"outflow": 1000, "party_type": "Supplier", "party": "Acme Ltd", "narration": "Invoice 12", "reference_no": "R1"},     # supplier, no account  -> Vendor payment
        {"outflow": 500, "account": "Office Expenses", "narration": "Stationery"},                                          # an account            -> Other payment
        {"inflow": 2000, "party_type": "Customer", "party": "Bola Stores"},                                                  # customer, no account  -> Customer receipt
        {"inflow": 300, "account": "Interest Income"},                                                                       # an account            -> Other receipt
        {"outflow": 700, "trans_type": "Transfer", "account": "GTB Savings"},                                                # transfer out
        {"inflow": 100, "trans_type": "Transfer", "account": "GTB Savings"},                                                 # transfer in
    ]).insert()
    assert (b.total_inflow, b.total_outflow) == (Dc("2400"), Dc("2200"))
    b.submit()
    kinds = [(r.created_type, r.status) for r in b.lines]
    assert kinds == [("Payment", "Created"), ("Payment", "Created"), ("Receipt", "Created"), ("Receipt", "Created"), ("General Journal", "Created"), ("General Journal", "Created")]
    p1, p2, r1, r2, t1, t2 = (get_doc(r.created_type, r.created_ref) for r in b.lines)
    assert (p1.payment_type, p1.party, p1.party_type, p1.total) == ("Vendor", "Acme Ltd", "Supplier", Dc("1000"))
    assert (p2.payment_type, p2.lines[0].account) == ("Other", "Office Expenses")
    assert (r1.receipt_type, r1.party) == ("Customer", "Bola Stores") and (r2.receipt_type, r2.lines[0].account) == ("Other", "Interest Income")
    assert (t1.journal_type, t2.journal_type) == ("Bank Transfer", "Bank Transfer")
    assert {d.source_type for d in (p1, p2, r1, r2, t1, t2)} == {BBT} and {d.source_ref for d in (p1, r1, t1)} == {b.name}      # traceable both ways
    assert p1.reference_no == "R1" and p1.remarks == "Invoice 12"


def test_drafts_wait_for_approval_and_submitted_post_immediately(bk):
    draft = make(BBT, [{"outflow": 1000, "account": "Rent"}]).insert().submit()
    assert get_doc("Payment", draft.lines[0].created_ref).docstatus == 0 and bal(BANK) == 0                  # nothing in the ledger yet
    live = make(BBT, [{"outflow": 400, "account": "Rent"}, {"inflow": 150, "account": "Other Income"}], create_as="Submitted").insert().submit()
    assert all(get_doc(t, n).docstatus == 1 for t, n in vouchers(live))
    assert bal(BANK) == -250 and bal("Rent") == 400 and bal("Other Income") == -150


def test_transfers_move_money_between_your_own_accounts(bk):
    make(BBT, [{"outflow": 700, "trans_type": "Transfer", "account": "GTB Savings"}], create_as="Submitted").insert().submit()
    assert (bal(BANK), bal("GTB Savings")) == (-700, 700)
    make(BBT, [{"inflow": 200, "trans_type": "Transfer", "account": "GTB Savings"}], create_as="Submitted").insert().submit()
    assert (bal(BANK), bal("GTB Savings")) == (-500, 500)
    with pytest.raises(ValidationError, match="Row 1: .*name the other bank/cash account"):
        make(BBT, [{"outflow": 5, "trans_type": "Transfer"}]).insert()
    with pytest.raises(ValidationError, match="Row 1: .*bank/cash"):
        make(BBT, [{"outflow": 5, "trans_type": "Transfer", "account": "Rent"}]).insert()


def test_wht_and_fees_flow_through_to_the_vouchers(bk):
    b = make(BBT, [{"outflow": 100000, "party_type": "Supplier", "party": "Acme", "wht_rate": 5},
                   {"inflow": 10000, "party_type": "Customer", "party": "Bola", "fee_amount": 150}], create_as="Submitted").insert().submit()
    assert bal(BANK) == -95000 + 9850 and bal("WHT Payable") == -5000 and bal("Gateway Fees") == 150
    assert bal("Trade Payables", party="Acme") == 100000 and bal("Trade Receivables", party="Bola") == -10000


# ============================== pre-flight: every problem, per row, before anything is saved ==============================
def test_all_problems_are_reported_together_with_row_numbers(bk):
    b = make(BBT, [
        {"outflow": 10, "account": "Rent"},                                           # fine
        {"outflow": 10, "inflow": 5, "account": "Rent"},                               # both
        {"account": "Rent"},                                                           # neither
        {"outflow": 10},                                                               # no account, no party
        {"outflow": 10, "account": "Operating Expenses"},                              # group account
        {"outflow": -4, "account": "Rent"},                                            # negative
        {"outflow": Dc("1.005"), "account": "Rent"},                                   # sub-kobo precision is refused, not rounded
        {"outflow": 10, "account": "Rent", "trans_type": "Receipt"},                   # type contradicts direction
    ])
    with pytest.raises(ValidationError) as e:
        b.insert()
    msg = str(e.value)
    for n in (2, 3, 4, 5, 6, 7, 8):
        assert f"Row {n}:" in msg
    assert "Row 1:" not in msg and "not both" in msg and "group account" in msg and "more than 2 decimal places" in msg
    assert get_list(BBT, limit=5) == [] and get_list("Payment", limit=5) == []        # nothing was saved or created


def test_error_report_is_capped_but_says_how_many_more(bk):
    with pytest.raises(ValidationError) as e:
        make(BBT, [{"outflow": 10} for _ in range(40)]).insert()
    assert str(e.value).count("Row ") == 25 + 0 and "and 15 more row(s)" in str(e.value)


def test_amortisation_rules(bk):
    bad = [({"outflow": 100, "account": "Rent", "amortise": 1, "spread_periods": 1, "expense_account": "Rent"}, "between 2 and 60"),
           ({"outflow": 100, "amortise": 1, "spread_periods": 6}, "Expense Account"),
           ({"inflow": 100, "account": "Rent", "amortise": 1, "spread_periods": 6, "expense_account": "Rent"}, "only Payment rows"),
           ({"outflow": 100, "amortise": 1, "spread_periods": 6, "expense_account": "Sales Revenue"}, "not an Expense account"),
           ({"outflow": 100, "amortise": 1, "spread_periods": 6, "expense_account": "Rent", "party_type": "Supplier", "party": "Acme"}, "cannot carry a party"),
           ({"outflow": 100, "amortise": 1, "spread_periods": 6, "expense_account": "Rent", "account": GTB} if False else
            {"outflow": 100, "amortise": 1, "spread_periods": 6, "expense_account": "Rent", "account": "Cash in Hand"}, "bank/cash")]
    for row, frag in bad:
        with pytest.raises(ValidationError, match=frag):
            make(BBT, [row]).insert()
    with pytest.raises(ValidationError, match="fees apply to receipts only"):
        make(BBT, [{"outflow": 100, "account": "Rent", "fee_amount": 5}]).insert()


# ============================== all-or-nothing and cancelling ==============================
GTB = "GTB Savings"


def test_a_failure_at_submit_creates_nothing(bk):
    b = make(BBT, [{"posting_date": date(2026, 3, 10), "outflow": 100, "account": "Rent"}, {"posting_date": date(2026, 3, 1), "outflow": 200, "account": "Rent"},
                   {"posting_date": date(2026, 3, 12), "outflow": 300, "account": "Rent"}], create_as="Submitted").insert()
    c.set_lock_date(date(2026, 3, 5))                                                  # books get locked AFTER the batch was saved
    with pytest.raises(ValidationError, match=r"Row 2: .*locked"):
        b.submit()
    assert get_list("Payment", limit=10) == [] and bal(BANK) == 0 and bal("Rent") == 0   # row 1 was created, then rolled back with the rest
    assert get_doc(BBT, b.name).docstatus == 0 and all(r.status == "Pending" and not r.created_ref for r in get_doc(BBT, b.name).lines)


def test_a_failure_while_creating_rolls_back_every_voucher_already_created(bk, monkeypatch):
    """Pre-flight catches ordinary problems before creation starts, so this fails MID-creation (row 3 of 4, after rows 1-2 were created and posted)."""
    b = make(BBT, [{"outflow": 100 * n, "account": "Rent"} for n in range(1, 5)], create_as="Submitted").insert()
    real, calls = ledger.post, []

    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 3:
            raise ValidationError("the ledger refused this one")
        return real(*a, **kw)
    monkeypatch.setattr(ledger, "post", flaky)
    with pytest.raises(ValidationError, match="Row 3: the ledger refused this one"):
        b.submit()
    assert len(calls) == 3                                                           # rows 1 and 2 really were created before the failure
    assert get_list("Payment", limit=10) == [] and get_list("GL Entry", limit=10) == [] and bal(BANK) == 0 and bal("Rent") == 0
    fresh = get_doc(BBT, b.name)
    assert fresh.docstatus == 0 and all(r.status == "Pending" and not r.created_ref for r in fresh.lines)
    monkeypatch.setattr(ledger, "post", real)
    fresh.submit()                                                                   # and the SAME batch can simply be submitted again
    assert len(vouchers(fresh)) == 4 and bal("Rent") == 1000


def test_cancelling_removes_drafts_and_reverses_posted_vouchers(bk):
    d = make(BBT, [{"outflow": 100, "account": "Rent"}]).insert().submit()
    pay = d.lines[0].created_ref
    d.cancel()
    assert not get_list("Payment", filters=[["name", "=", pay]], limit=1) and get_doc(BBT, d.name).lines[0].status == "Cancelled"      # the draft is gone
    p = make(BBT, [{"outflow": 400, "account": "Rent"}, {"inflow": 90, "account": "Other Income"}], create_as="Submitted").insert().submit()
    assert bal(BANK) == -310
    refs = vouchers(p)
    p.cancel()
    assert bal(BANK) == 0 and bal("Rent") == 0 and bal("Other Income") == 0
    assert all(get_doc(t, n).docstatus == 2 for t, n in refs) and all(r.status == "Cancelled" for r in get_doc(BBT, p.name).lines)
    assert len(ledger.voucher_rows("Payment", refs[0][1], reversals=True)) == 2                                  # history kept, mirrored


def test_a_submitted_batch_cannot_be_edited_so_its_policy_cannot_change(bk):
    b = make(BBT, [{"outflow": 100, "account": "Rent"}]).insert().submit()
    b.create_as = "Submitted"
    with pytest.raises(Exception, match="cannot be edited"):
        b.save()


def test_all_skipped_rows_cannot_be_submitted(bk):
    with pytest.raises(ValidationError, match="Nothing to create"):
        make(EXB, [{"inflow": 100, "account": "Other Income"}]).insert().submit()


# ============================== duplicates ==============================
def test_importing_the_same_statement_twice_is_refused(bk):
    row = {"posting_date": D, "outflow": 5000, "account": "Rent", "reference_no": "TRX-77"}
    make(BTP, [row], create_as="Submitted").insert().submit()
    with pytest.raises(ValidationError, match=r"Row 1: Payment PAY-\d+ already records this"):
        make(BTP, [row]).insert()
    make(BTP, [{**row, "allow_duplicate": 1}]).insert()                                                  # genuine repeat: allowed on purpose
    make(BTP, [{**row, "posting_date": date(2026, 3, 11)}]).insert()                                      # another day: not a duplicate
    make(BTP, [{**row, "outflow": 5001}]).insert()
    with pytest.raises(ValidationError, match="duplicate of an earlier row in this batch"):
        make(BBT, [row, row]).insert()


def test_a_cancelled_voucher_does_not_block_re_entry(bk):
    row = {"posting_date": D, "outflow": 5000, "account": "Rent", "reference_no": "TRX-9"}
    first = make(BTP, [row], create_as="Submitted").insert().submit()
    first.cancel()
    make(BTP, [row]).insert()


# ============================== Expense Batch ==============================
def test_expense_batch_posts_only_expenses_unless_told_otherwise(bk):
    rows = [{"outflow": 300, "account": "Office Expenses"}, {"inflow": 1000, "account": "Other Income"}, {"outflow": 50, "account": "Utilities"}]
    e = make(EXB, rows, create_as="Submitted").insert()
    assert [r.status for r in e.lines] == ["Pending", "Skipped", "Pending"] and (e.total_inflow, e.total_outflow) == (0, Dc("350"))
    e.submit()
    assert len(vouchers(e)) == 2 and bal("Cash in Hand") == -350 and bal("Other Income") == 0
    f = make(EXB, rows, create_as="Submitted", post_inflows=1).insert()
    assert [r.status for r in f.lines] == ["Pending"] * 3
    f.post_inflows = 0
    assert [r.status for r in f.save().lines] == ["Pending", "Skipped", "Pending"]                         # flipping the switch re-decides


# ============================== Bank Transaction Processor ==============================
def test_statement_rows_must_sit_inside_the_period(bk):
    with pytest.raises(ValidationError, match=r"Row 2: 2026-04-02 is outside the statement period 2026-03-01 to 2026-03-31"):
        make(BTP, [{"posting_date": D, "outflow": 1, "account": "Rent"}, {"posting_date": date(2026, 4, 2), "outflow": 1, "account": "Rent"}]).insert()
    with pytest.raises(ValidationError, match="enter the transaction date"):
        make(BTP, [{"outflow": 1, "account": "Rent"}]).insert()
    with pytest.raises(ValidationError, match="before 'Statement From'"):
        make(BTP, [{"posting_date": D, "outflow": 1, "account": "Rent"}], statement_to=date(2026, 2, 1)).insert()


def test_the_rows_must_add_up_to_the_statement(bk):
    rows = [{"posting_date": D, "inflow": 10000, "account": "Other Income"}, {"posting_date": D, "outflow": 2500, "account": "Rent"}]
    ok = make(BTP, rows, opening_balance=1000, closing_balance=8500).insert()
    assert ok.statement_note == "Proved: opening 1,000.00 + movements 7,500.00 = closing 8,500.00"
    with pytest.raises(ValidationError, match=r"opening 1,000.00 \+ movements 7,500.00 = 8,500.00, but the closing balance is 8,400.00 \(difference -100.00\)"):
        make(BTP, rows, opening_balance=1000, closing_balance=8400).insert()
    assert make(BTP, rows).insert().statement_note.startswith("Opening/closing balance not entered")
    # WHT: the statement shows what actually left the bank
    w = make(BTP, [{"posting_date": D, "outflow": 100000, "party_type": "Supplier", "party": "Acme", "wht_rate": 5}], opening_balance=500000, closing_balance=405000).insert()
    assert "Proved" in w.statement_note


def test_processor_end_to_end_with_transfers_and_receipts(bk):
    b = make(BTP, [{"posting_date": date(2026, 3, 2), "inflow": 50000, "party_type": "Customer", "party": "Bola", "reference_no": "S1"},
                   {"posting_date": date(2026, 3, 3), "outflow": 12000, "account": "Rent", "reference_no": "S2"},
                   {"posting_date": date(2026, 3, 4), "outflow": 8000, "trans_type": "Transfer", "account": GTB, "reference_no": "S3"}],
             opening_balance=100000, closing_balance=130000, create_as="Submitted").insert().submit()
    assert bal(BANK) == 30000 and bal(GTB) == 8000 and bal("Rent") == 12000 and bal("Trade Receivables", party="Bola") == -50000
    assert [r.status for r in b.lines] == ["Created"] * 3


# ============================== amortisation ==============================
def prepaid_batch(**kw):
    return make(BBT, [{"posting_date": D, "outflow": 120000, "amortise": 1, "spread_periods": 12, "expense_account": "Rent", "narration": "Annual rent"}], **kw)


def schedule(b):
    return get_list("Amortisation Schedule", filters=[["source_ref", "=", b.name]], fields=amortisation.FIELDS, order_by="period_no asc", limit=100)


def test_the_cost_is_parked_in_prepayments_and_a_schedule_is_created(bk):
    b = prepaid_batch(create_as="Submitted").insert().submit()
    assert bal("Prepayments") == 120000 and bal("Rent") == 0 and bal(BANK) == -120000
    s = schedule(b)
    assert [x["period_date"] for x in s][:3] == [date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31)] and s[-1]["period_date"] == date(2027, 2, 28)
    assert len(s) == 12 and sum(x["amount"] for x in s) == 120000 and {x["status"] for x in s} == {"Scheduled"}


def test_the_remainder_goes_to_the_last_month_so_the_parts_add_up_exactly():
    assert amortisation.split(Dc("100000"), 3) == [Dc("33333.33"), Dc("33333.33"), Dc("33333.34")]
    assert amortisation.split(Dc("0.05"), 3) == [Dc("0.01"), Dc("0.01"), Dc("0.03")]
    for amount, n in ((Dc("1000.01"), 7), (Dc("99999.99"), 12), (Dc("5"), 60)):
        parts = amortisation.split(amount, n)
        assert sum(parts) == amount and len(parts) == n and all(p >= 0 for p in parts)
    assert amortisation.month_end(2026, 14) == date(2027, 2, 28) and amortisation.month_end(2027, 12) == date(2027, 12, 31) and amortisation.month_end(2028, 2) == date(2028, 2, 29)


def test_due_months_are_posted_once_each(bk):
    b = prepaid_batch(create_as="Submitted").insert().submit()
    out = amortisation.post_due(as_of=date(2026, 5, 31))
    assert len(out["posted"]) == 3 and not out["errors"] and bal("Rent") == 30000 and bal("Prepayments") == 90000
    assert amortisation.post_due(as_of=date(2026, 5, 31)) == {"posted": [], "waiting": [], "cancelled": [], "errors": []}          # safe to re-run
    gj = get_doc("General Journal", schedule(b)[0]["journal"])
    assert (gj.journal_type, gj.reference, gj.source_type) == ("Prepayment", f"Amortisation 1/12 of {b.lines[0].created_ref}", "Amortisation Schedule")
    assert len(amortisation.post_due(as_of=date(2027, 12, 31))["posted"]) == 9
    assert bal("Rent") == 120000 and bal("Prepayments") == 0 and bal(BANK) == -120000                                            # fully expensed


def test_nothing_is_recognised_until_the_payment_is_actually_posted(bk):
    b = prepaid_batch().insert().submit()                                                  # Draft payment
    assert amortisation.post_due(as_of=date(2026, 6, 30))["posted"] == [] and bal("Rent") == 0
    assert len(amortisation.post_due(as_of=date(2026, 6, 30))["waiting"]) == 4
    get_doc("Payment", b.lines[0].created_ref).submit()
    assert len(amortisation.post_due(as_of=date(2026, 6, 30))["posted"]) == 4 and bal("Rent") == 40000


def test_a_cancelled_payment_cancels_its_schedule(bk):
    b = prepaid_batch(create_as="Submitted").insert().submit()
    get_doc("Payment", b.lines[0].created_ref).cancel()
    out = amortisation.post_due(as_of=date(2026, 5, 31))
    assert out["posted"] == [] and len(out["cancelled"]) == 3 and bal("Rent") == 0


def test_locked_months_are_reported_not_fatal(bk):
    prepaid_batch(create_as="Submitted").insert().submit()
    c.set_lock_date(date(2026, 4, 30))
    out = amortisation.post_due(as_of=date(2026, 5, 31))
    assert len(out["posted"]) == 1 and len(out["errors"]) == 2 and all("locked" in e["error"] for e in out["errors"]) and bal("Rent") == 10000
    c.set_lock_date(None)
    assert len(amortisation.post_due(as_of=date(2026, 5, 31))["posted"]) == 2                  # catch-up once the lock moves


def test_cancelling_the_batch_unwinds_payment_schedule_and_posted_months(bk):
    b = prepaid_batch(create_as="Submitted").insert().submit()
    amortisation.post_due(as_of=date(2026, 5, 31))
    b.cancel()
    assert bal("Prepayments") == 0 and bal("Rent") == 0 and bal(BANK) == 0
    assert {x["status"] for x in schedule(b)} == {"Cancelled"} and get_doc("Payment", b.lines[0].created_ref).docstatus == 2


def test_only_accountants_post_amortisation(bk):
    with session_as(VIEWER):
        with pytest.raises(PermissionDenied):
            amortisation.post_due()
    with session_as(ACCOUNTANT):
        assert amortisation.post_due(as_of=date(2026, 1, 1))["posted"] == []


# ============================== permissions ==============================
def test_roles(bk):
    with session_as(VIEWER):
        with pytest.raises(PermissionDenied):
            make(BBT, [{"outflow": 1, "account": "Rent"}]).insert()
    with session_as(ACCOUNTANT):
        b = make(BBT, [{"outflow": 1, "account": "Rent"}]).insert().submit()                 # may create and submit batches
        with pytest.raises(PermissionDenied):
            b.cancel()                                                                       # but not cancel them
    with session_as(MANAGER):
        get_doc(BBT, b.name).cancel()
    with session_as(VIEWER):
        assert get_doc(BBT, b.name).docstatus == 2                                           # read-only access works


# ============================== Excel / CSV ==============================
def draft(dt=BBT, **kw):
    return make(dt, [], **kw)


def xlsx(rows, sheet="Transactions"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_template_has_headings_and_instructions():
    wb = load_workbook(io.BytesIO(batch_io.template_bytes()))
    assert wb.sheetnames == ["Transactions", "Instructions"]
    assert [x.value for x in wb["Transactions"][1]][:5] == ["Date", "Type", "Bank Account", "Money In", "Money Out"]
    assert any("Money In = money that came into the bank" in (r[0].value or "") for r in wb["Instructions"].iter_rows())


def test_a_banks_own_statement_headings_are_understood_in_any_order(bk):
    f = xlsx([["Bank statement - GTBank March"], ["Value Date", "Description", "Withdrawal", "Deposit", "Transaction Reference", "Balance"],
              [date(2026, 3, 2), "Rent paid", 5000, None, "T1", 95000], ["03/03/2026", "Customer lodgement", None, "1,200.50", "T2", 96200.5], [None, None, None, None, None, None]])
    b = draft(BTP)
    rep = batch_io.import_rows(b, f)
    assert rep["imported"] == 2 and rep["errors"] == [] and rep["unknown_columns"] == ["Balance"]
    r1, r2 = b.lines
    assert (r1.posting_date, r1.outflow, r1.narration, r1.reference_no) == (date(2026, 3, 2), Dc("5000.00"), "Rent paid", "T1")
    assert (r2.posting_date, r2.inflow) == (date(2026, 3, 3), Dc("1200.50"))                    # day-first dates, thousands commas


def test_bad_rows_are_reported_individually_and_good_rows_still_import(bk):
    f = xlsx([["Date", "Money In", "Money Out", "Account", "Type", "Party Type", "Method"],
              ["2026-03-02", None, 100, "Rent", None, None, None],                       # excel row 2: fine
              ["2026-03-03", None, 100, "No Such Account", None, None, None],            # 3: unknown account
              ["not a date", None, 100, "Rent", None, None, None],                       # 4
              ["2026-03-05", 5, 5, "Rent", None, None, None],                            # 5: both
              ["2026-03-06", None, None, "Rent", None, None, None],                      # 6: neither
              ["2026-03-07", None, -50, "Rent", None, None, None],                       # 7: negative
              ["2026-03-08", None, 10, "Rent", "Swap", None, None],                      # 8: bad type
              ["2026-03-09", None, 10, "Rent", None, "Alien", None],                     # 9: bad party type
              ["2026-03-09", None, 10, "Rent", None, None, "Barter"],                    # 10: bad method
              ["2026-03-10", None, "abc", "Rent", None, None, None],                     # 11: not a number
              ["2026-03-11", None, 20, "Rent", "payment", None, "cheque"]])              # 12: fine (case-insensitive)
    b = draft(BTP)
    rep = batch_io.import_rows(b, f)
    assert rep["imported"] == 2 and [e["row"] for e in rep["errors"]] == [3, 4, 5, 6, 7, 8, 9, 10, 11]
    msgs = {e["row"]: e["error"] for e in rep["errors"]}
    assert "does not exist" in msgs[3] and "not a date" in msgs[4] and "not both" in msgs[5] and "enter an amount" in msgs[6] and "cannot be negative" in msgs[7]
    assert "Receipt, Payment or Transfer" in msgs[8] and "Customer, Supplier or Employee" in msgs[9] and "Method" in msgs[10] and "not a number" in msgs[11]
    assert (b.lines[1].trans_type, b.lines[1].method) == ("Payment", "Cheque")
    b.save()                                                                                  # and the imported rows pre-flight like any others


def test_replace_keeps_nothing_pending_and_csv_works(bk):
    b = draft(BBT)
    batch_io.import_rows(b, b"Date,Money Out,Account\n2026-03-02,10,Rent\n2026-03-03,20,Rent\n", "s.csv")
    assert len(b.lines) == 2
    batch_io.import_rows(b, b"Date,Money Out,Account\n2026-03-04,30,Rent\n", "s.csv")
    assert len(b.lines) == 3
    rep = batch_io.import_rows(b, b"\xef\xbb\xbfDate,Money Out,Account\n2026-03-05,40,Rent\n", "s.csv", replace=True)       # BOM from Excel's CSV export
    assert rep["imported"] == 1 and [r.outflow for r in b.lines] == [Dc("40.00")]


def test_export_then_import_round_trips(bk):
    b = make(BBT, [{"posting_date": D, "outflow": 1000, "party_type": "Supplier", "party": "Acme", "reference_no": "R1", "wht_rate": 5, "narration": "n1"},
                   {"posting_date": D, "inflow": 250.5, "account": "Other Income", "method": "Cheque"},
                   {"posting_date": D, "outflow": 120, "amortise": 1, "spread_periods": 6, "expense_account": "Rent"}]).insert()
    wb = load_workbook(io.BytesIO(batch_io.export_bytes(b)))
    assert [c_.value for c_ in wb.active[1]][-2:] == ["Status", "Created Document"]
    c2 = draft(BBT)
    rep = batch_io.import_rows(c2, batch_io.export_bytes(b))
    assert rep["imported"] == 3 and rep["errors"] == [] and rep["unknown_columns"] == []
    for a, z in zip(b.lines, c2.lines):
        for f in (field for _, field in batch_io.COLUMNS):
            assert (a.get(f) or None) == (z.get(f) or None), f
    c2.save()


def test_formulas_cannot_be_smuggled_in_or_out(bk):
    b = make(BBT, [{"posting_date": D, "outflow": 5, "account": "Rent", "narration": '=HYPERLINK("http://evil","x")', "reference_no": "+cmd|' /C calc'!A0"}]).insert()
    ws = load_workbook(io.BytesIO(batch_io.export_bytes(b))).active
    cells = [cell for row in ws.iter_rows() for cell in row if isinstance(cell.value, str) and cell.value[:1] in "=+"]
    assert cells and all(cell.data_type == "s" for cell in cells)                              # stored as text, never evaluated
    back = draft(BBT)
    batch_io.import_rows(back, batch_io.export_bytes(b))
    assert back.lines[0].narration.startswith("=HYPERLINK")                                    # survives as plain text


def test_import_refuses_unsafe_or_wrong_input(bk):
    with pytest.raises(ValidationError, match="draft"):
        batch_io.import_rows(make(BBT, [{"outflow": 1, "account": "Rent"}]).insert().submit(), xlsx([["Money Out"], [1]]))
    for content, frag in ((b"", "empty"), (b"just,some\nrandom,text\n", "No recognisable column headings"), (xlsx([["Date", "Narration"], ["2026-03-01", "x"]]), "Money In"),
                          (b"PK\x03\x04garbage", "Could not read"), (b"x" * 5_100_000, "larger than 5 MB")):
        with pytest.raises(ValidationError, match=frag):
            batch_io.import_rows(draft(BBT), content, "f.xlsx")
    big = b"Money Out\n" + b"1\n" * 5001
    with pytest.raises(ValidationError, match="At most 5000 rows"):
        batch_io.import_rows(draft(BBT), big, "big.csv")


# ============================== the invariant that matters ==============================
def test_random_batches_always_leave_the_books_balanced_and_cancel_back_to_zero(bk):
    rng = random.Random(7)
    accts = ["Rent", "Utilities", "Office Expenses", "Other Income", "Interest Income"]
    submitted = []
    for n in range(25):
        rows = []
        for _ in range(rng.randint(1, 6)):
            amt = Dc(rng.randint(1, 900000)) / 100
            kind = rng.choice(["pay", "rec", "cust", "vend", "xfer"])
            if kind == "pay":
                rows.append({"outflow": amt, "account": rng.choice(accts[:3])})
            elif kind == "rec":
                rows.append({"inflow": amt, "account": rng.choice(accts[3:]), "fee_amount": min(amt - Dc("0.01"), Dc(rng.randint(0, 50))) if amt > 1 else 0})
            elif kind == "cust":
                rows.append({"inflow": amt, "party_type": "Customer", "party": f"C{rng.randint(1, 4)}"})
            elif kind == "vend":
                rows.append({"outflow": amt, "party_type": "Supplier", "party": f"S{rng.randint(1, 4)}", "wht_rate": rng.choice([0, 5, 10])})
            else:
                rows.append({"outflow": amt, "trans_type": "Transfer", "account": GTB})
        b = make(rng.choice([BBT, BTP]), [{**r, "posting_date": date(2026, 3, rng.randint(1, 28))} for r in rows], create_as="Submitted").insert().submit()
        submitted.append(b)
        total = sum(x["debit"] - x["credit"] for x in get_list("GL Entry", fields=["debit", "credit"], limit=100000))
        assert total == 0, f"books out of balance after batch {n}"
    for b in rng.sample(submitted, len(submitted)):
        get_doc(b.doctype, b.name).cancel()
    accounts = {x["account"] for x in get_list("GL Entry", fields=["account"], limit=100000)}
    assert all(bal(a) == 0 for a in accounts), {a: bal(a) for a in accounts if bal(a)}
