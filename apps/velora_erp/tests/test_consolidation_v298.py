"""Consolidation on the real platform: two companies in separate databases, read only through the signed-in person's own access."""
import os
import sys
from datetime import date
from decimal import Decimal

import pytest
import velora
from velora import get_doc, new_doc
from velora import site as site_mod
from velora.controlplane import ControlPlane
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora.workspace import Workspace
from velora_erp.finance.engine import post_financial_transaction

PW = "correct horse battery"
APPS = ["velora_notify", "velora_projectone", "velora_erp"]
TODAY = date.today()


@pytest.fixture
def platform(tmp_path, monkeypatch):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    monkeypatch.delenv("VELORA_WORKSPACE", raising=False)
    path_before, mods_before = list(sys.path), set(sys.modules)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    ws.apps_dir.mkdir(parents=True, exist_ok=True)
    for app in APPS:
        (ws.apps_dir / app).symlink_to(os.path.join(root, app), target_is_directory=True)
        ws.register_app(app)
    ws.activate()
    plane = ControlPlane.create(ws, admin_email="root@example.com", admin_password=PW)
    plane.registry.create_tenant("Group")
    from velora import apps as apps_mod
    A = plane.provisioning.provision_company("Group", "Parent Ltd", apps=["velora_notify"])
    B = plane.provisioning.provision_company("Group", "Subsidiary Inc", apps=["velora_notify"])
    for co in (A, B):                                                      # VeloraERP and ProjectOne need each other, so they go in together
        site = plane.router.site_for(plane.registry.get_company(co["id"]))
        apps_mod.install_app(ws, site, "velora_erp", together=["velora_projectone"])
    idn = plane.identity
    for who in ("alice@example.com", "bob@example.com"): idn.create_user(who, who.split("@")[0], PW)
    idn.grant("alice@example.com", A["id"], ["Finance Manager"]); idn.grant("alice@example.com", B["id"], ["Finance Manager"])
    idn.grant("bob@example.com", A["id"], ["Finance Manager"])                                   # Bob cannot enter the subsidiary
    yield plane, A, B
    site_mod.unload_all(); velora.shutdown()
    sys.path[:] = path_before
    for n in set(sys.modules) - mods_before:
        if "velora_erp" in n: sys.modules.pop(n, None)


def seed(currency, postings):
    """A tiny chart, an open year and some balanced postings, inside the company currently open."""
    s = get_doc("Finance Settings", "Primary Finance Settings") if velora.get_list("Finance Settings", limit=1) else None
    if s is not None:
        s.base_currency = currency; s.save(ignore_permissions=True)
    year = TODAY.year
    new_doc("Financial Year", year_name=f"FY-{year}", start_date=date(year, 1, 1), end_date=date(year, 12, 31), status="Open", is_current=1).insert(ignore_permissions=True)
    new_doc("Financial Period", period_name=f"FY-{year}-P01", financial_year=f"FY-{year}", period_number=1, start_date=date(year, 1, 1), end_date=date(year, 12, 31), status="Open").insert(ignore_permissions=True)
    for code, label, root in (("ASSET", "Assets", "Asset"), ("LIAB", "Liabilities", "Liability"), ("EQUITY", "Equity", "Equity"), ("INCOME", "Income", "Income"), ("EXPENSE", "Expenses", "Expense")):
        new_doc("Account Group", group_code=code, group_name=label, root_type=root, is_group=0).insert(ignore_permissions=True)
    acc = {}
    for code, name, group, typ in (("1000", "Bank", "ASSET", "BANK"), ("1200", "Intercompany Receivable", "ASSET", "ACCRUED_INCOME"), ("2100", "Intercompany Payable", "LIAB", "ACCRUAL"),
                                   ("3000", "Share Capital", "EQUITY", "EQUITY"), ("4000", "Revenue", "INCOME", "REVENUE"), ("5000", "Costs", "EXPENSE", "OPERATING_EXPENSE")):
        acc[code] = new_doc("Account", account_code=code, account_name=name, account_group=group, account_type=typ, allow_manual_posting=1).insert(ignore_permissions=True).name
    for i, lines in enumerate(postings):
        post_financial_transaction(source_doctype="Test Source", source_name=f"T-{i}", posting_date=TODAY, currency=currency,
                                   lines=[{"account": acc[c], "debit": d, "credit": cr} for c, d, cr in lines])
    return acc


