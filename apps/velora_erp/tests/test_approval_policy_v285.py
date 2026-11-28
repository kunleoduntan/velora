"""v2.85: Finance Settings holds the company's approval policy; workflows are only the route.

* a new company gets no starter workflows and every policy row unticked;
* ticking a document in Finance Settings > Approvals switches on the workflow the company designed (and refuses if there is none);
* unticking it approves documents on save and switches the workflow off;
* a workflow switched on or off in the designer moves the policy the same way;
* "required but no active workflow" is reported, never silently ignored;
* Investment Settings now lives on the Investments tab of Finance Settings.
"""
from datetime import date

import pytest
import velora
from velora import get_doc, get_list
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora import workflows

from test_cash_transactions import setup_cash, MAKER, APPROVER
from test_finance_workflow_v284 import receipt, HEAD
from wf_helpers import ADMIN, install_approval


def settings():
    name = get_list("Finance Settings", fields=["name"], limit=1, ignore_permissions=True)[0]["name"]
    return get_doc("Finance Settings", name, ignore_permissions=True)


def tick(doctype, on):
    fs = settings()
    for row in fs.approval_policy:
        if row.document_type == doctype:
            row.require_approval = 1 if on else 0
    fs.save(ignore_permissions=True)


def row(doctype):
    return next(r for r in settings().approval_policy if r.document_type == doctype)


def test_a_new_company_starts_with_every_policy_row_unticked_and_no_starter_workflows(tmp_path):
    setup_cash(tmp_path)
    try:
        rows = {r.document_type: int(r.require_approval) for r in settings().approval_policy}
        assert {"Receipt", "Payment", "Payroll Run", "Financial Voucher", "Journal Entry Voucher", "Investment"} <= set(rows)
        assert not any(rows.values())
        assert not any(workflows.list_for_doctype(d) for d in rows)                         # no starter workflows: each company designs its own
        assert not any(workflows.is_managed(d) for d in rows)
    finally:
        velora.shutdown()


