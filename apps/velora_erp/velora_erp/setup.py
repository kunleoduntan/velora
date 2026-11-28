"""Install-time defaults for a new company database."""
import os
from velora import get_list, new_doc


DEFAULT_ACCOUNT_TYPES = [
    ("BANK", "Bank", "Asset", "Debit", 0, 1, 1),
    ("CASH", "Cash", "Asset", "Debit", 0, 1, 1),
    ("RECEIVABLE", "Receivable", "Asset", "Debit", 1, 1, 1),
    ("INVENTORY", "Inventory", "Asset", "Debit", 0, 1, 1),
    ("FIXED_ASSET", "Fixed Asset", "Asset", "Debit", 0, 1, 1),
    ("ACCUM_DEPRECIATION", "Accumulated Depreciation", "Asset", "Credit", 0, 0, 0),
    ("LOSS_ALLOWANCE", "Loss Allowance (expected credit loss)", "Asset", "Credit", 0, 0, 0),
    ("INTANGIBLE_ASSET", "Intangible Asset", "Asset", "Debit", 0, 1, 1),
    ("ACCUM_AMORTISATION", "Accumulated Amortisation", "Asset", "Credit", 0, 0, 0),
    ("PROVISION", "Provision (IAS 37)", "Liability", "Credit", 0, 0, 0),
    ("PREPAYMENT", "Prepayment", "Asset", "Debit", 0, 0, 1),
    ("LOAN_RECEIVABLE", "Loan Receivable", "Asset", "Debit", 1, 0, 1),
    ("PAYABLE", "Payable", "Liability", "Credit", 1, 1, 1),
    ("BORROWING", "Borrowing", "Liability", "Credit", 0, 0, 1),
    ("TAX_PAYABLE", "Tax Payable", "Liability", "Credit", 0, 1, 1),
    ("WITHHOLDING_TAX", "Withholding Tax", "Liability", "Credit", 0, 1, 1),
    ("ACCRUAL", "Accrual", "Liability", "Credit", 0, 0, 1),
    ("PAYROLL_PAYABLE", "Payroll Payable", "Liability", "Credit", 1, 1, 1),
    ("REVENUE", "Revenue", "Income", "Credit", 0, 0, 0),
    ("OTHER_INCOME", "Other Income", "Income", "Credit", 0, 0, 0),
    ("COST_OF_SALES", "Cost of Sales", "Expense", "Debit", 0, 0, 0),
    ("OPERATING_EXPENSE", "Operating Expense", "Expense", "Debit", 0, 0, 0),
    ("FINANCE_COST", "Finance Cost", "Expense", "Debit", 0, 0, 0),
    ("EQUITY", "Equity", "Equity", "Credit", 0, 0, 0),
    ("RETAINED_EARNINGS", "Retained Earnings", "Equity", "Credit", 0, 0, 0),
    ("CLEARING", "Clearing", "Asset", "Debit", 0, 1, 1),
    ("SUSPENSE", "Suspense", "Asset", "Debit", 0, 0, 1),
    ("SUPPLIER_ADVANCE", "Supplier Advance", "Asset", "Debit", 1, 0, 1),
    ("INTERCOMPANY_RECEIVABLE", "Intercompany Receivable", "Asset", "Debit", 0, 0, 1),
    ("CUSTOMER_ADVANCE", "Customer Advance", "Liability", "Credit", 1, 0, 1),
    ("CONTRA_REVENUE", "Contra Revenue", "Income", "Debit", 0, 0, 0),
    ("CONTRA_EXPENSE", "Contra Expense", "Expense", "Credit", 0, 0, 0),
    ("INVESTMENT", "Investment", "Asset", "Debit", 0, 0, 1),
    ("ACCRUED_INCOME", "Accrued Income", "Asset", "Debit", 0, 0, 1),
    ("TAX_RECEIVABLE", "Tax Receivable", "Asset", "Debit", 0, 0, 1),
    ("DEFERRED_INCOME", "Deferred Income", "Liability", "Credit", 0, 0, 1),
]


WORKSPACE_WIDGET_LIMIT = 30      # velora.application_workspaces refuses more than this per workspace


def _save_fitted(payload, scope="company"):
    """Save a workspace; if it holds more widgets than the framework allows, put the overflow in "<name> (More)".

    v2.70.0 assembled some workspaces with up to 50 widgets, which the framework rejects, so ERP installation
    failed. Nothing is dropped: the overflow lands in a companion workspace with the same visibility and roles.
    """
    from velora.application_workspaces import listing, save
    widgets = list(payload.get("widgets") or [])
    if len(widgets) <= WORKSPACE_WIDGET_LIMIT:
        return save(payload, scope)
    head, tail = widgets[:WORKSPACE_WIDGET_LIMIT], widgets[WORKSPACE_WIDGET_LIMIT:]
    more_name = f"{payload['name']} (More)"[:140]
    current = next((row for row in listing() if row.get("scope") == scope and row.get("name") == more_name), None)
    more_widgets = list((current or {}).get("layout") or [])
    seen = {w.get("title") for w in more_widgets}
    more_widgets.extend(w for w in tail if w.get("title") not in seen)
    save({"id": (current or {}).get("id"), "name": more_name,
          "description": f"More shortcuts for {payload['name']}.", "visibility": payload.get("visibility", "company"),
          "roles": payload.get("roles") or [], "widgets": more_widgets[:WORKSPACE_WIDGET_LIMIT]}, scope)
    return save({**payload, "widgets": head}, scope)


def ensure_currencies():
    from velora_erp.finance.currencies import ensure_currencies as _seed
    return _seed()


def ensure_transaction_types():
    from velora_erp.finance.currencies import ensure_transaction_types as _seed
    return _seed()


def ensure_account_types():
    existing = {r["name"] for r in get_list("Account Type", fields=["name"], limit=1000, ignore_permissions=True)}
    for code, label, root, normal, party, control, recon in DEFAULT_ACCOUNT_TYPES:
        if code in existing:
            continue
        new_doc(
            "Account Type", type_code=code, type_name=label, root_type=root, normal_balance=normal,
            requires_party=party, allows_control_account=control, default_reconciliation=recon,
            is_system_type=1, disabled=0,
        ).insert(ignore_permissions=True)



