"""VeloraERP application lifecycle and compatibility declarations."""
app_title = "VeloraERP"
app_description = "Integrated enterprise core: finance, inventory, assets, budgets, sales, purchasing, payroll and human resources."
required_apps = []
required_velora = ">=1.13.0,<1.14.0"
required_packages = []

# The framework financial statement designer reads the VeloraERP Account Ledger
# through this provider contract, not through legacy GL Entry tables.
financial_reporting_provider = "velora_erp.finance.reporting_provider"
after_install = "velora_erp.setup.after_install"
after_migrate = "velora_erp.setup.after_migrate"
setup_readiness_provider = "velora_erp.configuration"
before_uninstall = None
# One cancel routine for every document type: it removes the posting, unlinks what hangs on the document and writes the log.
doc_events = {
    "*": {
        "before_submit": "velora_erp.finance.restore_points.capture",
        "on_submit": "velora_erp.finance.restore_points.capture_after",
        "on_cancel": "velora_erp.finance.cancellation.on_any_cancel",
    },
}

# Plain-field links (source_doctype + source_document) that stop a document being cancelled while another submitted document uses it.
linked_documents_provider = "velora_erp.finance.links"

# Starter approval workflows (installed from Settings > Workflows; nothing is installed automatically).
workflow_template_provider = ["velora_erp.finance.workflow_templates", "velora_erp.hr.workflow_templates"]
approval_policy_provider = "velora_erp.finance.approval_policy"

# What can be copied from one company to another (Settings > Setup Copy).
setup_copy_provider = "velora_erp.setup_copy"

# Record scopes for row policies (own employee, department staff, managed departments).
row_scope_provider = "velora_erp.hr.scopes"
scheduler_events = {
    "every_minute": ["velora_erp.hr.attendance_integrations.run_scheduled_attendance_syncs", "velora_erp.support.jobs.check_sla"],
    "hourly": ["velora_erp.finance.bank_reconciliation.run_scheduled_reconciliation"],
    "daily": ["velora_erp.finance.recognition.schedules.process_due_recognitions", "velora_erp.finance.doctype.accrual.accrual.process_due_accrual_reversals",
              "velora_erp.investments.jobs.accrue_month_end", "velora_erp.investments.jobs.watch_maturities", "velora_erp.support.jobs.auto_close",
              "velora_erp.finance.inventory.expiry.watch_expiry", "velora_erp.finance.inventory.reservations.expire_due", "velora_erp.finance.inventory.procurement.expire_quotations"],
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
        "id": "veloraerp.sales.invoice.reviewer",
        "title": "Sales Invoice Review Advisor",
        "description": "Reviews an authorised Sales Invoice for completeness, unusual values and potential control issues.",
        "app": "VeloraERP",
        "doctype": "Sales Invoice",
        "context_fields": ["name", "customer", "posting_date", "due_date", "currency", "grand_total", "total_taxes_and_charges", "status", "docstatus"],
        "roles": ["System Manager", "Accounts Manager", "Accounts User", "Sales Manager", "Auditor"],
        "system_prompt": "You are a cautious invoice review advisor. Review only the supplied permitted fields. Identify missing information, arithmetic or date anomalies, and questions a human reviewer should investigate. Do not decide whether to approve or post. Never infer that an invoice is fraudulent from an anomaly alone.",
    },
)
