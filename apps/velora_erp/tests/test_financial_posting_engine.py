from datetime import date
from decimal import Decimal

import pytest

import velora
from velora import db, get_doc, new_doc
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora_erp.finance.engine import (
    get_account_activity,
    get_account_balance,
    post_financial_transaction,
)
from velora_erp.setup import after_install


def _setup_company(tmp_path):
    db_path = tmp_path / "veloraerp-posting.db"
    velora.configure(db_url=f"sqlite:///{db_path}", apps=["velora_erp"], developer_mode=True)
    velora.init()
    velora.migrate()
    after_install()
    year = date.today().year
    new_doc(
        "Financial Year", year_name=f"FY-{year}", start_date=date(year, 1, 1),
        end_date=date(year, 12, 31), status="Open", is_current=1,
    ).insert(ignore_permissions=True)
    new_doc(
        "Financial Period", period_name=f"FY-{year}-OPEN", financial_year=f"FY-{year}",
        period_number=1, start_date=date(year, 1, 1), end_date=date(year, 12, 31), status="Open",
    ).insert(ignore_permissions=True)
    new_doc("Account Group", group_code="ASSET", group_name="Assets", root_type="Asset", is_group=0).insert(ignore_permissions=True)
    new_doc("Account Group", group_code="EQUITY", group_name="Equity", root_type="Equity", is_group=0).insert(ignore_permissions=True)
    bank = new_doc(
        "Account", account_code="1000", account_name="Main Bank", account_group="ASSET",
        account_type="BANK", is_control_account=1, control_account_type="Bank",
    ).insert(ignore_permissions=True)
    equity = new_doc(
        "Account", account_code="3000", account_name="Opening Equity", account_group="EQUITY",
        account_type="EQUITY",
    ).insert(ignore_permissions=True)
    return bank, equity


def test_posting_engine_posts_balanced_immutable_ledger_and_is_idempotent(tmp_path):
    bank, equity = _setup_company(tmp_path)
    try:
        payload = dict(
            source_doctype="Test Source", source_name="SOURCE-001", posting_date=date.today(),
            currency="NGN", lines=[
                {"account": bank.name, "debit": "1000.00", "credit": "0"},
                {"account": equity.name, "debit": "0", "credit": "1000.00"},
            ],
        )
        draft = new_doc(
            "Financial Posting Batch", source_doctype=payload["source_doctype"],
            source_name=payload["source_name"], posting_date=payload["posting_date"],
            currency=payload["currency"], lines=payload["lines"],
        ).insert(ignore_permissions=True)
        assert draft.posting_status == "Draft"
        batch = post_financial_transaction(**payload)
        assert batch.name == draft.name
        assert batch.docstatus == 1
        assert batch.posting_status == "Posted"
        assert batch.total_debit == Decimal("1000.00")
        assert batch.total_base_credit == Decimal("1000.00")
        assert get_account_balance(bank.name) == Decimal("1000.000000")
        assert get_account_balance(equity.name) == Decimal("-1000.000000")
        assert len(get_account_activity(bank.name)) == 1

        repeated = post_financial_transaction(**payload)
        assert repeated.name == batch.name

        changed = dict(payload)
        changed["lines"] = [
            {"account": bank.name, "debit": "1200.00", "credit": "0"},
            {"account": equity.name, "debit": "0", "credit": "1200.00"},
        ]
        with pytest.raises(ValidationError, match="different financial content"):
            post_financial_transaction(**changed)

        ledger_rows = get_account_activity(bank.name)
        ledger_doc = get_doc("Account Ledger Record", ledger_rows[0]["name"], ignore_permissions=True)
        with pytest.raises(ValidationError, match="immutable"):
            ledger_doc.save(ignore_permissions=True)
        with pytest.raises(ValidationError, match="cannot be deleted"):
            ledger_doc.delete(ignore_permissions=True)
        with pytest.raises(ValidationError, match="only be created by the Financial Posting Engine"):
            new_doc("Account Ledger Record", entry_key="UNAUTHORISED", posting_batch=batch.name).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_unbalanced_batch_is_rejected_before_any_ledger_rows_are_written(tmp_path):
    bank, equity = _setup_company(tmp_path)
    try:
        with pytest.raises(ValidationError, match="must balance"):
            post_financial_transaction(
                source_doctype="Test Source", source_name="UNBALANCED-001", posting_date=date.today(),
                currency="NGN", lines=[
                    {"account": bank.name, "debit": "100", "credit": "0"},
                    {"account": equity.name, "debit": "0", "credit": "90"},
                ],
            )
        assert get_account_balance(bank.name) == Decimal("0")
    finally:
        velora.shutdown()