def ensure_financial_statement_layouts():
    """Seed shared layouts that run directly against the VeloraERP Account Ledger."""
    from velora.reporting.layouts import list_layouts, save_layout
    existing = {row["name"] for row in list_layouts()}
    income_statement = {
        "rows": [
            {"code": "INCOME", "description": "Revenue and Other Income", "type": "account_category", "category": "Income", "indent": 0, "bold": True},
            {"code": "EXPENSES", "description": "Expenses", "type": "account_category", "category": "Expense", "indent": 0, "bold": True},
            {"code": "NET_PROFIT", "description": "Net Profit / (Loss)", "type": "formula", "formula": "[INCOME]-[EXPENSES]", "indent": 0, "bold": True}
        ],
        "columns": [
            {"code": "CURRENT", "caption": "Current Period", "type": "net_change", "date_mode": "custom", "period": "year", "offset": 0, "width": 20}
        ],
        "options": {"statement_type": "income_statement", "currency_basis": "company_base_currency"}
    }
    statement_position = {
        "rows": [
            {"code": "ASSETS", "description": "Total Assets", "type": "account_category", "category": "Asset", "indent": 0, "bold": True},
            {"code": "LIABILITIES", "description": "Total Liabilities", "type": "account_category", "category": "Liability", "indent": 0, "bold": True},
            {"code": "EQUITY", "description": "Total Equity", "type": "account_category", "category": "Equity", "indent": 0, "bold": True},
            {"code": "LIABILITIES_EQUITY", "description": "Total Liabilities and Equity", "type": "formula", "formula": "[LIABILITIES]+[EQUITY]", "indent": 0, "bold": True},
            {"code": "BALANCE_CHECK", "description": "Assets Less Liabilities and Equity", "type": "formula", "formula": "[ASSETS]-[LIABILITIES_EQUITY]", "indent": 0, "bold": True}
        ],
        "columns": [
            {"code": "AS_AT", "caption": "As At Date", "type": "balance_at_date", "date_mode": "as_of", "period": "year", "offset": 0, "width": 20}
        ],
        "options": {"statement_type": "statement_of_financial_position", "currency_basis": "company_base_currency"}
    }
    comparative_income = {
        "rows": [
            {"code": "INCOME", "description": "Revenue and Other Income", "type": "account_category", "category": "Income", "indent": 0, "bold": True},
            {"code": "EXPENSES", "description": "Expenses", "type": "account_category", "category": "Expense", "indent": 0, "bold": True},
            {"code": "NET_PROFIT", "description": "Profit / (Loss) for the Period", "type": "formula", "formula": "[INCOME]-[EXPENSES]", "indent": 0, "bold": True},
            {"code": "NET_MARGIN", "description": "Net Profit Margin (%)", "type": "formula", "formula": "([NET_PROFIT]/[INCOME])*100", "indent": 1},
        ],
        "columns": [
            {"code": "CURRENT", "caption": "Current Period", "type": "net_change", "date_mode": "current_period", "period": "month", "offset": 0, "width": 18},
            {"code": "PRIOR", "caption": "Prior Year Comparable", "type": "same_period_last_year", "date_mode": "current_period", "period": "month", "offset": -12, "width": 20},
            {"code": "VARIANCE", "caption": "Variance", "type": "formula", "formula": "[CURRENT]-[PRIOR]", "width": 16},
            {"code": "VARIANCE_PCT", "caption": "Variance (%)", "type": "formula", "formula": "(([CURRENT]-[PRIOR])/[PRIOR])*100", "width": 15},
            {"code": "YTD", "caption": "Current YTD", "type": "year_to_date", "date_mode": "current_period", "period": "year", "offset": 0, "width": 18},
            {"code": "PRIOR_YTD", "caption": "Prior Year YTD", "type": "year_to_date", "date_mode": "current_period", "period": "year", "offset": -1, "width": 18},
            {"code": "YTD_VARIANCE", "caption": "YTD Variance", "type": "formula", "formula": "[YTD]-[PRIOR_YTD]", "width": 18},
        ],
        "options": {"statement_type": "comparative_income_statement", "currency_basis": "company_base_currency", "zero_suppression": False},
    }
    comparative_position = {
        "rows": [
            {"code": "ASSETS", "description": "Total Assets", "type": "account_category", "category": "Asset", "indent": 0, "bold": True},
            {"code": "LIABILITIES", "description": "Total Liabilities", "type": "account_category", "category": "Liability", "indent": 0, "bold": True},
            {"code": "EQUITY", "description": "Total Equity", "type": "account_category", "category": "Equity", "indent": 0, "bold": True},
            {"code": "LIABILITIES_EQUITY", "description": "Total Liabilities and Equity", "type": "formula", "formula": "[LIABILITIES]+[EQUITY]", "indent": 0, "bold": True},
            {"code": "BALANCE_CHECK", "description": "Assets Less Liabilities and Equity (must be zero)", "type": "formula", "formula": "[ASSETS]-[LIABILITIES_EQUITY]", "indent": 0, "bold": True},
        ],
        "columns": [
            {"code": "CURRENT", "caption": "Current As At", "type": "balance_at_date", "date_mode": "as_of", "period": "year", "offset": 0, "width": 18},
            {"code": "PRIOR", "caption": "Prior Year Comparable", "type": "balance_at_date", "date_mode": "as_of", "period": "year", "offset": -1, "width": 20},
            {"code": "MOVEMENT", "caption": "Movement", "type": "formula", "formula": "[CURRENT]-[PRIOR]", "width": 18},
        ],
        "options": {"statement_type": "comparative_statement_of_financial_position", "currency_basis": "company_base_currency", "balance_check_required": True},
    }
    equity_reconciliation = {
        "rows": [
            {"code": "EQUITY", "description": "Total Equity", "type": "account_category", "category": "Equity", "indent": 0, "bold": True},
        ],
        "columns": [
            {"code": "OPENING", "caption": "Opening Balance", "type": "opening_balance", "date_mode": "current_period", "period": "day", "offset": 0, "width": 18},
            {"code": "MOVEMENTS", "caption": "Movements During Period", "type": "net_change", "date_mode": "current_period", "period": "month", "offset": 0, "width": 22},
            {"code": "CLOSING", "caption": "Closing Balance", "type": "balance_at_date", "date_mode": "current_period", "period": "month", "offset": 0, "width": 18},
            {"code": "RECONCILIATION", "caption": "Reconciliation (must be zero)", "type": "formula", "formula": "[OPENING]+[MOVEMENTS]-[CLOSING]", "width": 22},
        ],
        "options": {"statement_type": "equity_movement_reconciliation", "currency_basis": "company_base_currency", "requires_equity_account_mapping_review": True},
    }
    layouts = (
        ("Income Statement", income_statement),
        ("Statement of Financial Position", statement_position),
        ("Comparative Income Statement", comparative_income),
        ("Comparative Statement of Financial Position", comparative_position),
        ("Statement of Changes in Equity - Mapping Template", equity_reconciliation),
    )
    for name, definition in layouts:
        if name not in existing:
            save_layout(name, definition, shared=True)


def ensure_finance_workspace():
    """Publish a role-aware Finance landing workspace integrated with native Velora routes."""
    from velora.application_workspaces import listing, save, set_default
    existing = listing()
    finance = next((row for row in existing if row["scope"] == "company" and row["name"] == "Finance"), None)
    if finance is None:
        finance = _save_fitted({
            "name": "Finance",
            "description": "Finance operations, account controls, financial reports and period management.",
            "visibility": "company",
            "roles": [],
            "widgets": [
                {"type": "shortcut", "title": "Account Structure", "description": "Maintain accounts and reporting hierarchy", "route": "#/app/Account", "width": 2},
                {"type": "shortcut", "title": "Account Groups", "description": "Manage the account hierarchy", "route": "#/app/Account Group", "width": 2},
                {"type": "shortcut", "title": "Cost Centres", "description": "Manage responsibility and cost allocation", "route": "#/app/Cost Centre", "width": 2},
                {"type": "shortcut", "title": "Accounting Dimensions", "description": "Manage financial analysis dimensions", "route": "#/app/Accounting Dimension", "width": 2},
                {"type": "shortcut", "title": "Financial Voucher", "description": "Create controlled financial adjustments", "route": "#/app/Financial Voucher", "width": 2},
                {"type": "shortcut", "title": "Opening Balances", "description": "Load approved opening balances", "route": "#/app/Opening Balance Entry", "width": 2},
                {"type": "shortcut", "title": "Trial Balance", "description": "Opening, movement and closing balances", "route": "#/report/Trial Balance", "width": 2},
                {"type": "shortcut", "title": "Account Ledger", "description": "Trace postings to their source documents", "route": "#/report/Account Ledger", "width": 2},
                {"type": "shortcut", "title": "Financial Statements", "description": "Run and design governed financial statements", "route": "#/financial-reports", "width": 2},
                {"type": "shortcut", "title": "Finance Settings", "description": "Company accounting and posting controls", "route": "#/app/Finance Settings", "width": 2},
                {"type": "shortcut", "title": "Financial Periods", "description": "Manage financial years and periods", "route": "#/app/Financial Period", "width": 2},
                {"type": "shortcut", "title": "Financial Years", "description": "Manage annual accounting boundaries", "route": "#/app/Financial Year", "width": 2},
                {"type": "number", "title": "Posted Ledger Records", "doctype": "Account Ledger Record", "filters": {}, "width": 1},
                {"type": "number", "title": "Draft Financial Vouchers", "doctype": "Financial Voucher", "filters": {"docstatus": 0}, "width": 1},
                {"type": "number", "title": "Pending Opening Balance Entries", "doctype": "Opening Balance Entry", "filters": {"docstatus": 0, "approval_status": "Pending"}, "width": 1},
                {"type": "activity", "title": "Recent Finance Activity", "width": 4}
            ]
        }, "company")
    # Extend an existing Finance workspace without replacing user-customised widgets.
    widgets = list(finance.get("layout") or [])
    # Keep the Finance workspace within the framework's 30-widget limit.
    # Employee master maintenance belongs in HR; keep the Employee Ledger report.
    widgets = [widget for widget in widgets if widget.get("title") != "Employees"]
    shortcuts = [
        {"type": "shortcut", "title": "Customers", "description": "Maintain customer accounts and credit controls", "route": "#/app/Customer", "width": 2},
        {"type": "shortcut", "title": "Sales Invoices", "description": "Issue and post customer invoices", "route": "#/app/Sales Invoice", "width": 2},
                {"type": "shortcut", "title": "Suppliers", "description": "Maintain supplier accounts and payable controls", "route": "#/app/Supplier", "width": 2},
        {"type": "shortcut", "title": "Purchase Invoices", "description": "Record and post supplier invoices", "route": "#/app/Purchase Invoice", "width": 2},
                {"type": "shortcut", "title": "Payment Terms", "description": "Configure invoice due dates and settlement discounts", "route": "#/app/Payment Terms", "width": 2},
        {"type": "shortcut", "title": "Customer Ledger", "description": "Review customer balances and transaction history", "route": "#/report/Customer Ledger", "width": 2},
        {"type": "shortcut", "title": "Supplier Ledger", "description": "Review supplier balances and transaction history", "route": "#/report/Supplier Ledger", "width": 2},
        {"type": "shortcut", "title": "Customer Statement", "description": "Review customer statement presentation", "route": "#/report/Customer Statement", "width": 2},
        {"type": "shortcut", "title": "Supplier Statement", "description": "Review supplier statement presentation", "route": "#/report/Supplier Statement", "width": 2},
        {"type": "shortcut", "title": "Customer Credit Exposure", "description": "Review customer credit utilisation and exposure", "route": "#/report/Customer Credit Exposure", "width": 2},
        {"type": "shortcut", "title": "Sales Margin Analysis", "description": "Analyse sales margin by item, customer and period", "route": "#/report/Sales Margin Analysis", "width": 2},
        {"type": "shortcut", "title": "Stock Balance", "description": "Review inventory quantity and valuation balances", "route": "#/report/Stock Balance", "width": 2},
        {"type": "shortcut", "title": "Employee Ledger", "description": "Review employee advances, loans and payable balances", "route": "#/report/Employee Ledger", "width": 2},
        {"type": "shortcut", "title": "Receipts", "description": "Record customer receipts, income and other incoming funds", "route": "#/app/Receipt", "width": 2},
        {"type": "shortcut", "title": "Payments", "description": "Record supplier payments, expenses and other outgoing funds", "route": "#/app/Payment", "width": 2},
        {"type": "shortcut", "title": "Recognition Schedules", "description": "Manage prepayment amortisation and deferred income", "route": "#/app/Recognition Schedule", "width": 2},
        {"type": "shortcut", "title": "Intercompany Cost Allocations", "description": "Monitor shared-cost instructions awaiting counterparty posting", "route": "#/app/Intercompany Cost Allocation", "width": 2},
    ]
    # Finance keeps its ledger/statement/recognition shortcuts; day-to-day customer, supplier and cash-settlement
    # shortcuts live in their own "Receivables & Payables" workspace so no workspace exceeds the framework's
    # 30-widget limit (v2.70.0 tried to put all of them on Finance and failed to install).
    finance_titles = ['Customer Ledger', 'Customer Statement', 'Employee Ledger', 'Intercompany Cost Allocations', 'Recognition Schedules', 'Supplier Ledger', 'Supplier Statement']
    moved = [widget for widget in shortcuts if widget["title"] not in finance_titles]
    shortcuts = [widget for widget in shortcuts if widget["title"] in finance_titles]
    # Drop any previously seeded copies of the moved shortcuts from Finance (they now live in the new workspace).
    moved_titles = {widget["title"] for widget in moved}
    widgets = [widget for widget in widgets if widget.get("title") not in moved_titles]
    titles = {widget.get("title") for widget in widgets}
    widgets.extend(widget for widget in shortcuts if widget["title"] not in titles)
    _ensure_receivables_payables_workspace(moved)
    _save_fitted({"id": finance["id"], "name": finance["name"], "description": finance.get("description", ""),
          "visibility": finance.get("visibility", "company"), "roles": finance.get("roles") or [], "widgets": widgets}, "company")
    if not any(row.get("scope") == "company" and row.get("is_default") for row in existing):
        set_default(finance["id"])




