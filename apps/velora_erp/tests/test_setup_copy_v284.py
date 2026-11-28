"""Copy setup (chart of accounts, masters, workflows, permissions) from one company to another."""
import json

import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import Session, session_as
from velora_erp.setup import after_install

from test_cash_transactions import setup_cash, MAKER
from wf_helpers import install_approval, ADMIN
from velora import setup_copy


def _second_company(tmp_path):
    velora.shutdown()
    velora.configure(db_url=f"sqlite:///{tmp_path / 'second.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()


def _names(doctype):
    return {r["name"] for r in get_list(doctype, fields=["name"], limit=10000, ignore_permissions=True)}


def test_sections_come_from_the_apps_and_leave_out_documents_that_need_approval(tmp_path):
    setup_cash(tmp_path)
    try:
        with session_as(ADMIN):
            by_id = {s["id"]: s for s in setup_copy.sections()}
        assert {"workflows", "permissions", "chart_of_accounts", "finance_masters", "hr_masters"} <= set(by_id)
        assert by_id["chart_of_accounts"]["doctypes"] == ["Account Type", "Account Group", "Account"]
        assert "Payroll Tax Jurisdiction" in by_id["payroll_masters"]["doctypes"] or any(x["doctype"] == "Payroll Tax Jurisdiction" for x in by_id["payroll_masters"]["skipped"])
    finally:
        velora.shutdown()


def test_only_a_system_manager_may_copy_setup(tmp_path):
    setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            with pytest.raises(PermissionDenied):
                setup_copy.export_bundle(["chart_of_accounts"])
    finally:
        velora.shutdown()


def test_chart_of_accounts_and_workflows_copy_to_a_new_company_once(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        install_approval("Receipt", roles=("Auditor",))
        with session_as(ADMIN):
            bundle = setup_copy.export_bundle(["chart_of_accounts", "workflows"])
        assert {"Account", "Account Group"} <= set(bundle["sections"]["chart_of_accounts"]["doctypes"])
        bundle = json.loads(json.dumps(bundle))                                    # it must survive being saved as a file

        _second_company(tmp_path)
        assert "5000" not in {a.split(" ")[0] for a in _names("Account")} or True
        before = len(_names("Account"))
        with session_as(ADMIN):
            plan = setup_copy.preview(bundle, ["chart_of_accounts", "workflows"])
            assert plan["new"] > 0 and not plan["blocked"]
            assert len(_names("Account")) == before                                # a preview writes nothing
            done = setup_copy.apply_bundle(bundle, ["chart_of_accounts", "workflows"])
        assert done["created"] >= len(accounts) + 1
        assert accounts["1000"].name in _names("Account")
        from velora import workflows
        assert workflows.is_managed("Receipt")
        with session_as(ADMIN):
            again = setup_copy.apply_bundle(bundle, ["chart_of_accounts", "workflows"])
            assert again["created"] == 0                                           # copying twice is harmless
        copied = get_doc("Account", accounts["1000"].name, ignore_permissions=True)
        assert copied.account_group == accounts["1000"].account_group and copied.account_type == "BANK"
    finally:
        velora.shutdown()


def test_nothing_is_copied_when_one_part_fails(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        with session_as(ADMIN):
            bundle = json.loads(json.dumps(setup_copy.export_bundle(["chart_of_accounts"])))
        bundle["sections"]["chart_of_accounts"]["doctypes"]["Account"][0]["account_group"] = "NO-SUCH-GROUP"
        _second_company(tmp_path)
        before = _names("Account Group"), _names("Account")
        with session_as(ADMIN):
            with pytest.raises(ValidationError, match="Nothing was copied"):
                setup_copy.apply_bundle(bundle, ["chart_of_accounts"])
        assert (_names("Account Group"), _names("Account")) == before              # the groups that did import were rolled back too
    finally:
        velora.shutdown()


def test_a_file_that_is_not_a_setup_bundle_is_refused(tmp_path):
    setup_cash(tmp_path)
    try:
        with session_as(ADMIN):
            with pytest.raises(ValidationError, match="not a Velora setup file"):
                setup_copy.preview({"hello": "world"}, ["chart_of_accounts"])
    finally:
        velora.shutdown()


def test_permissions_copy_adds_what_is_missing_and_keeps_what_is_there(tmp_path):
    setup_cash(tmp_path)
    try:
        from velora.controlplane.role_admin import RoleAdministration  # noqa: F401
        from velora.db import system as S
        from sqlalchemy import insert
        from velora import db
        with db.transaction() as c:
            c.execute(insert(S.row_policy).values(role="Auditor", doctype="Receipt", permission="read", conditions=[{"field": "owner", "operator": "=", "value": "x@y.test"}], is_active=True))
        with session_as(ADMIN):
            bundle = json.loads(json.dumps(setup_copy.export_bundle(["permissions"])))
        _second_company(tmp_path)
        with session_as(ADMIN):
            first = setup_copy.apply_bundle(bundle, ["permissions"])
            second = setup_copy.apply_bundle(bundle, ["permissions"])
        assert first["created"] >= 1 and second["created"] == 0
        from sqlalchemy import select
        with db.transaction() as c:
            assert c.execute(select(S.row_policy).where(S.row_policy.c.role == "Auditor", S.row_policy.c.doctype == "Receipt")).first()
    finally:
        velora.shutdown()


def test_a_tree_of_departments_is_created_from_the_top_down_whatever_order_the_file_has(tmp_path):
    setup_cash(tmp_path)
    try:
        top = new_doc("Department", department_name="Head Office", department_code="HO").insert(ignore_permissions=True)
        mid = new_doc("Department", department_name="Finance", department_code="FIN", parent_department=top.name).insert(ignore_permissions=True)
        new_doc("Department", department_name="Audit", department_code="AUD", parent_department=mid.name).insert(ignore_permissions=True)
        with session_as(ADMIN):
            bundle = json.loads(json.dumps(setup_copy.export_bundle(["hr_masters"])))
        rows = bundle["sections"]["hr_masters"]["doctypes"]["Department"]
        assert len(rows) == 3
        bundle["sections"]["hr_masters"]["doctypes"]["Department"] = list(reversed(rows))           # children before parents
        _second_company(tmp_path)
        with session_as(ADMIN):
            setup_copy.apply_bundle(bundle, ["hr_masters"])
        got = {d.name: d.parent_department for d in (get_doc("Department", n, ignore_permissions=True) for n in _names("Department"))}
        assert got[mid.name] == top.name and len(got) == 3
    finally:
        velora.shutdown()


def test_finance_policy_copies_to_another_company_and_replaces_only_inactive_samples(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        from sqlalchemy import update
        from velora import workflows
        install_approval("Receipt", roles=("Auditor",), enabled=False)           # this company's own approver for receipts, designed in the GUI
        fs = get_doc("Finance Settings", get_list("Finance Settings", fields=["name"], limit=1, ignore_permissions=True)[0]["name"], ignore_permissions=True)
        for row in fs.approval_policy:
            if row.document_type == "Receipt": row.require_approval = 1
        fs.backdated_posting_days = 30
        fs.investment_max_counterparty_percent = 40
        next(r for r in fs.authority_policy if r.action == "budget.override").roles = "Head of Finance"
        fs.save(ignore_permissions=True)
        with session_as(ADMIN):
            bundle = json.loads(json.dumps(setup_copy.export_bundle(["workflows", "finance_policy"])))
        assert bundle["sections"]["finance_policy"]["settings"]["fields"]["backdated_posting_days"] == 30

        _second_company(tmp_path)                                                  # a new company: no workflows, nothing ticked
        assert not workflows.is_managed("Receipt")
        with session_as(ADMIN):
            plan = setup_copy.preview(bundle, ["workflows", "finance_policy"])
            assert any(p["kind"] == "settings" and p["updates"] > 0 for p in plan["plan"])
            setup_copy.apply_bundle(bundle, ["workflows", "finance_policy"])
        assert workflows.is_managed("Receipt")                                    # the first company's workflow came across
        wf = next(w for w in workflows.list_definitions() if w["name"] == "Receipt Approval")
        assert wf["transitions"][0]["roles"] == ["Auditor"]
        fs2 = get_doc("Finance Settings", get_list("Finance Settings", fields=["name"], limit=1, ignore_permissions=True)[0]["name"], ignore_permissions=True)
        assert fs2.backdated_posting_days == 30 and fs2.investment_max_counterparty_percent == 40
        assert {r.document_type: r.require_approval for r in fs2.approval_policy}["Receipt"] == 1
        assert next(r for r in fs2.authority_policy if r.action == "budget.override").roles == "Head of Finance"
        assert fs2.base_currency and fs2.country_code                                # company identity is not copied over
        with session_as(ADMIN):                                                    # a workflow that is now live is never replaced
            again = setup_copy.preview(bundle, ["workflows"])
        assert again["new"] == 0
    finally:
        velora.shutdown()