def test_foreign_currency_conversion_and_mandatory_dimensions(tmp_path):
    bank, equity = _setup_company(tmp_path)
    try:
        new_doc(
            "Accounting Dimension", dimension_code="REGION", dimension_name="Region",
            value_source="Dimension Values", mandatory_on_posting=1,
        ).insert(ignore_permissions=True)
        new_doc(
            "Dimension Value", dimension="REGION", value_code="NORTH", value_name="Northern Region",
            is_group=0,
        ).insert(ignore_permissions=True)
        base = dict(
            source_doctype="Test Source", source_name="FX-001", posting_date=date.today(),
            currency="USD", exchange_rate="1500", lines=[
                {"account": bank.name, "debit": "10", "credit": "0", "dimensions": {"REGION": "NORTH"}},
                {"account": equity.name, "debit": "0", "credit": "10", "dimensions": {"REGION": "NORTH"}},
            ],
        )
        with pytest.raises(ValidationError, match="mandatory"):
            missing = dict(base)
            missing["lines"] = [{"account": bank.name, "debit": "10", "credit": "0"}, {"account": equity.name, "debit": "0", "credit": "10"}]
            post_financial_transaction(**missing)
        batch = post_financial_transaction(**base)
        assert batch.total_base_debit == Decimal("15000.00")
        assert get_account_balance(bank.name) == Decimal("15000.000000")
    finally:
        velora.shutdown()


def test_party_tracking_and_closed_period_controls(tmp_path):
    bank, equity = _setup_company(tmp_path)
    try:
        receivable = new_doc(
            "Account", account_code="1100", account_name="Trade Receivables",
            account_group="ASSET", account_type="RECEIVABLE",
            is_control_account=1, control_account_type="Receivables",
        ).insert(ignore_permissions=True)
        with pytest.raises(ValidationError, match="requires both Party Type and Party"):
            post_financial_transaction(
                source_doctype="Test Source", source_name="AR-MISSING-PARTY", posting_date=date.today(),
                currency="NGN", lines=[
                    {"account": receivable.name, "debit": "50", "credit": "0"},
                    {"account": equity.name, "debit": "0", "credit": "50"},
                ],
            )
        new_doc("Customer Group", group_code="RETAIL", group_name="Retail Customers", is_group=0).insert(ignore_permissions=True)
        customer = new_doc(
            "Customer", customer_code="CUST-001", customer_name="Test Customer",
            customer_group="RETAIL", customer_type="Company", control_account=receivable.name,
        ).insert(ignore_permissions=True)
        valid = post_financial_transaction(
            source_doctype="Test Source", source_name="AR-WITH-PARTY", posting_date=date.today(),
            currency="NGN", lines=[
                {"account": receivable.name, "debit": "50", "credit": "0", "party_type": "Customer", "party": customer.name},
                {"account": equity.name, "debit": "0", "credit": "50"},
            ],
        )
        assert valid.docstatus == 1
        assert get_account_balance(receivable.name, party_type="Customer", party=customer.name) == Decimal("50.000000")
        with pytest.raises(ValidationError, match="does not exist"):
            post_financial_transaction(
                source_doctype="Test Source", source_name="AR-UNKNOWN-PARTY", posting_date=date.today(),
                currency="NGN", lines=[
                    {"account": receivable.name, "debit": "10", "credit": "0", "party_type": "Customer", "party": "UNKNOWN-CUSTOMER"},
                    {"account": equity.name, "debit": "0", "credit": "10"},
                ],
            )

        from velora_erp.finance.doctype.financial_period_close.financial_period_close import CHECKLIST
        maker = Session("period-close-maker@example.test", frozenset({"Accountant"}))
        approver = Session("period-close-approver@example.test", frozenset({"Finance Manager"}))
        with session_as(maker):
            close = new_doc(
                "Financial Period Close",
                financial_period=f"FY-{date.today().year}-OPEN",
                close_date=date(date.today().year, 12, 31),
                checklist=[{"item_code": code, "description": label, "completed": 1,
                            "evidence_reference": f"REF-{code}", "reviewer_notes": "Reviewed"}
                           for code, label in CHECKLIST],
            ).insert()
        with session_as(approver):
            close = get_doc("Financial Period Close", close.name, ignore_permissions=True)
            close.approval_status = "Approved"
            close.save()
        # Submission is a separate duty from approval under v1.4 SoD controls.
        with session_as(Session("period-close-poster@example.test", frozenset({"Finance Operations"}))):
            close = get_doc("Financial Period Close", close.name, ignore_permissions=True)
            close.submit(ignore_permissions=True)
        with pytest.raises(ValidationError, match="is not open for posting"):
            post_financial_transaction(
                source_doctype="Test Source", source_name="CLOSED-PERIOD", posting_date=date.today(),
                currency="NGN", lines=[
                    {"account": bank.name, "debit": "10", "credit": "0"},
                    {"account": equity.name, "debit": "0", "credit": "10"},
                ],
            )
    finally:
        velora.shutdown()


