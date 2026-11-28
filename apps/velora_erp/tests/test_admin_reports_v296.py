"""Administration and decision reports: each one runs through the real report runner on a live site and says something true."""
from datetime import date, timedelta

import pytest
import velora
from velora.meta.registry import registry
from velora.reporting import runner
from test_cash_transactions import setup_cash
from test_invoice_settlement_v271 import MAKER, T, _purchase_invoice, _sales_invoice, approve, new_doc, session_as

SLUGS = ["Access by Role", "Users and Their Roles", "Role Conflicts in Use", "Activity Pulse", "Data Quality Scorecard", "Message Delivery Health", "Pending Approvals Ageing",
         "Customer Concentration", "Supplier Dependency", "Cash Outlook", "Collections Priority", "Sales and Purchases Trend", "Customer Segments", "Business Pulse"]


def _old_invoice(accounts, customer, amount, age=60, due_after=15):
    with session_as(MAKER):
        inv = new_doc("Sales Invoice", invoice_date=T - timedelta(days=age), posting_date=T - timedelta(days=age), due_date=T - timedelta(days=age - due_after), party=customer.name, currency="NGN", exchange_rate=1,
                      narration="Old", lines=[{"description": "Service", "quantity": 1, "rate": amount, "amount": amount, "account": accounts["4000"].name}]).insert()
    return approve(inv)


def run(name, **f):
    return runner.run_definition(registry.report(name), f)


def test_every_report_is_registered_with_a_role_and_runs_on_an_empty_site(tmp_path):
    setup_cash(tmp_path)
    try:
        for name in SLUGS:
            d = registry.report(name)
            assert d.module == "Administration" and "System Manager" in d.roles, name
            assert run(name) is not None, name
    finally:
        velora.shutdown()


def test_decision_reports_read_the_books(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        _sales_invoice(accounts, customer, 1000)
        _old_invoice(accounts, customer, 500)                              # invoiced 60 days ago, due 45 days ago
        _purchase_invoice(accounts, supplier, 300)
        conc = run("Customer Concentration")
        assert [r.values["band"] for r in conc.rows] == ["A"] and conc.rows[0].values["share"] == 100.0 and any("100.0%" in n for n in conc.notes)
        dep = run("Supplier Dependency")
        assert dep.rows[0].values["amount"] == 300 and any("second source" in n for n in dep.notes)
        cash = {r.values["when"]: r.values for r in run("Cash Outlook").rows}
        assert cash["Overdue"]["inflow"] == 500 and cash["Due in 0-30 days"]["inflow"] == 1000 and cash["Due in 0-30 days"]["outflow"] == 300
        col = run("Collections Priority")
        assert len(col.rows) == 1 and col.rows[0].values["late"] == 45 and col.rows[0].values["left"] == 500 and "reminder" in col.rows[0].values["action"]
        seg = run("Customer Segments")
        assert seg.rows[0].values["segment"] in ("New", "Occasional", "Loyal") and seg.rows[0].values["orders"] == 2
        trend = run("Sales and Purchases Trend", months=3)
        assert trend.rows[-1].values["sales"] == 1000 and trend.rows[-1].values["purchases"] == 300 and sum(r.values["sales"] for r in trend.rows) == 1500
        pulse = {r.values["metric"]: r.values for r in run("Business Pulse").rows}
        assert pulse["Customers owe you"]["now"] == 1500 and pulse["...of which overdue"]["now"] == 500
    finally:
        velora.shutdown()


def test_admin_reports_see_users_roles_and_gaps(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        from sqlalchemy import insert
        from velora import db
        from velora.db.system import company_user_role, role_conflict
        with db.transaction() as c:
            c.execute(insert(company_user_role).values(user_email="boss@x.com", roles=["System Manager"], granted_by="cli"))
            c.execute(insert(company_user_role).values(user_email="clerk@x.com", roles=["Accounts Preparer", "Accounts Approver"], granted_by="boss@x.com"))
            c.execute(insert(company_user_role).values(user_email="idle@x.com", roles=[], granted_by="boss@x.com"))
            c.execute(insert(role_conflict).values(role_a="Accounts Preparer", role_b="Accounts Approver", reason="Maker and checker must differ"))
        users = {r.values["user"]: r.values for r in run("Users and Their Roles").rows}
        assert "System Manager" in users["boss@x.com"]["flag"] and "No role" in users["idle@x.com"]["flag"] and users["clerk@x.com"]["flag"] == ""
        assert len(run("Users and Their Roles", only_flagged=1).rows) == 2
        conf = run("Role Conflicts in Use")
        assert [r.values["user"] for r in conf.rows] == ["clerk@x.com"]
        matrix = run("Access by Role")
        assert matrix.rows and all(r.values["level"] for r in matrix.rows)
        dq = run("Data Quality Scorecard")
        assert {r.values["entity"] for r in dq.rows} >= {"Customer", "Supplier"}
        assert any(r.values["missing"] >= 1 for r in dq.rows)
    finally:
        velora.shutdown()