def test_ticking_a_document_switches_on_its_workflow_and_unticking_switches_it_off(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        assert receipt(accounts).approval_status == "Approved"                              # unticked: approved on save
        with pytest.raises(ValidationError, match="no workflow exists"):
            tick("Receipt", True)                                                           # nothing designed yet: the company must create one first
        install_approval("Receipt", enabled=False)                                          # the company designs its workflow in the GUI
        tick("Receipt", True)
        assert workflows.is_managed("Receipt") and workflows.has_enabled_workflow("Receipt")
        r = receipt(accounts)
        assert r.approval_status == "Pending"
        with pytest.raises(ValidationError, match="approval"):
            get_doc("Receipt", r.name).submit(ignore_permissions=True)
        tick("Receipt", False)
        assert not workflows.has_enabled_workflow("Receipt") and not workflows.is_managed("Receipt")
        assert receipt(accounts).approval_status == "Approved"
    finally:
        velora.shutdown()


def test_ticking_never_creates_a_workflow_for_the_company(tmp_path):
    setup_cash(tmp_path)
    try:
        assert workflows.list_for_doctype("Receipt") == []
        with pytest.raises(ValidationError, match="no workflow exists"):
            tick("Receipt", True)
        assert workflows.list_for_doctype("Receipt") == [] and row("Receipt").require_approval == 0
    finally:
        velora.shutdown()


def test_the_designer_and_the_policy_never_disagree(tmp_path):
    setup_cash(tmp_path)
    try:
        install_approval("Receipt")                                                           # designer: switch it on
        assert row("Receipt").require_approval == 1
        install_approval("Receipt", enabled=False)                                            # designer: switch it off
        assert row("Receipt").require_approval == 0
    finally:
        velora.shutdown()


def test_required_without_an_active_workflow_never_blocks_the_document(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        install_approval("Receipt")
        name = workflows.enabled_names("Receipt")[0]
        workflows.set_enabled(name, False)                                                    # the company switched the workflow off
        assert workflows.approval_gap("Receipt")                                              # still reported, for information
        r = receipt(accounts)
        assert r.approval_status == "Approved"                                                # nothing governs it, so nothing holds it
        get_doc("Receipt", r.name).submit(ignore_permissions=True)                            # and it is not blocked
        assert get_doc("Receipt", r.name).docstatus == 1
    finally:
        velora.shutdown()


def test_the_policy_table_lists_only_real_approval_documents_and_restores_missing_rows(tmp_path):
    setup_cash(tmp_path)
    try:
        fs = settings()
        fs.approval_policy = []
        fs.append("approval_policy", {"document_type": "Not A Document", "require_approval": 1})
        fs.append("approval_policy", {"document_type": "Receipt", "require_approval": 0})
        fs.append("approval_policy", {"document_type": "Receipt", "require_approval": 1})
        fs.save(ignore_permissions=True)
        names = [r.document_type for r in settings().approval_policy]
        assert "Not A Document" not in names and names.count("Receipt") == 1 and "Payment" in names
    finally:
        velora.shutdown()


def test_investment_settings_live_on_the_finance_settings_investments_tab(tmp_path):
    setup_cash(tmp_path)
    try:
        from velora_erp.investments.settings import get_settings
        assert get_settings()["max_counterparty_percent"] == 25 and get_settings()["wht_treatment"] == "Tax credit (asset)"
        fs = settings()
        fs.investment_max_counterparty_percent = 40
        fs.investment_default_wht_rate = 5
        fs.save(ignore_permissions=True)
        assert get_settings()["max_counterparty_percent"] == 40 and get_settings()["default_wht_rate"] == 5
        fs = settings()
        fs.investment_default_wht_rate = 150
        with pytest.raises(ValidationError, match="between 0 and 100"):
            fs.save(ignore_permissions=True)
        from velora.meta.registry import registry
        assert "Investment Settings" not in {m.name for m in registry.all()}
    finally:
        velora.shutdown()


def test_upgrade_keeps_the_controls_a_company_had(tmp_path):
    """An existing company (no policy rows yet, an old Investment Settings record) keeps every approval it had."""
    setup_cash(tmp_path)
    try:
        from sqlalchemy import delete, text
        from velora.db.tables import get_table, table_name
        install_approval("Receipt"); install_approval("Payroll Run")                              # the company had designed and switched these on
        child = get_table("Approval Policy Row")
        legacy = table_name("Investment Settings")
        with velora.db.transaction() as c:
            c.execute(delete(child))
            c.execute(delete(get_table("Currency")))               # an older company whose currency list was never loaded
            c.execute(text(f'CREATE TABLE "{legacy}" (name VARCHAR(255), creation TIMESTAMP, require_approval INTEGER, max_counterparty_percent FLOAT, default_wht_rate FLOAT)'))
            c.execute(text(f"INSERT INTO \"{legacy}\" VALUES ('Default', '2026-01-01 00:00:00', 0, 35, 7)"))
        from velora_erp.patches.v2_85.approval_policy_and_investment_settings import execute
        execute()
        rows = {r.document_type: int(r.require_approval) for r in settings().approval_policy}
        assert rows["Receipt"] == 1 and rows["Payroll Run"] == 1 and workflows.is_managed("Receipt")        # enforced before, enforced still
        assert rows["Investment"] == 0 and rows["Investment Transaction"] == 0                              # the company had switched these off
        assert settings().investment_max_counterparty_percent == 35 and settings().investment_default_wht_rate == 7
        execute()                                                                                           # running it twice changes nothing
        assert {r.document_type: int(r.require_approval) for r in settings().approval_policy} == rows
    finally:
        velora.shutdown()


def test_other_powers_are_set_in_finance_settings(tmp_path):
    setup_cash(tmp_path)
    try:
        from velora_erp.finance import approval_authority as aa
        rows = {r.action: r.roles for r in settings().authority_policy}
        assert set(rows) == set(aa.DEFAULTS) and rows["budget.override"] == ""                  # nobody is named by code
        fs = settings()
        next(r for r in fs.authority_policy if r.action == "budget.override").roles = "Budget Committee, Head of Finance"
        fs.save(ignore_permissions=True)
        assert aa.is_authorised("budget.override", roles=("Head of Finance",)) and not aa.is_authorised("budget.override", roles=("Finance Manager",))
        assert aa.is_authorised("budget.override", user="Administrator")                       # the built-in administrator is never locked out
        fs = settings()
        next(r for r in fs.authority_policy if r.action == "budget.override").roles = " , "   # blank = anyone with permission
        fs.save(ignore_permissions=True)
        assert aa.is_authorised("budget.override", roles=("Finance Manager",))
        with session_as(ADMIN):
            aa.set_authority("hr_policy.approve", ["HR Director"])                              # the API and the settings page are the same record
        assert next(r for r in settings().authority_policy if r.action == "hr_policy.approve").roles == "HR Director"
        with session_as(ADMIN):
            aa.reset_authority("hr_policy.approve")
        assert aa.roles_for("hr_policy.approve") == ()
    finally:
        velora.shutdown()