def _ensure_receivables_payables_workspace(shortcuts):
    from velora.application_workspaces import listing, save
    current = next((row for row in listing() if row.get("scope") == "company" and row.get("name") == "Receivables & Payables"), None)
    widgets = list((current or {}).get("layout") or [])
    titles = {widget.get("title") for widget in widgets}
    widgets.extend(widget for widget in shortcuts if widget["title"] not in titles)
    _save_fitted({"id": (current or {}).get("id"), "name": "Receivables & Payables",
          "description": "Customers, suppliers, invoices, receipts, payments and settlement controls.",
          "visibility": "company", "roles": [], "widgets": widgets}, "company")


def ensure_recruitment_workspace():
    """Provide a dedicated ATS workspace over the canonical HR recruitment records."""
    from velora.application_workspaces import listing, save
    existing = listing()
    current = next((row for row in existing if row.get("scope") == "company" and row.get("name") == "Recruitment"), None)
    widgets = list((current or {}).get("layout") or [])
    shortcuts = [
        {"type":"shortcut","title":"Recruitment Dashboard","description":"Monitor open roles, pipeline conversion and interview activity","route":"#/app/Job Requisition","width":2},
        {"type":"shortcut","title":"Candidate Register","description":"Maintain candidate profiles, consent and source information","route":"#/app/Candidate","width":2},
        {"type":"shortcut","title":"Job Applications","description":"Manage screening and candidate pipeline stages","route":"#/app/Job Application","width":2},
        {"type":"shortcut","title":"Interview Calendar","description":"Schedule interviews, panels and structured feedback","route":"#/app/Interview","width":2},
        {"type":"shortcut","title":"Recruitment Inbox","description":"Review recruitment notifications and due actions","route":"#/app/Recruitment Inbox Notification","width":2},
        {"type":"shortcut","title":"Job Offers","description":"Prepare and track approved employment offers","route":"#/app/Job Offer","width":2},
        {"type":"shortcut","title":"Recruitment Settings","description":"Configure pipeline, reminders and optional AI assistance","route":"#/app/Recruitment Settings","width":2},
    ]
    titles = {item.get("title") for item in widgets}
    widgets.extend(item for item in shortcuts if item["title"] not in titles)
    _save_fitted({"id":(current or {}).get("id"),"name":"Recruitment","description":"Applicant tracking, candidate pipeline, interview scheduling, hiring decisions and recruitment intelligence.","visibility":"company","roles":[],"widgets":widgets[:30]},"company")


def ensure_payroll_workspace():
    """Publish payroll and employee finance as a governed Finance workspace."""
    from velora.application_workspaces import listing, save
    existing=listing()
    current=next((row for row in existing if row.get("scope")=="company" and row.get("name")=="Payroll & Employee Finance"),None)
    widgets=list((current or {}).get("layout") or [])
    shortcuts=[
      {"type":"shortcut","title":"Salary Components","description":"Configure controlled earning, deduction and employer contribution rules","route":"#/app/Salary Component","width":2},
      {"type":"shortcut","title":"Salary Structures","description":"Maintain approved salary calculation structures","route":"#/app/Salary Structure","width":2},
      {"type":"shortcut","title":"Salary Assignments","description":"Maintain effective-dated employee compensation assignments","route":"#/app/Salary Structure Assignment","width":2},
      {"type":"shortcut","title":"Payroll Preparation","description":"Pick the month: profiles and assignments are set up, the run is built and problems are listed","route":"#/app/Payroll Preparation","width":2},
      {"type":"shortcut","title":"Rent Declarations","description":"Annual rent per employee; verified declarations give PAYE rent relief automatically","route":"#/app/Employee Rent Declaration","width":2},
      {"type":"shortcut","title":"Payroll Automation Settings","description":"Tax rule, salary structure, rent relief rate and cap, and pre-payroll checks","route":"#/app/Payroll Automation Settings","width":2},
      {"type":"shortcut","title":"Payroll Runs","description":"Prepare, review, approve and post payroll accruals","route":"#/app/Payroll Run","width":2},
      {"type":"shortcut","title":"Salary Slips","description":"Review employee-level payroll statements and balances","route":"#/app/Salary Slip","width":2},
      {"type":"shortcut","title":"Payroll Inputs","description":"Manage approved one-time and recurring employee payroll inputs","route":"#/app/Payroll Input","width":2},
      {"type":"shortcut","title":"Payroll Register","description":"Review gross pay, deductions, employer costs and outstanding salary liabilities","route":"#/report/Payroll Register","width":2},
      {"type":"shortcut","title":"Payroll Payments","description":"Settle posted employee salary liabilities","route":"#/app/Payroll Payment","width":2},
      {"type":"shortcut","title":"Employee Loan Types","description":"Maintain approved employee loan policies and eligibility limits","route":"#/app/Employee Loan Type","width":2},
      {"type":"shortcut","title":"Loan Applications","description":"Review, approve and generate employee loan disbursements","route":"#/app/Employee Loan Application","width":2},
      {"type":"shortcut","title":"Employee Loans","description":"Approve, disburse and monitor employee loans and repayment schedules","route":"#/app/Employee Loan","width":2},
      {"type":"shortcut","title":"Loan Repayments","description":"Record employee loan repayments and payroll recovery","route":"#/app/Employee Loan Repayment","width":2},
      {"type":"shortcut","title":"Employee Advances","description":"Approve and disburse employee cash advances","route":"#/app/Employee Advance","width":2},
      {"type":"shortcut","title":"Advance Settlements","description":"Settle employee advances using expense evidence or cash refunds","route":"#/app/Employee Advance Settlement","width":2},
      {"type":"shortcut","title":"Employee Ledger","description":"Review employee receivables, recoveries and payables","route":"#/report/Employee Ledger","width":2},
      {"type":"shortcut","title":"Employee Loan Register","description":"Review employee loan principal and outstanding balances","route":"#/report/Employee Loan Register","width":2},
      {"type":"shortcut","title":"Employee Advance Register","description":"Review employee advance settlements and balances","route":"#/report/Employee Advance Register","width":2},
      {"type":"shortcut","title":"Tax Jurisdictions","description":"Configure country and tax-year localisation contexts","route":"#/app/Payroll Tax Jurisdiction","width":2},
      {"type":"shortcut","title":"Payroll Tax Rules","description":"Maintain approved effective-dated progressive tax bands","route":"#/app/Payroll Tax Rule","width":2},
      {"type":"shortcut","title":"Employee Tax Profiles","description":"Assign effective-dated tax jurisdictions and rules to employees","route":"#/app/Employee Tax Profile","width":2},
      {"type":"shortcut","title":"PAYE Refund and Credit Reviews","description":"Independently approve cumulative tax over-withholding credits before payroll posting","route":"#/app/Tax Refund Credit Review","width":2},
    ]
    titles={x.get("title") for x in widgets}
    widgets.extend(x for x in shortcuts if x["title"] not in titles)
    _save_fitted({"id":(current or {}).get("id"),"name":"Payroll & Employee Finance",
      "description":"Finance-owned payroll processing, employee loans, advances, salary liabilities and settlements.",
      "visibility":"company","roles":[],"widgets":widgets[:30]},"company")

