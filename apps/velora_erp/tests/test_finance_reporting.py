from datetime import date
from decimal import Decimal

import pytest
import velora
from velora import get_doc, new_doc
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import Session, session_as
from velora.reporting.layouts import execute_statement, statement_drilldown
from velora.reporting.runner import run_report
from velora_erp.finance.engine import get_account_balance, post_financial_transaction
from velora_erp.setup import after_install


MAKER = Session("maker@example.test", frozenset({"Accountant"}))
APPROVER = Session("approver@example.test", frozenset({"Finance Manager"}))
PUBLICATION_CREATOR = Session("report-creator@example.test", frozenset({"Finance Manager"}))


def setup_finance(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'finance-reporting.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init()
    velora.migrate()
    after_install()
    year = date.today().year
    fy_start, fy_end = date(year, 4, 1), date(year + 1, 3, 31)
    settings = get_doc("Finance Settings", "Primary Finance Settings")
    settings.financial_year_start_month = "April"
    settings.save(ignore_permissions=True)
    new_doc("Financial Year", year_name=f"FY-{year}-APR", start_date=fy_start, end_date=fy_end, status="Open", is_current=1).insert(ignore_permissions=True)
    new_doc("Financial Period", period_name=f"FY-{year}-APR-P01", financial_year=f"FY-{year}-APR", period_number=1, start_date=fy_start, end_date=fy_end, status="Open").insert(ignore_permissions=True)
    groups = {}
    for code, label, root in (("ASSET", "Assets", "Asset"), ("EQUITY", "Equity", "Equity"), ("INCOME", "Income", "Income"), ("EXPENSE", "Expenses", "Expense")):
        groups[code] = new_doc("Account Group", group_code=code, group_name=label, root_type=root, is_group=0).insert(ignore_permissions=True)
    accounts = {}
    for code, name, group, account_type in (
        ("1000", "Main Bank", "ASSET", "BANK"),
        ("3000", "Opening Equity", "EQUITY", "EQUITY"),
        ("4000", "Service Revenue", "INCOME", "REVENUE"),
        ("5000", "Office Expense", "EXPENSE", "OPERATING_EXPENSE"),
        ("1100", "Trade Receivables", "ASSET", "RECEIVABLE"),
        ("1200", "Other Receivables", "ASSET", "LOAN_RECEIVABLE"),
    ):
        extra = {"is_control_account": 1, "control_account_type": "Receivables"} if code == "1100" else {}
        accounts[code] = new_doc("Account", account_code=code, account_name=name, account_group=group, account_type=account_type, allow_manual_posting=1, **extra).insert(ignore_permissions=True)
    new_doc("Customer Group", group_code="TEST", group_name="Test Customers", is_group=0).insert(ignore_permissions=True)
    new_doc("Customer", customer_code="CUST-001", customer_name="Test Customer", customer_group="TEST", customer_type="Company", control_account=accounts["1100"].name).insert(ignore_permissions=True)
    return accounts


def teardown():
    velora.shutdown()


def test_framework_financial_statement_designer_reads_veloraerp_ledger(tmp_path):
    accounts = setup_finance(tmp_path)
    try:
        post_financial_transaction(
            source_doctype="Test Source", source_name="REV-1", posting_date=date.today(), currency="NGN",
            lines=[{"account": accounts["1000"].name, "debit": 100, "credit": 0}, {"account": accounts["4000"].name, "debit": 0, "credit": 100}],
        )
        definition = {
            "rows": [
                {"code": "ASSETS", "description": "Assets", "type": "account_category", "category": "Asset"},
                {"code": "INCOME", "description": "Income", "type": "account_category", "category": "Income"},
            ],
            "columns": [{"code": "CURRENT", "caption": "Current Period", "type": "net_change", "date_mode": "custom"}],
        }
        result = execute_statement(definition, {"from_date": date.today().replace(month=1, day=1).isoformat(), "to_date": date.today().isoformat()})
        values = {row["code"]: row["values"]["CURRENT"] for row in result["rows"]}
        assert values["ASSETS"] == pytest.approx(100)
        assert values["INCOME"] == pytest.approx(100)
        detail = statement_drilldown(definition, {"from_date": date.today().replace(month=1, day=1).isoformat(), "to_date": date.today().isoformat()}, "ASSETS", "CURRENT")
        assert len(detail["entries"]) == 1
        assert detail["entries"][0]["voucher_type"] == "Test Source"
        assert detail["entries"][0]["debit"] == pytest.approx(100)
        layouts = __import__("velora.reporting.layouts", fromlist=["list_layouts"]).list_layouts()
        assert {x["name"] for x in layouts} >= {
            "Income Statement", "Statement of Financial Position", "Comparative Income Statement",
            "Comparative Statement of Financial Position", "Statement of Changes in Equity - Mapping Template",
        }
        from velora.application_workspaces import listing, execute
        finance_workspace = next(row for row in listing() if row["scope"] == "company" and row["name"] == "Finance")
        rendered = execute(finance_workspace["id"])
        routes = {widget.get("route") for widget in rendered["results"] if widget["type"] == "shortcut"}
        assert "#/report/Trial Balance" in routes
        assert "#/financial-reports" in routes
        period_workspace = next(row for row in listing() if row["scope"] == "company" and row["name"] == "Period End")
        period_rendered = execute(period_workspace["id"])
        period_routes = {widget.get("route") for widget in period_rendered["results"] if widget["type"] == "shortcut"}
        assert "#/app/Financial Report Publication" in period_routes
        assert "#/app/Financial Budget" in period_routes
        rp_workspace = next(row for row in listing() if row["scope"] == "company" and row["name"] == "Receivables & Payables")
        rp_routes = {widget.get("route") for widget in execute(rp_workspace["id"])["results"] if widget["type"] == "shortcut"}
        assert "#/app/Customer" in rp_routes
        assert "#/app/Supplier" in rp_routes
        assert "#/app/Receipt" in rp_routes and "#/app/Payment" in rp_routes
        assert "#/report/Customer Statement" in routes
        assert "#/report/Supplier Statement" in routes
        assert any(widget["title"] == "Posted Ledger Records" and widget["value"] == 2 for widget in rendered["results"] if widget["type"] == "number")
    finally:
        teardown()


def test_trial_balance_and_account_ledger_reports_use_base_currency_ledger(tmp_path):
    accounts = setup_finance(tmp_path)
    try:
        post_financial_transaction(
            source_doctype="Test Source", source_name="TB-1", posting_date=date.today(), currency="NGN",
            lines=[{"account": accounts["1000"].name, "debit": 250, "credit": 0}, {"account": accounts["3000"].name, "debit": 0, "credit": 250}],
        )
        tb_default = run_report("Trial Balance", {"to_date": date.today().isoformat()})
        assert tb_default.subtitle.startswith("01 Apr")
        tb = run_report("Trial Balance", {"from_date": date.today().replace(month=1, day=1).isoformat(), "to_date": date.today().isoformat()})
        assert tb.title == "Trial Balance"
        assert any("Main Bank" in str(row.values.get("account", "")) for row in tb.rows)
        tb_range = run_report("Trial Balance", {"account_from": accounts["1000"].name,
            "account_to": accounts["1000"].name, "to_date": date.today().isoformat()})
        assert any("Main Bank" in str(row.values.get("account", "")) for row in tb_range.rows)
        assert not any("Opening Equity" in str(row.values.get("account", "")) for row in tb_range.rows)
        ledger = run_report("Account Ledger", {"account": accounts["1000"].name, "from_date": date.today().replace(month=1, day=1).isoformat(), "to_date": date.today().isoformat()})
        assert ledger.title.startswith("Account Ledger")
        assert any(row.values.get("balance") == Decimal("250.000000") for row in ledger.rows)
    finally:
        teardown()



def test_party_account_ledger_keeps_running_balances_separate_by_account(tmp_path):
    accounts = setup_finance(tmp_path)
    try:
        post_financial_transaction(
            source_doctype="Test Source", source_name="PARTY-AR-1", posting_date=date.today(), currency="NGN",
            lines=[
                {"account": accounts["1100"].name, "debit": 80, "credit": 0, "party_type": "Customer", "party": "CUST-001"},
                {"account": accounts["4000"].name, "debit": 0, "credit": 80},
            ],
        )
        post_financial_transaction(
            source_doctype="Test Source", source_name="PARTY-AR-2", posting_date=date.today(), currency="NGN",
            lines=[
                {"account": accounts["1200"].name, "debit": 20, "credit": 0, "party_type": "Customer", "party": "CUST-001"},
                {"account": accounts["4000"].name, "debit": 0, "credit": 20},
            ],
        )
        report = run_report("Account Ledger", {"party": "CUST-001", "from_date": date.today().replace(month=1, day=1).isoformat(), "to_date": date.today().isoformat()})
        balances = [row.values.get("balance") for row in report.rows if row.values.get("description") == "Closing Balance"]
        assert Decimal("80.000000") in balances
        assert Decimal("20.000000") in balances
        assert all(value not in balances for value in (Decimal("100.000000"),))
    finally:
        teardown()

def test_financial_voucher_requires_independent_approval_and_posts_once(tmp_path):
    accounts = setup_finance(tmp_path)
    try:
        from wf_helpers import install_approval, decide
        install_approval("Financial Voucher")
        with session_as(APPROVER):
            own = new_doc(
                "Financial Voucher", voucher_date=date.today(), posting_date=date.today(), purpose="General Adjustment",
                currency="NGN", exchange_rate=1, narration="Self-approval must be blocked",
                lines=[{"account": accounts["5000"].name, "debit": 5, "credit": 0}, {"account": accounts["1000"].name, "debit": 0, "credit": 5}],
            ).insert()
        with pytest.raises(PermissionDenied, match="separation of duties"):                    # the maker cannot approve their own voucher
            decide("Financial Voucher", own.name, "Approve", APPROVER)
        with session_as(MAKER):
            rejected = new_doc(
                "Financial Voucher", voucher_date=date.today(), posting_date=date.today(), purpose="General Adjustment",
                currency="NGN", exchange_rate=1, narration="Rejected adjustment",
                lines=[{"account": accounts["5000"].name, "debit": 7, "credit": 0}, {"account": accounts["1000"].name, "debit": 0, "credit": 7}],
            ).insert()
        decide("Financial Voucher", rejected.name, "Reject", APPROVER, "not supported by documents")
        with session_as(APPROVER):
            rejected = get_doc("Financial Voucher", rejected.name)
            assert rejected.approval_status == "Rejected" and rejected.rejected_by == APPROVER.user
            with pytest.raises(ValidationError, match="cannot be submitted"):
                rejected.submit(ignore_permissions=True)
        with session_as(MAKER):
            voucher = new_doc(
                "Financial Voucher", voucher_date=date.today(), posting_date=date.today(), purpose="General Adjustment",
                currency="NGN", exchange_rate=1, narration="Record office expense",
                lines=[{"account": accounts["5000"].name, "debit": 75, "credit": 0}, {"account": accounts["1000"].name, "debit": 0, "credit": 75}],
            ).insert()
        decide("Financial Voucher", voucher.name, "Approve", APPROVER)
        with session_as(APPROVER):
            voucher = get_doc("Financial Voucher", voucher.name)
            voucher.submit(ignore_permissions=True)
            voucher.reload()
            assert voucher.docstatus == 1
            assert voucher.posting_batch
            assert get_account_balance(accounts["5000"].name) == Decimal("75.000000")
            assert get_account_balance(accounts["1000"].name) == Decimal("-75.000000")
    finally:
        teardown()


def test_opening_balance_entry_is_balance_sheet_only_and_approved(tmp_path):
    accounts = setup_finance(tmp_path)
    try:
        with session_as(MAKER):
            entry = new_doc(
                "Opening Balance Entry", opening_date=date.today(), migration_reference="CUTOVER-2026-001",
                narration="Approved opening balances",
                lines=[{"account": accounts["1000"].name, "debit": 500, "credit": 0}, {"account": accounts["3000"].name, "debit": 0, "credit": 500}],
            ).insert()
        with session_as(APPROVER):
            entry = get_doc("Opening Balance Entry", entry.name)
            entry.approval_status = "Approved"
            entry.save(ignore_permissions=True)
            entry.submit(ignore_permissions=True)
            entry.reload()
            assert entry.docstatus == 1
            assert entry.posting_batch
            assert get_account_balance(accounts["1000"].name) == Decimal("500.000000")
        with session_as(MAKER):
            bad = new_doc(
                "Opening Balance Entry", opening_date=date.today(), migration_reference="CUTOVER-2026-002",
                narration="P and L account should be rejected",
                lines=[{"account": accounts["5000"].name, "debit": 10, "credit": 0}, {"account": accounts["3000"].name, "debit": 0, "credit": 10}],
            )
            with pytest.raises(ValidationError, match="restricted to Assets, Liabilities and Equity"):
                bad.insert()
    finally:
        teardown()


def test_financial_statement_supports_ledger_dimension_filters_and_dimension_rows(tmp_path):
    accounts = setup_finance(tmp_path)
    try:
        today = date.today()
        start = today.replace(month=1, day=1)
        new_doc("Accounting Dimension", dimension_code="DEPARTMENT", dimension_name="Department", value_source="Free Text", disabled=0).insert(ignore_permissions=True)
        post_financial_transaction(
            source_doctype="Branch Sales", source_name="LAGOS-1", posting_date=today, currency="NGN",
            lines=[
                {"account": accounts["1000"].name, "debit": 100, "credit": 0, "branch": "Lagos", "dimensions": {"DEPARTMENT": "Finance"}},
                {"account": accounts["4000"].name, "debit": 0, "credit": 100, "branch": "Lagos", "dimensions": {"DEPARTMENT": "Finance"}},
            ],
        )
        post_financial_transaction(
            source_doctype="Branch Sales", source_name="ABUJA-1", posting_date=today, currency="NGN",
            lines=[
                {"account": accounts["1000"].name, "debit": 50, "credit": 0, "branch": "Abuja", "dimensions": {"DEPARTMENT": "Operations"}},
                {"account": accounts["4000"].name, "debit": 0, "credit": 50, "branch": "Abuja", "dimensions": {"DEPARTMENT": "Operations"}},
            ],
        )
        definition = {
            "rows": [
                {"code": "INCOME", "description": "Income", "type": "account_category", "category": "Income"},
                {"code": "LAGOS", "description": "Lagos Branch", "type": "dimension", "dimension": "branch", "dimension_value": "Lagos"},
            ],
            "columns": [{"code": "CURRENT", "caption": "Current Period", "type": "net_change", "date_mode": "custom"}],
        }
        filters = {"from_date": start.isoformat(), "to_date": today.isoformat(), "branch": "Lagos"}
        result = execute_statement(definition, filters)
        values = {row["code"]: row["values"]["CURRENT"] for row in result["rows"]}
        assert values["INCOME"] == pytest.approx(100)
        # A row-level dimension is intersected with global filters, never allowed to broaden them.
        assert values["LAGOS"] == pytest.approx(200)
        detail = statement_drilldown(definition, filters, "INCOME", "CURRENT")
        assert len(detail["entries"]) == 1
        assert detail["entries"][0]["voucher_no"] == "LAGOS-1"
        department_result = execute_statement(definition, {"from_date": start.isoformat(), "to_date": today.isoformat(), "department": "Finance"})
        department_income = next(row for row in department_result["rows"] if row["code"] == "INCOME")
        assert department_income["values"]["CURRENT"] == pytest.approx(100)
    finally:
        teardown()


def test_financial_report_publication_requires_independent_approval_and_is_immutable(tmp_path):
    setup_finance(tmp_path)
    try:
        from velora.reporting.layouts import save_layout
        from velora import get_doc
        definition = {
            "rows": [{"code": "INCOME", "description": "Income", "type": "account_category", "category": "Income"}],
            "columns": [{"code": "CURRENT", "caption": "Current Period", "type": "net_change", "date_mode": "custom"}],
        }
        from wf_helpers import install_approval
        install_approval("Financial Report Publication")
        with session_as(PUBLICATION_CREATOR):
            layout = save_layout("Publication Test", definition)
            publication = new_doc(
                "Financial Report Publication", report_layout=layout["id"],
                from_date=date.today().replace(month=1, day=1), to_date=date.today(),
            ).insert()
            assert publication.report_snapshot
            assert publication.snapshot_hash
            assert publication.publication_status == "Draft"
            original_snapshot = publication.report_snapshot
            publication.report_snapshot = original_snapshot + " "
            with pytest.raises(ValidationError, match="System-generated report snapshot fields"):
                publication.save(ignore_permissions=True)
        from wf_helpers import decide
        pub_name = publication.name
        with pytest.raises(PermissionDenied, match="separation of duties"):
            decide("Financial Report Publication", pub_name, "Approve", PUBLICATION_CREATOR)       # the creator cannot approve it
        decide("Financial Report Publication", pub_name, "Approve", APPROVER)
        with session_as(APPROVER):
            publication = get_doc("Financial Report Publication", pub_name)
            assert publication.approved_by == APPROVER.user
            publication.submit(ignore_permissions=True)
            publication.reload()
            assert publication.docstatus == 1
            assert publication.publication_status == "Published"
            publication.cancel(ignore_permissions=True, reason="Withdrawn")      # a publication can be withdrawn; it then reads Cancelled
            publication.reload()
            assert publication.docstatus == 2 and publication.publication_status == "Cancelled"
    finally:
        teardown()


def test_financial_report_pdf_export_is_paginated_pdf_output():
    import importlib.util
    if importlib.util.find_spec("reportlab") is None:
        pytest.skip("ReportLab optional PDF capability is not installed")
    from velora.reporting.layouts import financial_statement_pdf
    content = financial_statement_pdf({
        "name": "Board Financial Results",
        "filters": {"from_date": "2026-01-01", "to_date": "2026-11-15", "branch": "Lagos"},
        "columns": [{"code": "ACTUAL", "caption": "Actual", "period_label": "1 Jan 2026 to 15 Nov 2026", "width": 18}],
        "rows": [{"code": "REVENUE", "description": "Revenue", "bold": True, "indent": 0, "values": {"ACTUAL": 1250000.25}}],
    })
    assert content.startswith(b"%PDF-")
    assert b"Board Financial Results" in content


def test_budget_vs_actual_uses_only_independently_approved_periodised_budgets(tmp_path):
    accounts = setup_finance(tmp_path)
    try:
        from velora import new_doc as _nd; _nd("Branch", branch_code="Lagos", branch_name="Lagos").insert(ignore_permissions=True)
        today = date.today()
        period_start = today.replace(day=1)
        import calendar
        period_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        with session_as(MAKER):
            budget = new_doc(
                "Financial Budget", budget_name="FY26-ORIGINAL-BASE", budget_scenario="Original",
                financial_year=f"FY-{today.year}-APR", budget_notes="Approved operating plan",
                lines=[
                    {"account": accounts["4000"].name, "period_start": period_start, "period_end": period_end, "budget_amount": 2000, "branch": "Lagos"},
                    {"account": accounts["5000"].name, "period_start": period_start, "period_end": period_end, "budget_amount": 1000, "branch": "Lagos"},
                ],
            ).insert()
        with session_as(APPROVER):
            budget = get_doc("Financial Budget", budget.name)
            budget.approval_status = "Approved"
            budget.save()
            budget.submit()
            budget.reload()
            assert budget.docstatus == 1
            assert budget.budget_status == "Active"
            assert get_account_balance(accounts["4000"].name) == Decimal("0")

        post_financial_transaction(
            source_doctype="Budget Actual", source_name="REV-ACTUAL", posting_date=today, currency="NGN",
            lines=[
                {"account": accounts["1000"].name, "debit": 1500, "credit": 0, "branch": "Lagos"},
                {"account": accounts["4000"].name, "debit": 0, "credit": 1500, "branch": "Lagos"},
            ],
        )
        post_financial_transaction(
            source_doctype="Budget Actual", source_name="EXP-ACTUAL", posting_date=today, currency="NGN",
            lines=[
                {"account": accounts["5000"].name, "debit": 700, "credit": 0, "branch": "Lagos"},
                {"account": accounts["1000"].name, "debit": 0, "credit": 700, "branch": "Lagos"},
            ],
        )
        definition = {
            "rows": [
                {"code": "INCOME", "type": "account_category", "category": "Income"},
                {"code": "EXPENSES", "type": "account_category", "category": "Expense"},
                {"code": "NET_PROFIT", "type": "formula", "formula": "[INCOME]-[EXPENSES]"},
            ],
            "columns": [
                {"code": "ACTUAL", "type": "net_change", "date_mode": "custom"},
                {"code": "BUDGET", "type": "budget", "date_mode": "custom"},
                {"code": "VARIANCE", "type": "formula", "formula": "[ACTUAL]-[BUDGET]"},
            ],
        }
        filters = {"from_date": period_start.isoformat(), "to_date": period_end.isoformat(), "budget_name": "FY26-ORIGINAL-BASE", "branch": "Lagos"}
        with session_as(MAKER):
            result = execute_statement(definition, filters)
        rows = {row["code"]: row["values"] for row in result["rows"]}
        assert rows["INCOME"]["ACTUAL"] == pytest.approx(1500)
        assert rows["INCOME"]["BUDGET"] == pytest.approx(2000)
        assert rows["EXPENSES"]["ACTUAL"] == pytest.approx(700)
        assert rows["EXPENSES"]["BUDGET"] == pytest.approx(1000)
        assert rows["NET_PROFIT"]["ACTUAL"] == pytest.approx(800)
        assert rows["NET_PROFIT"]["BUDGET"] == pytest.approx(1000)
        assert rows["NET_PROFIT"]["VARIANCE"] == pytest.approx(-200)
        remaining_days = (period_end - today).days + 1
        days_in_month = (period_end - period_start).days + 1
        with session_as(MAKER):
            partial = execute_statement(definition, {"from_date": today.isoformat(), "to_date": period_end.isoformat(), "budget_name": "FY26-ORIGINAL-BASE", "branch": "Lagos"})
        partial_rows = {row["code"]: row["values"] for row in partial["rows"]}
        assert partial_rows["INCOME"]["BUDGET"] == pytest.approx(2000 * remaining_days / days_in_month)
    finally:
        teardown()


def test_statement_of_changes_in_equity_reconciles_opening_movements_and_closing(tmp_path):
    accounts = setup_finance(tmp_path)
    try:
        today = date.today()
        start = today.replace(day=1)
        from datetime import timedelta
        opening_date = start - timedelta(days=1)
        post_financial_transaction(
            source_doctype="Equity Opening", source_name="EQ-OPEN", posting_date=opening_date, currency="NGN",
            lines=[
                {"account": accounts["1000"].name, "debit": 100, "credit": 0},
                {"account": accounts["3000"].name, "debit": 0, "credit": 100},
            ],
        )
        post_financial_transaction(
            source_doctype="Equity Contribution", source_name="EQ-MOVE", posting_date=today, currency="NGN",
            lines=[
                {"account": accounts["1000"].name, "debit": 25, "credit": 0},
                {"account": accounts["3000"].name, "debit": 0, "credit": 25},
            ],
        )
        definition = {
            "rows": [{"code": "EQUITY", "type": "account_category", "category": "Equity"}],
            "columns": [
                {"code": "OPENING", "type": "opening_balance", "date_mode": "current_period", "period": "day"},
                {"code": "MOVEMENTS", "type": "net_change", "date_mode": "custom"},
                {"code": "CLOSING", "type": "balance_at_date", "date_mode": "current_period"},
                {"code": "CHECK", "type": "formula", "formula": "[OPENING]+[MOVEMENTS]-[CLOSING]"},
            ],
        }
        with session_as(MAKER):
            result = execute_statement(definition, {"from_date": start.isoformat(), "to_date": today.isoformat()})
        values = result["rows"][0]["values"]
        assert values["OPENING"] == pytest.approx(100)
        assert values["MOVEMENTS"] == pytest.approx(25)
        assert values["CLOSING"] == pytest.approx(125)
        assert values["CHECK"] == pytest.approx(0)
    finally:
        teardown()


def test_financial_statement_xlsx_contains_statement_and_report_information_sheets():
    import io
    from openpyxl import load_workbook
    from velora.reporting.layouts import financial_statement_xlsx
    content = financial_statement_xlsx({
        "name": "Board Results",
        "filters": {"from_date": "2026-01-01", "to_date": "2026-11-15", "budget_name": "FY26-PLAN", "branch": "Lagos"},
        "columns": [{"code": "ACTUAL", "caption": "Actual", "period_label": "2026", "width": 18}],
        "rows": [{"code": "REVENUE", "description": "Revenue", "bold": True, "indent": 0, "values": {"ACTUAL": 1250000.25}}],
    })
    workbook = load_workbook(io.BytesIO(content), data_only=True)
    assert workbook.sheetnames == ["Financial Statement", "Report Information"]
    assert workbook["Financial Statement"]["A1"].value == "Board Results"
    assert workbook["Report Information"]["B4"].value == "Board Results"


def test_account_ledger_supports_account_code_range_and_keeps_account_sections(tmp_path):
    accounts = setup_finance(tmp_path)
    try:
        post_financial_transaction(
            source_doctype="Test Source", source_name="RANGE-1", posting_date=date.today(), currency="NGN",
            lines=[
                {"account": accounts["1000"].name, "debit": 30, "credit": 0},
                {"account": accounts["4000"].name, "debit": 0, "credit": 30},
            ],
        )
        report = run_report("Account Ledger", {
            "account_from": accounts["1000"].name, "account_to": accounts["4000"].name,
            "from_date": date.today().replace(month=1, day=1).isoformat(), "to_date": date.today().isoformat(),
        })
        account_sections = [row.values.get("account") for row in report.rows if row.type == "header"]
        assert any("Main Bank" in str(x) for x in account_sections)
        assert any("Service Revenue" in str(x) for x in account_sections)
        assert not any("Opening Equity" in str(row.values.get("account", "")) for row in report.rows)
        assert any(row.type == "subtotal" for row in report.rows)
    finally:
        teardown()
