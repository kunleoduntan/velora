"""Bank Account master, shared-cost distribution from Finance Settings, and amortised prepayments on Payments and Receipts."""
from datetime import date
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc, get_list
from velora.exceptions import ValidationError
from velora.permissions import session_as
from test_cash_transactions import setup_cash, approve, MAKER

D = Decimal


def _cost_centres():
    return [new_doc("Cost Centre", cost_centre_code=c, cost_centre_name=c).insert(ignore_permissions=True).name for c in ("ADM", "OPS")]


def _settings(ccs, pcts=(60, 40)):
    rows = [{"rule_name": "Shared Rent", "cost_centre": cc, "percentage": p} for cc, p in zip(ccs, pcts)]
    existing = get_list("Finance Settings", fields=["name"], limit=1, ignore_permissions=True)
    doc = get_doc("Finance Settings", existing[0]["name"], ignore_permissions=True) if existing else new_doc("Finance Settings", settings_name="Primary", country_code="NG", base_currency="NGN", decimal_places=2)
    doc.cost_distribution_lines = []
    for r in rows: doc.append("cost_distribution_lines", r)
    doc.save(ignore_permissions=True) if existing else doc.insert(ignore_permissions=True)


def _net(account, cc=None):
    f = {"account": account}
    if cc: f["cost_centre"] = cc
    rows = get_list("Account Ledger Record", filters=f, fields=["debit", "credit"], limit=1000)
    return sum(D(str(r["debit"] or 0)) - D(str(r["credit"] or 0)) for r in rows)