def ensure_period_end_workspace():
    """Create a dedicated period-end control workspace without overcrowding Finance."""
    from velora.application_workspaces import listing, save
    existing = listing()
    current = next((row for row in existing if row.get("scope") == "company" and row.get("name") == "Period End"), None)
    widgets = list((current or {}).get("layout") or [])
    shortcuts = [
        {"type": "shortcut", "title": "Financial Periods", "description": "Review accounting periods and posting status", "route": "#/app/Financial Period", "width": 2},
        {"type": "shortcut", "title": "Period Close Review", "description": "Complete period-end reconciliations and submit for independent approval", "route": "#/app/Financial Period Close", "width": 2},
        {"type": "shortcut", "title": "Trial Balance", "description": "Review opening balances, movements and closing balances", "route": "#/report/Trial Balance", "width": 2},
        {"type": "shortcut", "title": "Account Ledger", "description": "Investigate period movements and source transactions", "route": "#/report/Account Ledger", "width": 2},
        {"type": "shortcut", "title": "Financial Statements", "description": "Review the governed financial statements", "route": "#/financial-reports", "width": 2},
        {"type": "shortcut", "title": "Financial Report Publications", "description": "Review, independently approve and publish immutable financial statement snapshots", "route": "#/app/Financial Report Publication", "width": 2},
        {"type": "shortcut", "title": "Financial Budgets", "description": "Prepare, independently approve and maintain periodised budget versions", "route": "#/app/Financial Budget", "width": 2},
        {"type": "shortcut", "title": "Budget Adjustments", "description": "Approved budget increases, decreases and transfers", "route": "#/app/Budget Adjustment", "width": 2},
        {"type": "shortcut", "title": "Deferred Tax Posting Inbox", "description": "Resolve deferred tax proposals before period closure", "route": "#/app/Deferred Tax Posting Inbox", "width": 2},
        {"type": "shortcut", "title": "Year End Close", "description": "Review, independently approve and post the financial year closing journal", "route": "#/app/Year End Close", "width": 2},
    ]
    titles = {widget.get("title") for widget in widgets}
    widgets.extend(widget for widget in shortcuts if widget["title"] not in titles)
    _save_fitted({"id": (current or {}).get("id"), "name": "Period End",
          "description": "Period-end reconciliation, review, approval and financial close controls.",
          "visibility": "company", "roles": [], "widgets": widgets[:30]}, "company")


def ensure_finance_operations_workspaces():
    """Publish focused Treasury and Fixed Assets workspaces without overcrowding Finance."""
    from velora.application_workspaces import listing, save
    existing = listing()
    definitions = {
        "Treasury": ("Bank statement processing, bulk bank movements, accruals and journal controls.", [
            {"type":"shortcut","title":"Journal Voucher","description":"Create balanced manual journals through the Financial Posting Engine","route":"#/app/Financial Voucher","width":2},
            {"type":"shortcut","title":"Journal Entry Voucher","description":"Many journal transactions in one voucher, each with its opposite leg created for you","route":"#/app/Journal Entry Voucher","width":2},
            {"type":"shortcut","title":"Bank Accounts","description":"Company bank accounts linked to ledger accounts, used on Payments and Receipts","route":"#/app/Bank Account","width":2},
            {"type":"shortcut","title":"Bank Transaction Processor","description":"Import, code and review statement lines before posting","route":"#/app/Bank Transaction Processor","width":2},
            {"type":"shortcut","title":"Bank Coding Rules","description":"Configure deterministic statement coding rules","route":"#/app/Bank Transaction Coding Rule","width":2},
            {"type":"shortcut","title":"Batch Bank Transaction","description":"Approve and post a batch of bank receipts and payments","route":"#/app/Batch Bank Transaction","width":2},
            {"type":"shortcut","title":"Expense Batch","description":"Petty-cash expense batch with duplicate checks and withholding tax","route":"#/app/Expense Batch","width":2},
            {"type":"shortcut","title":"Accruals","description":"Post period-end accruals with scheduled reversals","route":"#/app/Accrual","width":2},
            {"type":"shortcut","title":"Payments","description":"Settle suppliers, expenses and lease instalments","route":"#/app/Payment","width":2},
            {"type":"shortcut","title":"Account Ledger","description":"Trace every bank movement to its source posting","route":"#/report/Account Ledger","width":2},
        ]),
        "Fixed Assets": ("Capital expenditure requests, acquisitions, lease accounting and asset lifecycle controls.", [
            {"type":"shortcut","title":"Fixed Asset Register","description":"Maintain owned and right-of-use assets","route":"#/app/Fixed Asset","width":2},
            {"type":"shortcut","title":"Fixed Asset Categories","description":"Configure asset accounts and useful-life defaults","route":"#/app/Fixed Asset Category","width":2},
            {"type":"shortcut","title":"Fixed Asset Requests","description":"Raise and approve capital expenditure requests","route":"#/app/Fixed Asset Request","width":2},
            {"type":"shortcut","title":"Fixed Asset Purchases","description":"Record and capitalise direct asset acquisitions","route":"#/app/Fixed Asset Purchase","width":2},
            {"type":"shortcut","title":"Fixed Asset Leases","description":"Recognise lessee right-of-use assets and lease liabilities","route":"#/app/Fixed Asset Lease","width":2},
            {"type":"shortcut","title":"Fixed Asset Revaluation","description":"Record supported asset valuation movements","route":"#/app/Fixed Asset Revaluation","width":2},
            {"type":"shortcut","title":"Fixed Asset Disposal","description":"Derecognise assets and calculate disposal gains or losses","route":"#/app/Fixed Asset Disposal","width":2},
            {"type":"shortcut","title":"Depreciation Runs","description":"Calculate, review and post periodic depreciation for owned and right-of-use assets","route":"#/app/Fixed Asset Depreciation Run","width":2},
            {"type":"shortcut","title":"Asset Impairment","description":"Assess impairment losses and controlled reversals under IAS 36","route":"#/app/Fixed Asset Impairment","width":2},
            {"type":"shortcut","title":"Asset Transfers","description":"Move assets between locations, cost centres and business units with approval and history","route":"#/app/Fixed Asset Transfer","width":2},
            {"type":"shortcut","title":"Asset History","description":"Review immutable asset movement and lifecycle history","route":"#/app/Fixed Asset History Log","width":2},
            {"type":"shortcut","title":"Asset GL Reconciliation","description":"Compare fixed asset subledger balances with asset-linked General Ledger postings","route":"#/report/Fixed Asset Reconciliation","width":2},
            {"type":"shortcut","title":"Depreciation Books","description":"Separate IFRS financial, tax and management depreciation bases","route":"#/app/Fixed Asset Depreciation Book","width":2},
            {"type":"shortcut","title":"Asset Book Balances","description":"Maintain tax and management opening carrying values per asset and book","route":"#/app/Fixed Asset Book Balance","width":2},
            {"type":"shortcut","title":"Lease Modifications","description":"Remeasure lessee lease liabilities and right-of-use assets","route":"#/app/Fixed Asset Lease Modification","width":2},
            {"type":"shortcut","title":"Cash-generating Units","description":"Maintain IAS 36 CGU asset groupings","route":"#/app/Fixed Asset CGU","width":2},
            {"type":"shortcut","title":"CGU Impairment Assessments","description":"Allocate impairment losses to fixed assets subject to recoverable amount floors","route":"#/app/Fixed Asset CGU Impairment","width":2},
            {"type":"shortcut","title":"Deferred Tax Assessments","description":"Calculate temporary differences and generate review proposals","route":"#/app/Deferred Tax Assessment","width":2},
            {"type":"shortcut","title":"Deferred Tax Posting Inbox","description":"Review, independently approve and post proposed deferred tax journals","route":"#/app/Deferred Tax Posting Inbox","width":2},
            {"type":"shortcut","title":"Component Adjustments","description":"Add, retire, impair and revalue significant asset components after acquisition","route":"#/app/Fixed Asset Component Adjustment","width":2},
            {"type":"shortcut","title":"Lease Terminations","description":"Process full lease termination and partial scope reduction with ROU derecognition","route":"#/app/Fixed Asset Lease Termination","width":2},
            {"type":"shortcut","title":"CGU Impairment Reversals","description":"Reverse eligible CGU impairment within the no-impairment carrying amount ceiling","route":"#/app/Fixed Asset CGU Impairment Reversal","width":2},
        ]),
    }
    for name, (description, shortcuts) in definitions.items():
        current = next((row for row in existing if row.get("scope") == "company" and row.get("name") == name), None)
        widgets = list((current or {}).get("layout") or [])
        titles = {widget.get("title") for widget in widgets}
        widgets.extend(widget for widget in shortcuts if widget["title"] not in titles)
        _save_fitted({"id": (current or {}).get("id"), "name": name, "description": description,
              "visibility":"company", "roles":[], "widgets":widgets[:30]}, "company")



def ensure_fixed_asset_depreciation_books():
    """Seed the Financial and Tax depreciation books once (each company has its own database)."""
    from velora import get_list, new_doc
    existing=get_list("Fixed Asset Depreciation Book",fields=["book_code"],limit=100,ignore_permissions=True)
    codes={r["book_code"] for r in existing}
    settings=get_list("Finance Settings",fields=["accounting_framework"],limit=1,ignore_permissions=True)
    framework=(settings[0].get("accounting_framework") if settings else "IFRS") or "IFRS"
    if "FINANCIAL" not in codes:
        new_doc("Fixed Asset Depreciation Book",book_code="FINANCIAL",book_name="Financial Reporting Book",book_type="Financial",accounting_framework=framework,posts_to_gl=1,is_default=1,disabled=0,description="Primary statutory financial reporting depreciation book.").insert(ignore_permissions=True)
    if "TAX" not in codes:
        new_doc("Fixed Asset Depreciation Book",book_code="TAX",book_name="Tax Depreciation Book",book_type="Tax",accounting_framework="Tax",posts_to_gl=0,is_default=0,disabled=0,description="Non-posting tax depreciation book for deferred tax.").insert(ignore_permissions=True)