def test_per_line_currency_rounding_mismatch_is_not_silently_posted(tmp_path):
    bank, equity = _setup_company(tmp_path)
    try:
        expense_group = new_doc(
            "Account Group", group_code="EXPENSE", group_name="Expenses", root_type="Expense", is_group=0,
        ).insert(ignore_permissions=True)
        expense = new_doc(
            "Account", account_code="6000", account_name="Minor Expense", account_group=expense_group.name,
            account_type="OPERATING_EXPENSE",
        ).insert(ignore_permissions=True)
        with pytest.raises(ValidationError, match="Base currency debits"):
            post_financial_transaction(
                source_doctype="Test Source", source_name="FX-ROUNDING", posting_date=date.today(),
                currency="USD", exchange_rate="1.2345", lines=[
                    {"account": bank.name, "debit": "0.01", "credit": "0"},
                    {"account": expense.name, "debit": "0.02", "credit": "0"},
                    {"account": equity.name, "debit": "0", "credit": "0.03"},
                ],
            )
        assert get_account_balance(bank.name) == Decimal("0")
    finally:
        velora.shutdown()


def test_batch_and_ledger_write_roll_back_together_on_ledger_failure(tmp_path, monkeypatch):
    bank, equity = _setup_company(tmp_path)
    try:
        draft = new_doc(
            "Financial Posting Batch", source_doctype="Test Source", source_name="ATOMIC-001",
            posting_date=date.today(), currency="NGN", lines=[
                {"account": bank.name, "debit": "75", "credit": "0"},
                {"account": equity.name, "debit": "0", "credit": "75"},
            ],
        ).insert(ignore_permissions=True)
        from velora_erp.finance.doctype.financial_posting_batch import financial_posting_batch as batch_controller

        def fail_after_start(_batch):
            raise ValidationError("Simulated ledger persistence failure")

        monkeypatch.setattr(batch_controller, "_write_ledger", fail_after_start)
        with pytest.raises(ValidationError, match="Simulated ledger persistence failure"):
            draft.submit(ignore_permissions=True)
        persisted = get_doc("Financial Posting Batch", draft.name, ignore_permissions=True)
        assert persisted.docstatus == 0
        assert persisted.posting_status == "Draft"
        assert get_account_balance(bank.name) == Decimal("0")
        assert get_account_activity(bank.name) == []
    finally:
        velora.shutdown()


