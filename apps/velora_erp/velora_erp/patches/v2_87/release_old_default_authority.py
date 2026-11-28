"""Upgrade: the built-in role lists for "other powers" (reverse a posting, override a budget, ...) are gone.

Earlier releases wrote their default roles into Finance Settings > Approvals, so an existing company still holds them as if it had
chosen them. Any row that still equals the old built-in list is emptied (= anyone whose role permissions allow the action). A list
the company edited itself is left alone."""
from sqlalchemy import inspect, select, update

from velora import db
from velora.db.tables import get_table, table_name

OLD_DEFAULTS = {
    "financial_document.reverse": {"Finance Manager", "System Manager"},
    "budget.override": {"Finance Manager", "System Manager"},
    "reporting_workbench.approve": {"Finance Manager", "System Manager"},
    "reporting_case.submit": {"Preparer", "Finance Manager"},
    "reporting_case.review": {"Reviewer", "Finance Manager", "CFO"},
    "reporting_case.approve_publication": {"Approver", "CFO", "Board Secretary"},
    "reporting_case.publish": {"Publisher", "CFO"},
    "hr_policy.approve": {"HR Manager", "System Manager"},
}


def _roles(text) -> set[str]:
    return {r.strip() for r in str(text or "").split(",") if r.strip()}


def _clear_rows() -> None:
    with db.transaction() as c:
        if not inspect(c).has_table(table_name("Authority Policy Row")):
            return                                                   # a bare framework site: only the settings store exists
    table = get_table("Authority Policy Row")
    with db.transaction() as c:
        for name, action, roles in c.execute(select(table.c.name, table.c.action, table.c.roles)).all():
            if OLD_DEFAULTS.get(action) == _roles(roles):
                c.execute(update(table).where(table.c.name == name).values(roles=""))


def execute():
    _clear_rows()
    from velora.settings import get_setting, set_setting
    from velora_erp.finance.approval_authority import SETTING_KEY
    stored = dict(get_setting(SETTING_KEY, {}) or {})
    kept = {k: v for k, v in stored.items() if OLD_DEFAULTS.get(k) != set(v or [])}
    if kept != stored:
        set_setting(SETTING_KEY, kept)