def ensure_hr_workspace():
    """Publish the HR workspace for employee administration and workforce operations."""
    from velora.application_workspaces import listing, save, set_default

    existing = listing()
    workspace = next(
        (row for row in existing if row["scope"] == "company" and row["name"] == "HR & People"),
        None,
    )
    widgets = [
        {"type": "shortcut", "title": "Employee 360°", "description": "Open the unified employee profile and lifecycle workspace", "route": "#/hr/employee", "width": 2},
        {"type": "shortcut", "title": "Employees", "description": "Maintain the canonical employee master", "route": "#/app/Employee", "width": 2},
        {"type": "shortcut", "title": "Leave Management Centre", "description": "Design leave policies, preview eligibility, review balances and utilisation", "route": "#/hr/leave", "width": 4},
        {"type": "shortcut", "title": "Employee Profiles", "description": "Manage restricted personnel profile details", "route": "#/app/Employee HR Profile", "width": 2},
        {"type": "shortcut", "title": "Departments", "description": "Maintain the organisation structure", "route": "#/app/Department", "width": 2},
        {"type": "shortcut", "title": "Designations", "description": "Manage job titles and designations", "route": "#/app/Designation", "width": 2},
        {"type": "shortcut", "title": "Job Grades", "description": "Maintain job grades and career levels", "route": "#/app/Job Grade", "width": 2},
        {"type": "shortcut", "title": "Job Bands", "description": "Manage career bands", "route": "#/app/Job Band", "width": 2},
        {"type": "shortcut", "title": "Job Positions", "description": "Manage approved and vacant positions", "route": "#/app/Job Position", "width": 2},
        {"type": "shortcut", "title": "Work Locations", "description": "Manage office, branch and remote locations", "route": "#/app/Work Location", "width": 2},
        {"type": "shortcut", "title": "Reporting Assignments", "description": "Review effective-dated employee reporting lines", "route": "#/app/Reporting Assignment", "width": 2},
        {"type": "shortcut", "title": "Employment Contracts", "description": "Maintain approved employment agreements and renewals", "route": "#/app/Employment Contract", "width": 2},
        {"type": "shortcut", "title": "Employee Documents", "description": "Track personnel documents and expiry dates", "route": "#/app/Employee Document", "width": 2},
        {"type": "shortcut", "title": "Qualifications", "description": "Maintain verified education and professional credentials", "route": "#/app/Employee Qualification", "width": 2},
        {"type": "shortcut", "title": "Employee Change Requests", "description": "Approve transfers, promotions and organisation changes", "route": "#/app/Employee Change Request", "width": 2},
        {"type": "shortcut", "title": "Probation Reviews", "description": "Track probation check-ins and confirmation decisions", "route": "#/app/Probation Review", "width": 2},
        {"type": "shortcut", "title": "Lifecycle History", "description": "Review approved employee status events", "route": "#/app/Employee Status History", "width": 2},
        {"type": "shortcut", "title": "Job Requisitions", "description": "Request and approve headcount", "route": "#/app/Job Requisition", "width": 2},
        {"type": "shortcut", "title": "Candidates", "description": "Maintain the recruitment candidate pool", "route": "#/app/Candidate", "width": 2},
        {"type": "shortcut", "title": "Job Postings", "description": "Publish approved vacancies", "route": "#/app/Job Posting", "width": 2},
        {"type": "shortcut", "title": "Job Applications", "description": "Manage the recruitment pipeline", "route": "#/app/Job Application", "width": 2},
        {"type": "shortcut", "title": "Interviews", "description": "Schedule interviews and capture scorecards", "route": "#/app/Interview", "width": 2},
        {"type": "shortcut", "title": "Job Offers", "description": "Approve and track employment offers", "route": "#/app/Job Offer", "width": 2},
        {"type": "shortcut", "title": "Onboarding Plans", "description": "Manage employee onboarding journeys", "route": "#/app/Onboarding Plan", "width": 2},
        {"type": "shortcut", "title": "Onboarding Tasks", "description": "Track assigned induction and setup tasks", "route": "#/app/Onboarding Task", "width": 2},
        {"type": "number", "title": "Active Employees", "doctype": "Employee", "filters": {"disabled": 0}, "width": 1},
        {"type": "number", "title": "Departments", "doctype": "Department", "filters": {"disabled": 0}, "width": 1},
        {"type": "number", "title": "Approved Positions", "doctype": "Job Position", "filters": {"position_status": "Approved"}, "width": 1},
        {"type": "number", "title": "Open Requisitions", "doctype": "Job Requisition", "filters": {"requisition_status": "Approved"}, "width": 1},
        {"type": "number", "title": "Active Onboarding", "doctype": "Onboarding Plan", "filters": {"plan_status": "Active"}, "width": 1},
        {"type": "shortcut", "title": "Employee Classifications", "description": "Define reusable categories such as management level and employee group", "route": "#/app/Employee Classification Category", "width": 2},
        {"type": "shortcut", "title": "Classification Values", "description": "Maintain controlled values for employee classification categories", "route": "#/app/Employee Classification Value", "width": 2},
        {"type": "shortcut", "title": "Leave Periods", "description": "Configure annual or other leave allocation periods", "route": "#/app/Leave Period", "width": 2},
        {"type": "shortcut", "title": "Leave Policies", "description": "Create versioned leave packages with employee eligibility criteria", "route": "#/app/Leave Policy", "width": 2},
        {"type": "shortcut", "title": "Bulk Policy Assignment", "description": "Preview eligible employees and allocate every leave type in a policy", "route": "#/app/Leave Policy Assignment", "width": 2},
        {"type": "shortcut", "title": "Leave Types", "description": "Configure leave policies and entitlement rules", "route": "#/app/Leave Type", "width": 2},
        {"type": "shortcut", "title": "Leave Allocations", "description": "Allocate and approve employee leave entitlements", "route": "#/app/Leave Allocation", "width": 2},
        {"type": "shortcut", "title": "Leave Applications", "description": "Review and approve employee leave requests", "route": "#/app/Leave Application", "width": 2},
        {"type": "shortcut", "title": "Holiday Lists", "description": "Maintain public holidays and work calendars", "route": "#/app/Holiday List", "width": 2},
        {"type": "shortcut", "title": "Attendance", "description": "Review daily attendance and exceptions", "route": "#/app/Attendance", "width": 2},
        {"type": "shortcut", "title": "Attendance Integrations", "description": "Connect ZKTeco BioTime and other attendance providers", "route": "#/app/Attendance Integration", "width": 2},
        {"type": "shortcut", "title": "Attendance Devices", "description": "Register biometric terminals and attendance sources", "route": "#/app/Attendance Device", "width": 2},
        {"type": "shortcut", "title": "Device User Mappings", "description": "Map provider employee identifiers to Velora employees", "route": "#/app/Attendance Device User Mapping", "width": 2},
        {"type": "shortcut", "title": "External Punch Inbox", "description": "Review imported biometric punches and exceptions", "route": "#/app/External Attendance Punch", "width": 2},
        {"type": "shortcut", "title": "Attendance Sync Runs", "description": "Review provider synchronisation history", "route": "#/app/Attendance Sync Run", "width": 2},
        {"type": "shortcut", "title": "Shift Types", "description": "Configure working hours and shift rules", "route": "#/app/Shift Type", "width": 2},
        {"type": "shortcut", "title": "Shift Assignments", "description": "Manage employee shift schedules", "route": "#/app/Shift Assignment", "width": 2},
        {"type": "shortcut", "title": "Overtime Requests", "description": "Approve overtime and submit eligible items for payroll review", "route": "#/app/Overtime Request", "width": 2},
        {"type": "shortcut", "title": "HR Service Requests", "description": "Resolve employee self-service requests", "route": "#/app/HR Service Request", "width": 2},
        {"type": "number", "title": "Pending Leave Requests", "doctype": "Leave Application", "filters": {"workflow_status": "Pending Approval"}, "width": 1},
        {"type": "number", "title": "Pending Overtime Reviews", "doctype": "Overtime Request", "filters": {"approval_status": "Pending Approval"}, "width": 1},
        {"type": "number", "title": "Open HR Requests", "doctype": "HR Service Request", "filters": {"request_status": "Open"}, "width": 1},
        {"type": "activity", "title": "Recent HR Activity", "width": 4},
    ]
    if workspace is None:
        workspace = _save_fitted({
            "name": "HR & People",
            "description": "Employee administration, organisation structure and workforce operations.",
            "visibility": "roles",
            "roles": ["HR Manager", "HR Officer"],
            "widgets": widgets[:30],
        }, "company")
    else:
        # Preserve administrator customisations; add only missing standard shortcuts.
        current = list(workspace.get("layout") or [])
        titles = {item.get("title") for item in current}
        current.extend(item for item in widgets if item.get("title") not in titles)
        _save_fitted({
            "id": workspace["id"],
            "name": "HR & People",
            "description": workspace.get("description") or "Employee administration and workforce operations.",
            "visibility": "roles",
            "roles": ["HR Manager", "HR Officer"],
            "widgets": current[:30],
        }, "company")
    # Do not override an administrator's existing default workspace.
    if not any(row.get("is_default") for row in existing if row["scope"] == "company"):
        try:
            set_default(workspace["id"])
        except Exception:
            # Workspace creation remains successful if the current setup actor
            # is not authorised to change company defaults.
            pass



