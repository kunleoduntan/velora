"""VeloraERP application lifecycle and compatibility declarations."""
app_title = "VeloraERP"
app_description = "Integrated enterprise core: finance, inventory, assets, budgets, sales, purchasing, payroll and human resources."
default_providers = {"base_currency": "velora_erp.finance.multicurrency.base_currency"}
app_guide = "docs/VELORAERP-USER-MANUAL-v*.html"
required_apps = ["velora_projectone"]
required_velora = ">=1.19.0,<1.21.0"
required_packages = []

# The framework financial statement designer reads the VeloraERP Account Ledger
# through this provider contract, not through legacy GL Entry tables.
financial_reporting_provider = "velora_erp.finance.reporting_provider"
after_install = "velora_erp.setup.after_install"
workflow_template_provider = "velora_erp.finance.workflow_templates"
error_advice = "velora_erp.advice_rules"
# What people do, in plain words: each profile ticks the roles that job needs (People & Access). Change or add roles at any time.
access_profiles = {
    "Accountant": {"roles": ["Accountant"], "description": "Prepares invoices, receipts, payments, journals and reconciliations; cannot cancel."},
    "Finance Manager": {"roles": ["Finance Manager", "Accountant"], "description": "Approves, submits and cancels finance documents; closes periods; sees all finance reports."},
    "Auditor (read only)": {"roles": ["Auditor"], "description": "Reads and exports every ledger, document and report; changes nothing."},
    "Sales": {"roles": ["Sales Manager"], "description": "Quotations, orders, delivery and customers."},
    "Purchasing": {"roles": ["Procurement Officer"], "description": "Requests, quotations, purchase orders and suppliers."},
    "Store and inventory": {"roles": ["Storekeeper", "Inventory Manager"], "description": "Receipts, issues, transfers, stock counts and valuation."},
    "HR": {"roles": ["HR Manager", "HR Officer"], "description": "Employees, leave, attendance, recruitment and performance."},
    "Payroll": {"roles": ["Payroll Manager", "Payroll Officer"], "description": "Pay runs, salary structures, statutory deductions and payslips."},
    "Projects": {"roles": ["Project Manager", "Project User"], "description": "Projects, tasks, timesheets and project costs."},
    "Support desk": {"roles": ["Support Agent"], "description": "Tickets and customer service."},
    "Employee (self-service)": {"roles": ["Employee"], "description": "Own payslips, leave and requests only."},
}
after_migrate = "velora_erp.setup.after_migrate"
setup_readiness_provider = "velora_erp.configuration"
before_uninstall = None
# One cancel routine for every document type: it removes the posting, unlinks what hangs on the document and writes the log.
doc_events = {
    "Employee": {"on_update": "velora_erp.finance.payroll_automation.employee_saved"},
    "*": {
        "before_submit": "velora_erp.finance.restore_points.capture",
        "on_submit": "velora_erp.finance.restore_points.capture_after",
        "on_cancel": "velora_erp.finance.cancellation.on_any_cancel",
    },
}

# Plain-field links (source_doctype + source_document) that stop a document being cancelled while another submitted document uses it.
linked_documents_provider = "velora_erp.finance.links"

# Workflow definitions are created exclusively in the shared Workflow Designer.
approval_policy_provider = "velora_erp.finance.approval_policy"

# What can be copied from one company to another (Settings > Setup Copy).
setup_copy_provider = "velora_erp.setup_copy"

# Record scopes for row policies (own employee, department staff, managed departments).
row_scope_provider = "velora_erp.hr.scopes"
scheduler_events = {
    "every_minute": ["velora_erp.hr.attendance_integrations.run_scheduled_attendance_syncs", "velora_erp.support.jobs.check_sla"],
    "hourly": ["velora_erp.finance.bank_reconciliation.run_scheduled_reconciliation"],
    "daily": ["velora_erp.finance.recognition.schedules.process_due_recognitions", "velora_erp.finance.doctype.accrual.accrual.process_due_accrual_reversals", "velora_erp.finance.doctype.foreign_currency_revaluation.foreign_currency_revaluation.process_due_reversals",
              "velora_erp.investments.jobs.accrue_month_end", "velora_erp.investments.jobs.watch_maturities", "velora_erp.support.jobs.auto_close",
              "velora_erp.finance.inventory.expiry.watch_expiry", "velora_erp.finance.inventory.reservations.expire_due", "velora_erp.finance.inventory.procurement.expire_quotations", "velora_erp.engagement.jobs.run_daily", "velora_erp.tax.service.refresh_obligations", "velora_erp.treasury.jobs.daily"],
}

# Extra HTTP routes (Bank Reconciliation centre) are installed through the generic api_routes_provider hook.
api_routes_provider = "velora_erp.api_routes"

# Generic framework routes discover this provider without depending on VeloraERP.
document_flow_provider = "velora_erp.finance.document_flow.api"

# Generic Velora Desk row-pricing provider for Inventory Item cost-based pricing.
document_pricing_provider = "velora_erp.finance.pricing"

