from datetime import date
from decimal import Decimal

import pytest
import velora
from velora import new_doc, get_doc, get_list
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora_erp.finance.engine import get_account_balance
from velora_erp.finance.recognition.schedules import process_due_recognitions
from velora_erp.setup import after_install

MAKER = Session("cost-maker@example.test", frozenset({"Accountant"}))
APPROVER = Session("cost-approver@example.test", frozenset({"Finance Manager"}))


def setup_cost(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'cost-treatment.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    today = date.today(); year = today.year
    new_doc("Financial Year", year_name=f"FY-{year}", start_date=date(year, 1, 1), end_date=date(year, 12, 31), status="Open", is_current=1).insert(ignore_permissions=True)
    new_doc("Financial Period", period_name=f"FY-{year}-P01", financial_year=f"FY-{year}", period_number=1, start_date=date(year, 1, 1), end_date=date(year, 12, 31), status="Open").insert(ignore_permissions=True)
    groups = {}
    for code, label, root in [("A", "Assets", "Asset"), ("L", "Liabilities", "Liability"), ("I", "Income", "Income"), ("X", "Expense", "Expense")]:
        groups[code] = new_doc("Account Group", group_code=code, group_name=label, root_type=root, is_group=0).insert(ignore_permissions=True)
    def account(code, name, group, kind, **extra):
        return new_doc("Account", account_code=code, account_name=name, account_group=groups[group].name, account_type=kind, allow_manual_posting=1, **extra).insert(ignore_permissions=True)
    ar = account("1100", "Receivables", "A", "RECEIVABLE", is_control_account=1, control_account_type="Receivables", requires_party=1)
    ap = account("2100", "Payables", "L", "PAYABLE", is_control_account=1, control_account_type="Payables", requires_party=1)
    expense = account("5000", "Rent Expense", "X", "OPERATING_EXPENSE")
    input_vat = account("1200", "Input VAT", "A", "CLEARING")
    prepaid = account("1300", "Prepayments", "A", "PREPAYMENT")
    due_from = account("1310", "Due From Affiliates", "A", "INTERCOMPANY_RECEIVABLE")
    new_doc("Supplier Group", group_code="SG", group_name="Suppliers", is_group=0).insert(ignore_permissions=True)
    supplier = new_doc("Supplier", supplier_code="S001", supplier_name="Landlord and Insurer", supplier_group="SG", supplier_type="Company", control_account=ap.name).insert(ignore_permissions=True)
    cc = new_doc("Cost Centre", cost_centre_code="HQ", cost_centre_name="Head Office", is_group=0, disabled=0).insert(ignore_permissions=True)
    bu = new_doc("Business Unit", business_unit_code="OPS", business_unit_name="Operations", disabled=0).insert(ignore_permissions=True)
    return {"supplier": supplier, "expense": expense, "input_vat": input_vat, "prepaid": prepaid, "due_from": due_from, "cost_centre": cc, "business_unit": bu, "payables": ap}


def approve_submit(doc):
    with session_as(APPROVER):
        doc = get_doc(doc.doctype, doc.name)
        doc.approval_status = "Approved"
        doc.save(ignore_permissions=True)
        doc.submit(ignore_permissions=True)
        doc.reload()
    return doc


def make_invoice(accounts, **kwargs):
    data = dict(invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=accounts["supplier"].name,
                currency="NGN", exchange_rate=1, narration="Shared office rent", lines=[{"account": accounts["expense"].name, "description": "Office rent", "amount": 1200}])
    data.update(kwargs)
    return new_doc("Purchase Invoice", **data)


def test_purchase_invoice_amortisation_creates_pending_quarterly_schedule_and_posts_prepaid(tmp_path):
    a = setup_cost(tmp_path)
    try:
        with session_as(MAKER):
            invoice = make_invoice(a, is_amortised_cost=1, amortisation_frequency="Quarterly",
                amortisation_start_date=date(date.today().year, 1, 1), amortisation_end_date=date(date.today().year, 12, 31),
                prepayment_account=a["prepaid"].name).insert()
            assert len(invoice.amortisation_preview) == 4
            invoice = approve_submit(invoice)
        assert get_account_balance(a["prepaid"].name) == Decimal("1200.000000")
        assert get_account_balance(a["expense"].name) == Decimal("0.000000")
        schedules = get_list("Recognition Schedule", filters={"source_doctype": "Purchase Invoice", "source_document": invoice.name}, fields=["name"], limit=10)
        assert len(schedules) == 1
        schedule = get_doc("Recognition Schedule", schedules[0]["name"])
        assert (schedule.docstatus, schedule.approval_status, schedule.frequency, schedule.period_count) == (0, "Approved", "Quarterly", 4)
        assert schedule.end_date == date(date.today().year, 12, 31)
        with session_as(APPROVER):
            schedule.approval_status = "Approved"; schedule.save(ignore_permissions=True); schedule.submit(ignore_permissions=True)
        first_due = date(date.today().year, 1, 1)
        made = process_due_recognitions(as_of_date=first_due)
        assert len(made) == 1
        assert get_account_balance(a["expense"].name) == Decimal("300.000000")
        assert get_account_balance(a["prepaid"].name) == Decimal("900.000000")
    finally:
        velora.shutdown()


def test_shared_cost_splits_purchase_expense_by_cost_centre_and_business_unit(tmp_path):
    a = setup_cost(tmp_path)
    try:
        with session_as(MAKER):
            invoice = make_invoice(a, is_shared_cost=1, cost_allocations=[
                {"allocation_type": "Cost Centre", "cost_centre": a["cost_centre"].name, "percentage": 60},
                {"allocation_type": "Business Unit", "business_unit": a["business_unit"].name, "percentage": 40},
            ]).insert()
            invoice = approve_submit(invoice)
        assert get_account_balance(a["expense"].name) == Decimal("1200.000000")
        entries = get_list("Account Ledger Record", filters={"source_doctype": "Purchase Invoice", "source_name": invoice.name},
            fields=["account", "debit", "cost_centre", "business_unit"], limit=20)
        allocations = [x for x in entries if x["account"] == a["expense"].name]
        assert sorted(Decimal(str(x["debit"])) for x in allocations) == [Decimal("480.000000"), Decimal("720.000000")]
        assert any(x["cost_centre"] == a["cost_centre"].name for x in allocations)
        assert any(x["business_unit"] == a["business_unit"].name for x in allocations)
    finally:
        velora.shutdown()


def test_intercompany_shared_cost_posts_due_from_and_creates_auditable_outbox(tmp_path):
    a = setup_cost(tmp_path)
    try:
        with session_as(MAKER):
            invoice = make_invoice(a, is_shared_cost=1, cost_allocations=[{
                "allocation_type": "Intercompany", "target_company": "ENTITY-B", "intercompany_receivable_account": a["due_from"].name, "percentage": 100,
            }]).insert()
            invoice = approve_submit(invoice)
        assert get_account_balance(a["due_from"].name) == Decimal("1200.000000")
        assert get_account_balance(a["expense"].name) == Decimal("0.000000")
        outbox = get_list("Intercompany Cost Allocation", filters={"source_invoice": invoice.name}, fields=["name", "target_company", "amount", "status"], limit=10)
        assert len(outbox) == 1
        assert outbox[0]["target_company"] == "ENTITY-B"
        assert Decimal(str(outbox[0]["amount"])) == Decimal("1200.000000")
        assert outbox[0]["status"] == "Pending Counterparty Posting"
    finally:
        velora.shutdown()


def test_shared_cost_requires_exactly_one_hundred_percent_and_active_targets(tmp_path):
    a = setup_cost(tmp_path)
    try:
        with session_as(MAKER):
            invoice = make_invoice(a, is_shared_cost=1, cost_allocations=[
                {"allocation_type": "Cost Centre", "cost_centre": a["cost_centre"].name, "percentage": 70},
            ])
            with pytest.raises(ValidationError, match="total exactly 100%"):
                invoice.insert()
    finally:
        velora.shutdown()


def test_amortised_shared_cost_splits_local_schedule_and_intercompany_instruction(tmp_path):
    a = setup_cost(tmp_path)
    try:
        with session_as(MAKER):
            invoice = make_invoice(a, is_amortised_cost=1, is_shared_cost=1,
                amortisation_frequency="Monthly", amortisation_start_date=date(date.today().year, 1, 1),
                amortisation_end_date=date(date.today().year, 12, 31), prepayment_account=a["prepaid"].name,
                cost_allocations=[
                    {"allocation_type": "Cost Centre", "cost_centre": a["cost_centre"].name, "percentage": 60},
                    {"allocation_type": "Intercompany", "target_company": "ENTITY-B", "intercompany_receivable_account": a["due_from"].name, "percentage": 40},
                ]).insert()
            invoice = approve_submit(invoice)
        assert get_account_balance(a["prepaid"].name) == Decimal("720.000000")
        assert get_account_balance(a["due_from"].name) == Decimal("480.000000")
        schedules = get_list("Recognition Schedule", filters={"source_doctype": "Purchase Invoice", "source_document": invoice.name}, fields=["name"], limit=10)
        assert len(schedules) == 1
        assert get_doc("Recognition Schedule", schedules[0]["name"]).total_amount == Decimal("720.00")
        instructions = get_list("Intercompany Cost Allocation", filters={"source_invoice": invoice.name}, fields=["amount", "is_amortised_cost", "frequency", "target_company"], limit=10)
        assert len(instructions) == 1
        assert Decimal(str(instructions[0]["amount"])) == Decimal("480.00")
        assert instructions[0]["is_amortised_cost"] == 1
        assert instructions[0]["frequency"] == "Monthly"
    finally:
        velora.shutdown()


def test_purchase_invoice_metadata_has_collapsible_conditional_cost_sections():
    import json
    from pathlib import Path
    from velora.meta.spec import DocType
    definition = json.loads((Path(__file__).parents[1] / "velora_erp" / "finance" / "doctype" / "purchase_invoice" / "purchase_invoice.json").read_text())
    meta = DocType.from_dict(definition, app="velora_erp")
    assert meta.layout is not None
    sections = {section["label"]: section for tab in meta.layout["tabs"] for section in tab["sections"]}
    assert sections["Amortisation Details"]["collapsible"] is True
    assert sections["Shared Cost Allocation"]["collapsible"] is True
    fields = {field.fieldname: field for field in meta.fields}
    assert fields["amortisation_frequency"].depends_on == "eval:doc.is_amortised_cost == 1"
    assert fields["cost_allocations"].depends_on == "eval:doc.is_shared_cost == 1"
    assert fields["amortisation_preview"].read_only is True