def test_source_adapter_contract_posts_only_through_shared_engine(tmp_path):
    from dataclasses import dataclass
    from velora_erp.finance.adapters import PostingInstruction, PostingLine, post_source_document
    from sqlalchemy import select
    from velora.db.tables import get_table

    bank, equity = _setup_company(tmp_path)
    try:
        @dataclass
        class SubmittedSource:
            doctype: str = "External Sales Invoice"
            name: str = "SI-ADAPTER-001"
            docstatus: int = 1

        class SalesInvoiceAdapter:
            def build_posting(self, source):
                assert source.name == "SI-ADAPTER-001"
                return PostingInstruction(
                    posting_date=date.today(),
                    currency="NGN",
                    idempotency_key=f"sales-invoice:{source.name}:original",
                    lines=(
                        PostingLine(
                            account=bank.name, debit="1250.00",
                            transaction_date=date.today(), external_reference="BANK-REF-778",
                            tax_code="VAT-STD", tax_rate="7.5", taxable_amount="1000", tax_amount="75",
                            base_taxable_amount="1000", base_tax_amount="75",
                            tax_jurisdiction="NG", branch="LAGOS",
                        ),
                        PostingLine(account=equity.name, credit="1250.00"),
                    ),
                )

        source = SubmittedSource()
        batch = post_source_document(source, SalesInvoiceAdapter())
        assert batch.docstatus == 1
        assert batch.source_doctype == source.doctype
        assert batch.source_name == source.name
        assert batch.idempotency_key == "sales-invoice:SI-ADAPTER-001:original"
        assert get_account_balance(bank.name) == Decimal("1250.000000")
        ledger = get_table("Account Ledger Record")
        with db.transaction() as conn:
            detail = conn.execute(select(ledger).where(ledger.c.source_name == source.name, ledger.c.account == bank.name)).mappings().one()
        assert detail["external_reference"] == "BANK-REF-778"
        assert detail["tax_code"] == "VAT-STD"
        assert Decimal(str(detail["tax_amount"])) == Decimal("75")
        assert Decimal(str(detail["base_tax_amount"])) == Decimal("75")
        assert Decimal(str(detail["base_taxable_amount"])) == Decimal("1000")
        assert detail["tax_jurisdiction"] == "NG"
        assert detail["branch"] == "LAGOS"
        assert detail["account_code_snapshot"] == "1000"

        repeated = post_source_document(source, SalesInvoiceAdapter())
        assert repeated.name == batch.name
        assert get_account_balance(bank.name) == Decimal("1250.000000")

        class ChangedSourceDetailAdapter(SalesInvoiceAdapter):
            def build_posting(self, source):
                instruction = super().build_posting(source)
                lines = list(instruction.lines)
                lines[0] = PostingLine(
                    account=bank.name, debit="1250.00", transaction_date=date.today(),
                    external_reference="DIFFERENT-REFERENCE", tax_code="VAT-STD", tax_rate="7.5",
                    taxable_amount="1000", tax_amount="75", base_taxable_amount="1000",
                    base_tax_amount="75", tax_jurisdiction="NG", branch="LAGOS",
                )
                return PostingInstruction(
                    posting_date=instruction.posting_date, currency=instruction.currency,
                    idempotency_key=instruction.idempotency_key, lines=tuple(lines),
                )

        with pytest.raises(ValidationError, match="different financial content"):
            post_source_document(source, ChangedSourceDetailAdapter())
    finally:
        velora.shutdown()


def test_source_adapter_contract_rejects_unsubmitted_source_and_missing_key(tmp_path):
    from dataclasses import dataclass
    from velora_erp.finance.adapters import PostingInstruction, PostingLine, post_source_document

    _setup_company(tmp_path)
    try:
        @dataclass
        class Source:
            doctype: str = "External Sales Invoice"
            name: str = "SI-ADAPTER-002"
            docstatus: int = 0

        class Adapter:
            def build_posting(self, source):
                return PostingInstruction(
                    posting_date=date.today(), currency="NGN", idempotency_key="",
                    lines=(PostingLine(account="A", debit="1"), PostingLine(account="B", credit="1")),
                )

        with pytest.raises(ValidationError, match="must be submitted"):
            post_source_document(Source(), Adapter())

        submitted = Source(docstatus=1)
        with pytest.raises(ValidationError, match="stable, non-empty idempotency key"):
            post_source_document(submitted, Adapter())
    finally:
        velora.shutdown()