# Declarative AI advisors are discovered by the framework AI gateway.
# They are read-only advisors; no advisor is allowed to execute business actions.
ai_advisors = (
    {
        "id": "veloraerp.hr.recruitment.advisor",
        "title": "Recruitment & Candidate Review Advisor",
        "description": "Assists authorised HR users with structured candidate summaries, job matching questions and interview preparation using permitted record context.",
        "app": "VeloraERP",
        "doctype": "Job Application",
        "context_fields": ["name", "candidate", "requisition", "job_posting", "application_date", "screening_score", "screening_notes", "application_stage"],
        "roles": ["System Manager", "HR Manager", "HR Officer"],
        "system_prompt": "You are a recruitment support advisor. Use only the supplied permitted fields. Provide evidence-based summaries and interview preparation questions. Do not infer protected characteristics, rank candidates using protected traits, make hiring decisions, reject candidates, or modify records. Flag missing evidence and require human review.",
    },
    {
        "id": "veloraerp.finance.advisor",
        "title": "Finance & Accounting Advisor",
        "description": "Explains accounting treatment, financial performance, controls and reporting considerations.",
        "app": "VeloraERP",
        "roles": ["System Manager", "Accounts Manager", "Accounts User", "Auditor", "Finance Manager"],
        "system_prompt": "You are a senior enterprise finance and accounting advisor. Explain accounting logic clearly, identify control implications, distinguish accounting standards from local tax rules, and state assumptions. Do not post, approve, cancel, amend or modify transactions. Do not invent ledger balances or claim to have inspected records not supplied in the approved context.",
    },
    {
        "id": "veloraerp.tax.advisor",
        "title": "Tax Adviser",
        "description": "Explains how VAT, withholding tax, company income tax and levies are treated in the books, what a return should contain and what to check before filing.",
        "app": "VeloraERP",
        "roles": ["System Manager", "Accounts Manager", "Accounts User", "Auditor", "Finance Manager", "Accountant"],
        "system_prompt": "You are a careful tax adviser working inside an ERP. Explain how a transaction should be taxed and accounted for, and which Tax Rule, Tax Journal, return or computation in the system covers it. Never quote a statutory rate, threshold or deadline as fact unless it was supplied in the approved context: say it must be taken from the approved Tax Rule or the current law, and suggest checking with the tax authority or a qualified adviser. Do not post, approve, file, cancel or modify anything, and do not invent balances.",
    },
    {
        "id": "veloraerp.tax.computation.reviewer",
        "title": "Income Tax Computation Reviewer",
        "description": "Reviews an authorised income tax computation for unusual adjustments and missing items.",
        "app": "VeloraERP",
        "doctype": "Income Tax Computation",
        "context_fields": ["name", "period_start", "period_end", "accounting_profit", "total_add_backs", "total_deductions", "total_capital_allowances", "adjusted_profit", "loss_brought_forward", "assessable_profit", "income_tax_charge", "levies", "wht_utilised", "net_payable"],
        "roles": ["System Manager", "Accounts Manager", "Finance Manager", "Accountant", "Auditor"],
        "system_prompt": "You are a cautious tax computation reviewer. Review only the supplied fields. Point out adjustments that look unusually large or small against profit, missing capital allowances, losses that were not used and credits that were not claimed, and say what a human reviewer should check. Do not state the law as fact and do not decide whether to file.",
    },
    {
        "id": "veloraerp.sales.invoice.reviewer",
        "title": "Sales Invoice Review Advisor",
        "description": "Reviews an authorised Sales Invoice for completeness, unusual values and potential control issues.",
        "app": "VeloraERP",
        "doctype": "Sales Invoice",
        "context_fields": ["name", "customer", "posting_date", "due_date", "currency", "grand_total", "total_taxes_and_charges", "status", "docstatus"],
        "roles": ["System Manager", "Accounts Manager", "Accounts User", "Sales Manager", "Auditor"],
        "system_prompt": "You are a cautious invoice review advisor. Review only the supplied permitted fields. Identify missing information, arithmetic or date anomalies, and questions a human reviewer should investigate. Do not decide whether to approve or post. Never infer that an invoice is fraudulent from an anomaly alone.",
    },
    {
        "id": "veloraerp.treasury.advisor",
        "title": "Debt & Treasury Advisor",
        "description": "Explains loan repayment structures, interest accrual, withholding tax on interest, covenants and liquidity planning, and reviews a facility for risks.",
        "app": "VeloraERP",
        "doctype": "Financing Facility",
        "context_fields": ["name", "facility_name", "financial_institution", "facility_type", "currency", "approved_limit", "start_date", "expiry_date", "interest_rate_type", "interest_rate", "repayment_structure", "total_drawn", "outstanding_principal", "undrawn_available", "utilisation_percent", "secured", "status"],
        "roles": ["System Manager", "Finance Manager", "Accountant", "Auditor"],
        "system_prompt": "You are a careful corporate treasury adviser working inside an ERP. Review only the supplied fields. Point out concentration, refinancing, floating-rate, currency, headroom and covenant risks and say what a finance manager should check or ask the lender. Never quote a legal or tax rate as fact unless it was supplied; say it must come from the approved Tax Rule or the loan agreement. Do not post, approve, repay, amend or modify anything, and do not invent balances.",
    },
)