def ensure_hr_operations_workspace():
    """Publish a focused HR Operations workspace for leave, attendance and service delivery."""
    from velora.application_workspaces import listing, save
    existing=listing()
    current=next((row for row in existing if row.get("scope")=="company" and row.get("name")=="HR Operations"),None)
    widgets=[
      {"type":"shortcut","title":"Employee Classifications","description":"Define reusable categories such as management level and employee group","route":"#/app/Employee Classification Category","width":2},
      {"type":"shortcut","title":"Classification Values","description":"Maintain controlled values for employee classification categories","route":"#/app/Employee Classification Value","width":2},
      {"type":"shortcut","title":"Leave Periods","description":"Configure annual or other leave allocation periods","route":"#/app/Leave Period","width":2},
      {"type":"shortcut","title":"Leave Policies","description":"Create versioned leave packages with employee eligibility criteria","route":"#/app/Leave Policy","width":2},
      {"type":"shortcut","title":"Bulk Policy Assignment","description":"Preview eligible employees and allocate every leave type in a policy","route":"#/app/Leave Policy Assignment","width":2},
      {"type":"shortcut","title":"Leave Types","description":"Configure leave policies and entitlement rules","route":"#/app/Leave Type","width":2},
      {"type":"shortcut","title":"Leave Allocations","description":"Allocate and approve employee leave entitlements","route":"#/app/Leave Allocation","width":2},
      {"type":"shortcut","title":"Leave Applications","description":"Review and approve employee leave requests","route":"#/app/Leave Application","width":2},
      {"type":"shortcut","title":"Holiday Lists","description":"Maintain public holidays and work calendars","route":"#/app/Holiday List","width":2},
      {"type":"shortcut","title":"Attendance","description":"Review daily attendance and exceptions","route":"#/app/Attendance","width":2},
      {"type":"shortcut","title":"Attendance Integrations","description":"Connect ZKTeco BioTime and other attendance providers","route":"#/app/Attendance Integration","width":2},
      {"type":"shortcut","title":"Attendance Devices","description":"Register biometric terminals and attendance sources","route":"#/app/Attendance Device","width":2},
      {"type":"shortcut","title":"Device User Mappings","description":"Map provider employee identifiers to Velora employees","route":"#/app/Attendance Device User Mapping","width":2},
      {"type":"shortcut","title":"External Punch Inbox","description":"Review imported biometric punches and exceptions","route":"#/app/External Attendance Punch","width":2},
      {"type":"shortcut","title":"Attendance Sync Runs","description":"Review provider synchronisation history","route":"#/app/Attendance Sync Run","width":2},
      {"type":"shortcut","title":"Integration Health","description":"Monitor provider connectivity, device health and sync failures","route":"#/app/Attendance Integration","width":2},
      {"type":"shortcut","title":"Shift Types","description":"Configure working hours and shift rules","route":"#/app/Shift Type","width":2},
      {"type":"shortcut","title":"Shift Assignments","description":"Manage employee shift schedules","route":"#/app/Shift Assignment","width":2},
      {"type":"shortcut","title":"Overtime Requests","description":"Approve overtime and submit eligible items for payroll review","route":"#/app/Overtime Request","width":2},
      {"type":"shortcut","title":"Performance Cycles","description":"Plan annual, quarterly and continuous performance cycles","route":"#/app/Performance Cycle","width":2},
      {"type":"shortcut","title":"Review Templates","description":"Configure weighted goals, competency and behaviour criteria","route":"#/app/Performance Review Template","width":2},
      {"type":"shortcut","title":"Performance Goals","description":"Cascade strategic and departmental objectives to employees","route":"#/app/Performance Goal","width":2},
      {"type":"shortcut","title":"Performance Check-ins","description":"Record continuous progress, coaching and blockers","route":"#/app/Performance Check In","width":2},
      {"type":"shortcut","title":"Performance Reviews","description":"Manage self-assessment, manager review and sign-off","route":"#/app/Performance Review","width":2},
      {"type":"shortcut","title":"360 Feedback","description":"Collect structured peer and multi-rater feedback","route":"#/app/Performance Feedback","width":2},
      {"type":"shortcut","title":"Improvement Plans","description":"Manage measurable performance improvement plans","route":"#/app/Performance Improvement Plan","width":2},
      {"type":"shortcut","title":"Competency Library","description":"Maintain the organisation-wide skills and competency catalogue","route":"#/app/Competency","width":2},
      {"type":"shortcut","title":"Competency Frameworks","description":"Define role, grade and departmental proficiency expectations","route":"#/app/Competency Framework","width":2},
      {"type":"shortcut","title":"Skills Gap Assessments","description":"Assess employee capability against required proficiency levels","route":"#/app/Employee Competency Assessment","width":2},
      {"type":"shortcut","title":"Calibration Sessions","description":"Moderate performance ratings with documented evidence and decisions","route":"#/app/Performance Calibration Session","width":2},
      {"type":"shortcut","title":"360 Feedback Campaigns","description":"Coordinate rater nominations, invitations and response completion","route":"#/app/Performance Rater Campaign","width":2},
      {"type":"shortcut","title":"HR Service Requests","description":"Resolve employee self-service requests","route":"#/app/HR Service Request","width":2},
      {"type":"shortcut","title":"Employee Separations","description":"Approve resignations, retirements and terminations; coordinate exit clearance and final settlement","route":"#/app/Employee Separation","width":2},
      {"type":"shortcut","title":"Handover Management","description":"Coordinate leave and separation handovers, task ownership, evidence and recipient acceptance","route":"#/app/Handover Management","width":2},
      {"type":"shortcut","title":"HR Policy Library","description":"Control policy documents, version approval, publication and review dates","route":"#/app/HR Policy Document","width":2},
      {"type":"shortcut","title":"Policy Acknowledgements","description":"Assign and monitor employee acknowledgement against exact published policy versions","route":"#/app/HR Policy Acknowledgement","width":2},
      {"type":"shortcut","title":"Employee Relations Cases","description":"Manage restricted grievances, disciplinary matters, welfare and investigations","route":"#/app/Employee Relations Case","width":2},
      {"type":"shortcut","title":"Employee Status History","description":"Review approved effective-dated employee lifecycle events","route":"#/app/Employee Status History","width":2},
      {"type":"shortcut","title":"Employment Contracts","description":"Maintain approved contracts and contract periods","route":"#/app/Employment Contract","width":2},
      {"type":"shortcut","title":"Employee Onboarding","description":"Manage onboarding plans and assigned completion tasks","route":"#/app/Onboarding Plan","width":2},
      {"type":"number","title":"Pending Leave Requests","doctype":"Leave Application","filters":{"workflow_status":"Pending Approval"},"width":1},
      {"type":"number","title":"Pending Attendance Reviews","doctype":"Attendance","filters":{"approval_status":"Pending Approval"},"width":1},
      {"type":"number","title":"Pending Overtime Reviews","doctype":"Overtime Request","filters":{"approval_status":"Pending Approval"},"width":1},
      {"type":"number","title":"Open HR Requests","doctype":"HR Service Request","filters":{"request_status":"Open"},"width":1},
      {"type":"number","title":"Active Separations","doctype":"Employee Separation","filters":{"workflow_status":"Clearance In Progress"},"width":1},
      {"type":"number","title":"Open Relations Cases","doctype":"Employee Relations Case","filters":{"case_status":"Open"},"width":1},
      {"type":"activity","title":"Recent HR Operations","width":4},
    ]
    current_widgets=list((current or {}).get("layout") or [])
    titles={x.get("title") for x in current_widgets}
    current_widgets.extend(x for x in widgets if x.get("title") not in titles)
    _save_fitted({"id":(current or {}).get("id"),"name":"HR Operations",
      "description":"Employee lifecycle, leave, attendance, performance, development and employee service delivery.",
      "visibility":"roles","roles":["HR Manager","HR Officer","Department Manager"],
      "widgets":current_widgets[:50]},"company")


