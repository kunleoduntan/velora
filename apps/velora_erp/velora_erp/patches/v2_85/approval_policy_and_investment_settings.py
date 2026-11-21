"""Upgrade: approval becomes a company policy in Finance Settings, and Investment Settings joins Finance Settings.

Before this release approvals were enforced in code (and by two "require approval" flags). So that nothing silently stops being
checked, an existing company keeps every approval it had: each approval document gets its sample workflow switched on and its
policy row ticked, except the manual vouchers and investments the company had switched off. The company can then change any of it
in Finance Settings > Approvals and Settings > Workflows. A new company never runs this (its policy is seeded, all unticked)."""
from sqlalchemy import inspect, text

from velora import db, get_doc, get_list
from velora.db.tables import table_name

INVESTMENT_KEYS = ("auto_accrue", "maturity_alert_days", "wht_treatment", "default_wht_rate", "max_counterparty_percent", "max_asset_group_percent",
                   "bank_account", "interest_income_account", "dividend_income_account", "rental_income_account", "accrued_income_account",
                   "deferred_income_account", "wht_receivable_account", "wht_expense_account", "realised_gain_loss_account",
                   "unrealised_gain_loss_account", "fair_value_reserve_account", "investment_expense_account")


def _first_row(doctype: str) -> dict:
    name = table_name(doctype)
    with db.transaction() as c:
        if not inspect(c).has_table(name):
            return {}
        row = c.execute(text(f'SELECT * FROM "{name}" ORDER BY creation LIMIT 1')).mappings().first()
    return dict(row) if row else {}


def execute():
    found = get_list("Finance Settings", fields=["name"], limit=1, ignore_permissions=True)
    if not found:
        return
    settings = get_doc("Finance Settings", found[0]["name"], ignore_permissions=True)
    if settings.approval_policy:
        return                                            # already on the new policy (new company, or this patch ran)
    from velora_erp.finance.approval_policy import policy_doctypes
    from velora_erp.finance.currencies import ensure_currencies
    ensure_currencies()                                   # saving Finance Settings checks its Base Currency exists; older companies may not have the currency list yet
    from velora_erp.finance.workflow_templates import install_missing
    from velora_erp.investments.settings import field_for

    legacy_finance, legacy_investment = _first_row("Finance Settings"), _first_row("Investment Settings")
    manual_vouchers_on = legacy_finance.get("require_approval_for_manual_vouchers")
    investments_on = legacy_investment.get("require_approval")
    skip = set()
    if manual_vouchers_on is not None and not int(manual_vouchers_on):
        skip |= {"Financial Voucher", "Journal Entry Voucher"}
    if investments_on is not None and not int(investments_on):
        skip |= {"Investment", "Investment Transaction"}

    install_missing(enabled=True)                         # controls that were enforced in code stay enforced
    from velora_erp.hr.workflow_templates import install_templates as install_hr_samples
    install_hr_samples(enabled=False, system=True)        # HR samples are offered, inactive: HR approvals were never enforced in code
    for doctype in policy_doctypes():
        settings.append("approval_policy", {"document_type": doctype, "require_approval": 0 if doctype in skip else 1})
    for key in INVESTMENT_KEYS:
        value = legacy_investment.get(key)
        if value not in (None, ""):
            settings.set(field_for(key), value)
    settings.save(ignore_permissions=True)