def test_bank_account_fills_the_ledger_account_and_checks_currency(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        bank = new_doc("Bank Account", account_code="GTB-001", account_name="GTBank Current", bank_name="GTBank", account_number="0123456789", gl_account=accounts["1000"].name, currency="NGN").insert(ignore_permissions=True)
        with pytest.raises(ValidationError):
            new_doc("Bank Account", account_code="BAD", account_name="Bad", gl_account=accounts["5000"].name).insert(ignore_permissions=True)
        with session_as(MAKER):
            rcpt = new_doc("Receipt", receipt_date=date.today(), posting_date=date.today(), purpose="Other Income", currency="NGN", exchange_rate=1, bank_account=bank.name,
                           narration="Via bank account", lines=[{"account": accounts["4000"].name, "amount": 500, "description": "income"}]).insert(ignore_permissions=True)
        assert rcpt.cash_account == accounts["1000"].name
        approve(rcpt)
        assert _net(accounts["1000"].name) == D(500)
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="held in NGN"):
                new_doc("Receipt", receipt_date=date.today(), posting_date=date.today(), purpose="Other Income", currency="USD", exchange_rate=1500, bank_account=bank.name,
                        narration="wrong currency", lines=[{"account": accounts["4000"].name, "amount": 5}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_shared_cost_is_split_by_the_finance_settings_percentages(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        adm, ops = _cost_centres(); _settings([adm, ops])
        assert get_list("Cost Distribution Rule", filters={"rule_name": "Shared Rent"}, fields=["name"], limit=1, ignore_permissions=True)
        with session_as(MAKER):
            pay = new_doc("Payment", payment_date=date.today(), posting_date=date.today(), purpose="Expense Payment", currency="NGN", exchange_rate=1, cash_account=accounts["1000"].name,
                          beneficiary="Landlord", narration="Rent", is_shared_cost=1, distribution_rule="Shared Rent",
                          lines=[{"account": accounts["5000"].name, "amount": 1000, "description": "Office rent"}]).insert(ignore_permissions=True)
        approve(pay)
        assert _net(accounts["5000"].name, adm) == D(600) and _net(accounts["5000"].name, ops) == D(400)
        assert _net(accounts["1000"].name) == D(-1000)
        # percentages that do not total 100 are refused in Finance Settings
        with pytest.raises(ValidationError, match="100%"):
            _settings([adm, ops], (60, 30))
    finally:
        velora.shutdown()


def test_prepayment_creates_pending_recognition_schedules_per_cost_centre(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        adm, ops = _cost_centres(); _settings([adm, ops])
        prepaid = new_doc("Account", account_code="1300", account_name="Prepaid Expenses", account_group="A", account_type="PREPAYMENT", allow_manual_posting=1).insert(ignore_permissions=True)
        with session_as(MAKER):
            pay = new_doc("Payment", payment_date=date.today(), posting_date=date.today(), purpose="Prepayment", currency="NGN", exchange_rate=1, cash_account=accounts["1000"].name,
                          beneficiary="Insurer", narration="Annual insurance", is_shared_cost=1, distribution_rule="Shared Rent", is_amortised_cost=1,
                          amortisation_frequency="Monthly", amortisation_start_date=date(date.today().year, 1, 1), amortisation_end_date=date(date.today().year, 12, 31),
                          recognition_account=accounts["5000"].name,
                          lines=[{"account": prepaid.name, "amount": 1200, "description": "Insurance"}]).insert(ignore_permissions=True)
        approve(pay)
        schedules = get_list("Recognition Schedule", filters={"source_document": pay.name}, fields=["name", "total_amount", "cost_centre", "approval_status", "schedule_type"], limit=10, ignore_permissions=True)
        assert sorted((s["cost_centre"], D(str(s["total_amount"]))) for s in schedules) == sorted([(adm, D(720)), (ops, D(480))])
        assert {s["approval_status"] for s in schedules} == {"Approved"} and {s["schedule_type"] for s in schedules} == {"Prepayment"}
        # amortisation is only for the right purpose
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="Prepayment"):
                new_doc("Payment", payment_date=date.today(), posting_date=date.today(), purpose="Expense Payment", currency="NGN", exchange_rate=1, cash_account=accounts["1000"].name,
                        beneficiary="X", narration="n", is_amortised_cost=1, amortisation_start_date=date.today(), amortisation_end_date=date.today(), recognition_account=accounts["5000"].name,
                        lines=[{"account": accounts["5000"].name, "amount": 10}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_journal_entry_voucher_posts_each_row_with_its_opposite_leg(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            jev = new_doc("Journal Entry Voucher", title="Month-end", voucher_date=date.today(), posting_date=date.today(), currency="NGN", exchange_rate=1, narration="Bulk journal",
                          lines=[
                              {"trans_date": date.today(), "transaction_description": "Supplier invoice booked", "account_type": "Supplier", "party": supplier.name,
                               "trans_effect": "Credit", "amount": 700, "corresponding_account": accounts["5000"].name},
                              {"trans_date": date.today(), "transaction_description": "Bank charge", "account_type": "Account GL", "party": accounts["5000"].name,
                               "trans_effect": "Debit", "amount": 50, "corresponding_account": accounts["1000"].name}]).insert(ignore_permissions=True)
        assert jev.lines[0].party_name == "Supply Co" and jev.total_debit == D(50) and jev.total_credit == D(700)
        approve(jev)
        assert _net(accounts["2100"].name) == D(-700)          # supplier control account, credited
        assert _net(accounts["5000"].name) == D(700) + D(50)   # expense debited by both rows
        assert _net(accounts["1000"].name) == D(-50)
        rows = get_list("Account Ledger Record", fields=["debit", "credit"], limit=100)
        assert sum(D(str(r["debit"] or 0)) for r in rows) == sum(D(str(r["credit"] or 0)) for r in rows)
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="must differ"):
                new_doc("Journal Entry Voucher", title="Bad", voucher_date=date.today(), posting_date=date.today(), currency="NGN", exchange_rate=1, narration="n",
                        lines=[{"trans_date": date.today(), "transaction_description": "x", "account_type": "Account GL", "party": accounts["5000"].name, "trans_effect": "Debit",
                                "amount": 1, "corresponding_account": accounts["5000"].name}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def _expense_invoice(accounts, supplier, **extra):
    return new_doc("Purchase Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=supplier.name, currency="NGN", exchange_rate=1,
                   narration="Office rent", lines=[{"account": accounts["5000"].name, "description": "Rent", "quantity": 1, "uom": "Each", "amount": 1000}], **extra)


def test_purchase_invoice_shares_and_amortises_cost_from_the_distribution_rule(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        adm, ops = _cost_centres(); _settings([adm, ops])
        prepaid = new_doc("Account", account_code="1300", account_name="Prepaid Expenses", account_group="A", account_type="PREPAYMENT", allow_manual_posting=1).insert(ignore_permissions=True)
        with session_as(MAKER):
            inv = _expense_invoice(accounts, supplier, is_shared_cost=1, distribution_rule="Shared Rent", is_amortised_cost=1, amortisation_frequency="Monthly",
                                   amortisation_start_date=date.today().replace(day=1), amortisation_end_date=date.today().replace(day=1).replace(year=date.today().year + 1) , prepayment_account=prepaid.name).insert(ignore_permissions=True)
        assert [(r.cost_centre, D(str(r.percentage))) for r in inv.cost_allocations] == [(adm, D(60)), (ops, D(40))]
        approve(inv)
        assert _net(prepaid.name, adm) == D(600) and _net(prepaid.name, ops) == D(400)
        assert _net(accounts["2100"].name) == D(-1000)
        schedules = get_list("Recognition Schedule", filters={"source_document": inv.name}, fields=["name", "total_amount", "cost_centre"], limit=10, ignore_permissions=True)
        assert sorted((s["cost_centre"], D(str(s["total_amount"]))) for s in schedules) == sorted([(adm, D(600)), (ops, D(400))])
    finally:
        velora.shutdown()


def test_purchase_invoice_rule_needs_shared_cost_and_a_defined_rule(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        adm, ops = _cost_centres(); _settings([adm, ops])
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="Is Shared Cost"):
                _expense_invoice(accounts, supplier, distribution_rule="Shared Rent").insert(ignore_permissions=True)
            with pytest.raises(ValidationError, match="not defined"):
                _expense_invoice(accounts, supplier, is_shared_cost=1, distribution_rule="No Such Rule").insert(ignore_permissions=True)
        _settings([adm, ops], pcts=(60, 40))
        with session_as(MAKER):
            inv = _expense_invoice(accounts, supplier, is_shared_cost=1, distribution_rule="Shared Rent").insert(ignore_permissions=True)
        approve(inv)
        assert _net(accounts["5000"].name, adm) == D(600) and _net(accounts["5000"].name, ops) == D(400)
    finally:
        velora.shutdown()