def ensure_performance_workspace():
    """Publish a dedicated performance and talent management workspace."""
    from velora.application_workspaces import listing, save
    existing=listing()
    current=next((row for row in existing if row.get("scope")=="company" and row.get("name")=="Performance Management"),None)
    widgets=[
      {"type":"shortcut","title":"Performance Cycles","description":"Plan annual, quarterly, probation and continuous cycles","route":"#/app/Performance Cycle","width":2},
      {"type":"shortcut","title":"Review Templates","description":"Design weighted assessment frameworks and rating scales","route":"#/app/Performance Review Template","width":2},
      {"type":"shortcut","title":"Strategic Goals","description":"Cascade organisational, departmental and individual objectives","route":"#/app/Performance Goal","width":2},
      {"type":"shortcut","title":"Performance Check-ins","description":"Capture coaching conversations, progress and blockers","route":"#/app/Performance Check In","width":2},
      {"type":"shortcut","title":"Performance Reviews","description":"Manage self-assessment, manager ratings and approvals","route":"#/app/Performance Review","width":2},
      {"type":"shortcut","title":"360 Feedback","description":"Collect confidential peer and multi-rater feedback","route":"#/app/Performance Feedback","width":2},
      {"type":"shortcut","title":"Improvement Plans","description":"Set measurable actions, milestones and outcomes","route":"#/app/Performance Improvement Plan","width":2},
      {"type":"shortcut","title":"Competency Library","description":"Maintain the organisation-wide skills and competency catalogue","route":"#/app/Competency","width":2},
      {"type":"shortcut","title":"Competency Frameworks","description":"Define proficiency expectations by role, grade and department","route":"#/app/Competency Framework","width":2},
      {"type":"shortcut","title":"Skills Gap Assessments","description":"Assess current capability against required proficiency","route":"#/app/Employee Competency Assessment","width":2},
      {"type":"shortcut","title":"Calibration Sessions","description":"Moderate ratings with documented rationale and approval","route":"#/app/Performance Calibration Session","width":2},
      {"type":"shortcut","title":"360 Feedback Campaigns","description":"Coordinate rater nominations and feedback completion","route":"#/app/Performance Rater Campaign","width":2},
      {"type":"number","title":"Open Skills Gaps","doctype":"Employee Competency Assessment","filters":{"status":"Confirmed"},"width":1},
      {"type":"number","title":"Pending Calibration","doctype":"Performance Calibration Session","filters":{"status":"Pending Approval"},"width":1},
      {"type":"number","title":"Reviews Awaiting Approval","doctype":"Performance Review","filters":{"review_status":"Pending Approval"},"width":1},
      {"type":"number","title":"Goals At Risk","doctype":"Performance Goal","filters":{"status":"At Risk"},"width":1},
      {"type":"number","title":"Active Improvement Plans","doctype":"Performance Improvement Plan","filters":{"status":"Active"},"width":1},
    ]
    current_widgets=list((current or {}).get("layout") or [])
    titles={x.get("title") for x in current_widgets}
    current_widgets.extend(x for x in widgets if x.get("title") not in titles)
    _save_fitted({"id":(current or {}).get("id"),"name":"Performance Management",
      "description":"Continuous performance, strategic alignment, fair assessment and employee development.",
      "visibility":"roles","roles":["HR Manager","HR Officer","Department Manager"],"widgets":current_widgets[:30]},"company")


def ensure_employee_performance_workspaces():
    """Publish role-specific employee and manager performance portals."""
    from velora.application_workspaces import listing, save
    existing=listing()
    specs=[
      ("My Performance", "Employee self-service for goals, check-ins, reviews and development.", ["Employee"], [
        {"type":"shortcut","title":"My Goals","description":"Track objectives, update progress and submit evidence","route":"#/hr/performance","width":2},
        {"type":"shortcut","title":"My Performance Reviews","description":"View review outcomes and acknowledge completed reviews","route":"#/hr/performance","width":2},
        {"type":"shortcut","title":"My Check-ins","description":"Record progress, achievements and support needs","route":"#/hr/performance","width":2},
        {"type":"shortcut","title":"My Development","description":"Review competency gaps and development actions","route":"#/hr/performance","width":2},
      ]),
      ("Team Performance", "Manager self-service for direct reports, goals, coaching and reviews.", ["Department Manager"], [
        {"type":"shortcut","title":"My Team","description":"View direct reports and performance priorities","route":"#/hr/team-performance","width":2},
        {"type":"shortcut","title":"Team Goals","description":"Monitor team goal progress and delivery risks","route":"#/hr/team-performance","width":2},
        {"type":"shortcut","title":"Team Reviews","description":"Track review progress for direct reports","route":"#/hr/team-performance","width":2},
        {"type":"shortcut","title":"Coaching Check-ins","description":"Record coaching conversations with direct reports","route":"#/hr/team-performance","width":2},
      ]),
    ]
    for name,description,roles,widgets in specs:
      current=next((row for row in existing if row.get("scope")=="company" and row.get("name")==name),None)
      current_widgets=list((current or {}).get("layout") or [])
      titles={x.get("title") for x in current_widgets}
      current_widgets.extend(x for x in widgets if x.get("title") not in titles)
      _save_fitted({"id":(current or {}).get("id"),"name":name,"description":description,
        "visibility":"roles","roles":roles,"widgets":current_widgets[:20]},"company")


def ensure_area_reports():
    """Place every registered report (and the new governance doctypes) under the area workspace it belongs to."""
    from velora.application_workspaces import listing
    def rep(name, desc): return {"type":"shortcut","title":name,"description":desc,"route":f"#/report/{name}","width":2}
    def doc(name, desc, title=None): return {"type":"shortcut","title":title or name,"description":desc,"route":f"#/app/{name}","width":2}
    areas = {
        "Sales": ("Customer orders, fulfilment, invoicing and receipts.", [
            rep("Customer Ledger","Customer balances and movements"), rep("Customer Statement","Statement of account per customer"),
            rep("Customer Credit Exposure","Credit limit versus open exposure"), rep("Sales Margin Analysis","Margin by item and customer"),
            rep("Sales Quotation Register","Quotations and conversion status"), rep("Customer Complaint Register","Complaints and resolution status")]),
        "Purchasing": ("Supplier procurement, goods receipt, invoicing and payments.", [
            rep("Supplier Ledger","Supplier balances and movements"), rep("Supplier Statement","Statement of account per supplier")]),
        "Fixed Assets": ("Capital expenditure requests, acquisitions, lease accounting and asset lifecycle controls.", [
            rep("Fixed Asset Reconciliation","Subledger to ledger reconciliation"), rep("Fixed Asset Book Reconciliation","Depreciation book reconciliation"), rep("Fixed Asset Maintenance Cost","Repairs & maintenance per asset")]),
        "Treasury": ("Bank statement processing, bulk bank movements, accruals and journal controls.", [
            rep("Trial Balance","Account balances for the period")]),
        "Finance": ("Finance", [
            doc("Naming Series Rule","Configure document naming patterns per document type")]),
        "Payroll & Employee Finance": ("Payroll", [
            rep("Employee Advance Register","Advances issued and recovered"), rep("Employee Loan Register","Staff loans and balances"),
            rep("Payroll Cost Analysis","Employer cost by department, branch or cost centre"), rep("Statutory Deductions Summary","PAYE, pension and other remittances"),
            rep("Payroll Variance","Period-on-period pay changes by employee")]),
    }
    existing = listing()
    for name, (description, shortcuts) in areas.items():
        current = next((r for r in existing if r.get("scope") == "company" and r.get("name") == name), None)
        if not current:
            continue
        widgets = list(current.get("layout") or [])
        titles = {w.get("title") for w in widgets}
        add = [w for w in shortcuts if w["title"] not in titles]
        if not add:
            continue
        _save_fitted({"id": current.get("id"), "name": name, "description": current.get("description") or description,
                      "visibility": current.get("visibility") or "company", "roles": current.get("roles") or [], "widgets": widgets + add}, "company")

    # Dedicated HR Reports workspace (HR & People / HR Operations are at their widget limit).
    hr_reports = [
        rep("Employee Directory","Staff list with department, branch, grade and tenure"), rep("Headcount Analysis","Headcount, joiners, leavers and turnover"),
        rep("Leave Balance","Allocated, used and available leave"), rep("Leave Utilisation","Leave taken per employee by type"),
        rep("Attendance Summary","Present, absent, late and hours worked"), rep("Overtime Register","Overtime hours and approval status"), rep("Staff Budget vs Actual","Budgeted headcount and cost against people employed and requested"),
        rep("Contract and Probation Watch","Contracts and probations ending soon"), rep("Training Register","Enrolments, outcomes and certificate expiry"),
        rep("Recruitment Pipeline","Applications by requisition and stage"), rep("Separation and Attrition","Leavers, tenure and settlement status"),
        rep("Performance Rating Distribution","Ratings by department for a cycle"), rep("Payroll Cost Analysis","Employer cost by department, branch or cost centre"),
        rep("Statutory Deductions Summary","PAYE, pension and other remittances"), rep("Payroll Variance","Period-on-period pay changes by employee"),
        doc("Department Staff Budget","Headcount and cost budget per department"), doc("Branch","Branches and offices"),
    ]
    current = next((r for r in existing if r.get("scope") == "company" and r.get("name") == "HR Reports"), None)
    widgets = list((current or {}).get("layout") or []); titles = {w.get("title") for w in widgets}
    widgets += [w for w in hr_reports if w["title"] not in titles]
    _save_fitted({"id": (current or {}).get("id"), "name": "HR Reports", "description": "Workforce, leave, attendance, recruitment, performance and payroll reports.",
                  "visibility": "roles", "roles": ["HR Manager", "HR Officer", "Payroll Manager", "Auditor", "System Manager"], "widgets": widgets}, "company")