def host_group(members, rules=()):
    g = new_doc("Consolidation Group", group_name="Whole Group", presentation_currency="NGN", tolerance=1)
    for m in members: g.append("members", m)
    for r in rules: g.append("eliminations", r)
    return g.insert(ignore_permissions=True)


def test_two_companies_in_two_databases_are_consolidated_with_eliminations_and_a_translated_member(platform):
    plane, A, B = platform
    with plane.company_scope(B["id"]):
        seed("USD", [[("1000", 500, 0), ("3000", 0, 300), ("4000", 0, 200)], [("5000", 50, 0), ("1000", 0, 50)], [("1000", 10, 0), ("2100", 0, 10)]])
        new_doc("Currency Exchange Rate", from_currency="USD", to_currency="NGN", effective_date=date(TODAY.year, 1, 1), rate=1500).insert(ignore_permissions=True)
    with plane.company_scope(A["id"]):
        seed("NGN", [[("1000", 1000000, 0), ("3000", 0, 1000000)], [("1200", 15000, 0), ("1000", 0, 15000)], [("1000", 100000, 0), ("4000", 0, 100000)]])
        g = host_group([{"company_id": A["id"], "ownership_percent": 100}, {"company_id": B["id"], "ownership_percent": 100}],
                       [{"description": "Loan to subsidiary", "rule_type": "Intercompany balance", "company_one": A["id"], "account_one": "1200", "company_two": B["id"], "account_two": "2100"}])
    with plane.company_scope(A["id"], "alice@example.com", ("Finance Manager",)):
        from velora_erp.finance.consolidation_service import run_consolidation
        r = run_consolidation("Whole Group", date(TODAY.year, 1, 1), TODAY, save=True)
    by = {l["key"]: l for l in r["lines"]}
    assert by["1000"]["cells"][A["id"]] == 1085000                                   # 1,000,000 - 15,000 + 100,000
    assert by["1000"]["cells"][B["id"]] == (500 - 50 + 10) * 1500                   # translated at the closing rate
    assert by["1200"]["total"] == 0 and by["2100"]["total"] == 0                       # 10 USD = 15,000 NGN on both sides: eliminated
    assert not [c for c in r["checks"] if c["code"] == "difference"]
    assert r["saved_as"].startswith("CNR-")
    assert abs(sum(l["total"] for l in r["lines"])) < 0.01                           # the consolidated trial balance balances
    assert r["balance_sheet"]["check"] == 0


def test_a_member_the_person_cannot_enter_is_left_out_and_reported_never_read(platform):
    plane, A, B = platform
    with plane.company_scope(B["id"]):
        seed("NGN", [[("1000", 500, 0), ("3000", 0, 500)]])
    with plane.company_scope(A["id"]):
        seed("NGN", [[("1000", 1000, 0), ("3000", 0, 1000)]])
        host_group([{"company_id": A["id"], "ownership_percent": 100}, {"company_id": B["id"], "ownership_percent": 100}])
    from velora_erp.finance.consolidation_service import run_consolidation
    with plane.company_scope(A["id"], "bob@example.com", ("Finance Manager",)):
        r = run_consolidation("Whole Group", date(TODAY.year, 1, 1), TODAY)
    assert {l["key"]: l for l in r["lines"]}["1000"]["total"] == 1000                # only Parent's money
    assert any(c["code"] == "member_unavailable" and c["company"] == B["id"] for c in r["checks"]) and r["ok"] is False


def test_a_missing_exchange_rate_stops_that_member_instead_of_guessing(platform):
    plane, A, B = platform
    with plane.company_scope(B["id"]):
        seed("USD", [[("1000", 5, 0), ("3000", 0, 5)]])                              # no USD to NGN rate anywhere
    with plane.company_scope(A["id"]):
        seed("NGN", [[("1000", 1000, 0), ("3000", 0, 1000)]])
        host_group([{"company_id": A["id"]}, {"company_id": B["id"]}])
    from velora_erp.finance.consolidation_service import run_consolidation
    with plane.company_scope(A["id"], "alice@example.com", ("Finance Manager",)):
        r = run_consolidation("Whole Group", date(TODAY.year, 1, 1), TODAY)
    assert any("No exchange rate" in c["message"] for c in r["checks"])


def test_group_rules_reject_a_company_that_is_not_a_member(platform):
    plane, A, B = platform
    with plane.company_scope(A["id"]):
        with pytest.raises(Exception, match="not a member"):
            host_group([{"company_id": A["id"]}], [{"description": "x", "company_one": A["id"], "account_one": "1", "company_two": "someone-else", "account_two": "2"}])