def after_install():
    """Create the company Finance Settings and configurable system account types once."""
    ensure_transaction_types()
    ensure_currencies()                                   # Finance Settings links to Currency, so the master comes first
    existing = get_list("Finance Settings", fields=["name"], limit=1, ignore_permissions=True)
    if not existing:
        new_doc(
            "Finance Settings", settings_name="Primary Finance Settings", country_code=os.environ.get("VELORA_COUNTRY", "NG").upper(), base_currency=os.environ.get("VELORA_BASE_CURRENCY", "NGN").upper(),
            accounting_basis="Accrual", accounting_framework="IFRS", financial_year_start_month="January",
            number_format="1,234,567.89", decimal_places=2, allow_backdated_posting=1, backdated_posting_days=365,
            prevent_posting_to_closed_periods=1, allow_negative_account_balance=0,
            exchange_rate_source="Manual", rate_type="Spot", tax_inclusive_pricing=0, tax_rounding_method="Per Document",
            track_financial_changes=1, require_reason_for_override=1,
        ).insert(ignore_permissions=True)
    ensure_account_types()
    from velora_erp.hr.data_protection import apply_default_field_protection
    apply_default_field_protection()
    from velora_erp.hr.data_protection import apply_employee_state_protection
    from velora_erp.hr.scopes import apply_default_scopes
    apply_employee_state_protection(); apply_default_scopes()
    ensure_finance_indexes()
    ensure_financial_statement_layouts()
    ensure_finance_workspace()
    ensure_hr_workspace()
    ensure_recruitment_workspace()
    ensure_hr_operations_workspace()
    ensure_performance_workspace()
    ensure_employee_performance_workspaces()
    ensure_payroll_workspace()
    ensure_period_end_workspace()
    ensure_finance_operations_workspaces()
    ensure_fixed_asset_depreciation_books()
    ensure_commercial_workspaces()
    ensure_new_area_workspaces()
    ensure_area_reports()
    from velora_erp.configuration import seed_settings_catalogue
    ensure_currencies()
    ensure_transaction_types()
    seed_settings_catalogue()
    try:
        from velora_erp.engagement import defaults as engagement_defaults
        engagement_defaults.ensure()
    except Exception:  # noqa: BLE001 - never block an install on the optional engagement module
        import logging
        logging.getLogger(__name__).exception("Engagement defaults not created")


def ensure_finance_indexes():
    """Install account/date and source lookup indexes for the immutable ledger."""
    from velora_erp.patches.v0_3.add_finance_ledger_indexes import execute
    execute()



def ensure_commercial_workspaces():
    """Create dedicated Sales and Purchasing workspaces without crowding Finance."""
    from velora.application_workspaces import listing, save
    existing = listing()
    definitions = {
        "Sales": ("Customer orders, fulfilment, invoicing and receipts.", [
            {"type":"shortcut","title":"Company Setup Readiness","description":"Review foundational configuration and outstanding setup controls","route":"#/settings/company-setup","width":2},
            {"type":"shortcut","title":"Customers","description":"Customer master records","route":"#/app/Customer","width":2},
            {"type":"shortcut","title":"Sales Orders","description":"Manage customer orders","route":"#/app/Sales Order","width":2},
            {"type":"shortcut","title":"Delivery Notes","description":"Prepare and confirm deliveries","route":"#/app/Delivery Note","width":2},
            {"type":"shortcut","title":"Waybills","description":"Prepare transport documents","route":"#/app/Waybill","width":2},
            {"type":"shortcut","title":"Sales Invoices","description":"Recognise customer revenue and receivables","route":"#/app/Sales Invoice","width":2},
            {"type":"shortcut","title":"Receipts","description":"Record customer receipts","route":"#/app/Receipt","width":2},
            {"type":"shortcut","title":"Sales Returns","description":"Process customer returns and financial reversals","route":"#/app/Sales Return","width":2},
        ]),
        "Purchasing": ("Supplier procurement, goods receipt, invoicing and payments.", [
            {"type":"shortcut","title":"Suppliers","description":"Supplier master records","route":"#/app/Supplier","width":2},
            {"type":"shortcut","title":"Purchase Orders","description":"Manage supplier orders","route":"#/app/Purchase Order","width":2},
            {"type":"shortcut","title":"Purchase Receipts","description":"Record goods received","route":"#/app/Purchase Receipt","width":2},
            {"type":"shortcut","title":"Purchase Invoices","description":"Recognise supplier costs and payables","route":"#/app/Purchase Invoice","width":2},
            {"type":"shortcut","title":"Payments","description":"Record supplier payments","route":"#/app/Payment","width":2},
            {"type":"shortcut","title":"Purchase Returns","description":"Process supplier returns and financial reversals","route":"#/app/Purchase Return","width":2},
            {"type":"shortcut","title":"Landed Cost Vouchers","description":"Allocate additional acquisition costs to received goods","route":"#/app/Landed Cost Voucher","width":2},
            {"type":"shortcut","title":"Payment Terms","description":"Configure supplier and customer terms","route":"#/app/Payment Terms","width":2},
        ]),
    }
    for name, (description, shortcuts) in definitions.items():
        current = next((row for row in existing if row.get("scope") == "company" and row.get("name") == name), None)
        widgets = list((current or {}).get("layout") or [])
        titles = {widget.get("title") for widget in widgets}
        widgets.extend(widget for widget in shortcuts if widget["title"] not in titles)
        _save_fitted({"id": (current or {}).get("id"), "name": name, "description": description,
              "visibility":"company", "roles":[], "widgets":widgets}, "company")


def after_migrate():
    """Keep governed setting contracts and setup workspace current on upgrades."""
    from velora_erp.configuration import seed_settings_catalogue
    seed_settings_catalogue()
    ensure_account_types()                               # account types added by a newer release (for example Investment) reach existing companies too
    try:
        from velora_erp.engagement import defaults as engagement_defaults
        engagement_defaults.ensure()
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("Engagement defaults not created")
    ensure_new_area_workspaces()
    ensure_finance_workspace()
    ensure_hr_workspace()
    ensure_recruitment_workspace()
    ensure_hr_operations_workspace()
    ensure_performance_workspace()
    ensure_employee_performance_workspaces()
    ensure_payroll_workspace()
    ensure_period_end_workspace()
    ensure_finance_operations_workspaces()
    ensure_fixed_asset_depreciation_books()
    ensure_commercial_workspaces()
    ensure_area_reports()


def ensure_new_area_workspaces():
    """Workspaces for the Investments, Support and Communication areas. Existing widgets are kept; only missing shortcuts are added."""
    from velora.application_workspaces import listing
    existing = listing()
    short = lambda title, description, route: {"type": "shortcut", "title": title, "description": description, "route": route, "width": 2}
    definitions = {
        "Investments": ("Money market, capital market, property and other holdings: income, tax, valuation and maturities.", [
            short("Investment Portfolio", "Holdings, allocation, maturity ladder, concentration and what is due", "#/investments"),
            short("Investments", "Register of every holding", "#/app/Investment"),
            short("Investment Transactions", "Accruals, income, dividends, rent, revaluations, sales and maturities", "#/app/Investment Transaction"),
            short("Investment Settings", "Tax treatment, limits and default accounts (Finance Settings > Investments)", "#/app/Finance Settings"),
        ]),
        "Debt and Treasury": ("Lenders, facilities, loans, repayments, interest, covenants, liquidity and currency risk.", [
            short("Treasury Centre", "Debt position, adviser findings, headroom, cash runway and covenants", "#/treasury-centre"),
            short("Financing Facilities", "Approved facilities, limits, pricing, security and covenants", "#/app/Financing Facility"),
            short("Financing Drawdowns", "Loans drawn on a facility, with the repayment schedule", "#/app/Financing Drawdown"),
            short("Financing Repayments", "Instalments paid, with withholding tax on interest", "#/app/Financing Repayment"),
            short("Interest Accruals", "Month-end interest cost across all loans", "#/app/Interest Accrual"),
            short("Covenant Tests", "Record and monitor covenant results", "#/app/Covenant Test"),
            short("Facility Amendments", "Rate changes that reprice floating loans", "#/app/Facility Amendment"),
            short("Financial Institutions", "Banks and other lenders", "#/app/Financial Institution"),
            short("Debt Portfolio", "Every loan, balance, rate and what is due", "#/report/Debt Portfolio"),
            short("Debt Maturity Ladder", "Principal by maturity bucket", "#/report/Debt Maturity Ladder"),
            short("Liquidity Forecast", "Week-by-week cash against debt service", "#/report/Liquidity Forecast"),
            short("Covenant Monitor", "Every covenant, its status and next test", "#/report/Covenant Monitor"),
        ]),
        "Support": ("Customer and internal support with service levels, escalation and satisfaction.", [
            short("Support Desk", "Queue, service-level status and workload", "#/support"),
            short("Support Tickets", "Every ticket", "#/app/Support Ticket"),
            short("Service Level Agreements", "Response and resolution targets by priority", "#/app/Service Level Agreement"),
            short("Support Teams", "Teams and their members", "#/app/Support Team"),
            short("Canned Replies", "Saved answers for common questions", "#/app/Canned Reply"),
        ]),
    }
    for name, (description, shortcuts) in definitions.items():
        current = next((row for row in existing if row.get("scope") == "company" and row.get("name") == name), None)
        widgets = list((current or {}).get("layout") or [])
        titles = {widget.get("title") for widget in widgets}
        widgets.extend(widget for widget in shortcuts if widget["title"] not in titles)
        _save_fitted({"id": (current or {}).get("id"), "name": name, "description": description, "visibility": "company", "roles": [], "widgets": widgets}, "company")
