"""ProjectOne running on a real Velora site next to VeloraERP: one Project record, framework permissions, no company field."""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import velora
from velora import new_doc
from velora.api import create_app

BOSS = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
MEMBER = {"X-Velora-User": "pat", "X-Velora-Roles": "Project User"}
AUDITOR = {"X-Velora-User": "aud", "X-Velora-Roles": "Auditor"}
PROJECT = {"title": "Head Office Build", "project_code": "hob-1", "project_manager": "pat", "currency": "NGN",
           "start_date": "2026-01-01", "end_date": "2026-12-31", "approved_budget": 5000000}


@pytest.fixture()
def site(tmp_path):
    pg = os.environ.get("VELORA_P1_TEST_PG_URL")        # set to run these tests on PostgreSQL instead of SQLite
    velora.configure(db_url=pg or f"sqlite:///{tmp_path / 'p1.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init()
    if pg:
        from sqlalchemy import MetaData
        from velora import db
        with db.transaction() as conn:
            md = MetaData()
            md.reflect(conn)
            md.drop_all(conn)
    velora.migrate()
    from velora_erp.setup import after_install
    from velora_projectone.setup import after_install as projects_install
    after_install()
    projects_install()
    yield TestClient(create_app())
    velora.shutdown()


def create(client, doctype, document, key, headers=BOSS):
    return client.post(f"/api/projectone/native/documents/{doctype}", json={"document": document, "idempotency_key": key}, headers=headers)


def test_no_doctype_carries_a_company_field():
    root = Path(__file__).resolve().parents[1] / "velora_projectone" / "projectone" / "doctype"
    for path in root.glob("*/*.json"):
        fields = json.loads(path.read_text())["fields"]
        assert not [f for f in fields if f["fieldname"] == "company" or f.get("options") == "Company"], path.name


def test_there_is_one_project_doctype_and_erp_links_to_it(site):
    from velora.meta.registry import registry
    assert registry.get("Project").app == "velora_projectone"
    assert {"project"} <= {f.fieldname for f in registry.get("Journal Entry Voucher Line").fields}
    assert registry.get("Journal Entry Voucher Line").get_field("project").options == "Project"


def test_project_is_created_once_per_request_key_and_found_by_link_search(site):
    first = create(site, "Project", PROJECT, "k-1")
    again = create(site, "Project", PROJECT, "k-1")
    assert first.status_code == 200 and first.json()["data"]["name"] == "HOB-1"
    assert again.json()["data"]["name"] == "HOB-1"
    assert create(site, "Project", {**PROJECT, "title": "Other"}, "k-1").status_code == 422     # same key, different content
    found = site.get("/api/search-link", params={"doctype": "Project", "txt": "hob"}, headers=BOSS).json()["data"]
    assert [row["name"] for row in found] == ["HOB-1"]


def test_permissions_follow_the_doctype_roles(site):
    assert create(site, "Project", PROJECT, "k-1").status_code == 200
    assert create(site, "Project", {**PROJECT, "project_code": "X-2"}, "k-2", AUDITOR).status_code == 403
    assert site.get("/api/projectone/native/documents/Project", headers=AUDITOR).status_code == 200
    task = {"project": "HOB-1", "task_code": "T1", "title": "Foundation", "planned_start": "2026-02-01", "planned_finish": "2026-03-01"}
    assert create(site, "Project Task", task, "t-1", MEMBER).status_code == 200
    assert create(site, "Project Task", {**task, "task_code": "T2", "planned_finish": "2026-01-01"}, "t-2", MEMBER).status_code == 422


def test_update_needs_the_current_version(site):
    saved = create(site, "Project", PROJECT, "k-1").json()["data"]
    url = "/api/projectone/native/documents/Project/HOB-1"
    ok = site.put(url, json={"document": {"description": "Phase one"}, "expected_version": saved["version"]}, headers=BOSS)
    assert ok.status_code == 200 and ok.json()["data"]["description"] == "Phase one"
    stale = site.put(url, json={"document": {"description": "Late"}, "expected_version": saved["version"]}, headers=BOSS)
    assert stale.status_code == 422


def test_workbench_inbox_and_executive_workspace_answer(site):
    create(site, "Project", PROJECT, "k-1")
    create(site, "Project Task", {"project": "HOB-1", "task_code": "T1", "title": "Foundation"}, "t-1", MEMBER)
    board = site.get("/api/projectone/workbench/projects/HOB-1", headers=MEMBER)
    assert board.status_code == 200 and board.json()["data"]["total"] == 1
    assert site.get("/api/projectone/native/workflow-inbox", headers=MEMBER).json() == {"data": []}
    assert site.get("/api/projectone/portfolio/executive-workspace", headers=BOSS).status_code == 200
    assert site.get("/api/projectone/health", headers=BOSS).json()["data"]["status"] == "available"
    assert site.get("/api/projectone/integrations/readiness", headers=BOSS).json()["data"]["native"]["production_ready"] is True


def test_erp_postings_on_a_project_reach_the_executive_workspace(site):
    from velora.document.document import get_table
    from velora import db
    create(site, "Project", PROJECT, "k-1")
    table = get_table("Account Ledger Record")
    with db.transaction() as conn:
        conn.execute(table.insert(), [{"name": "ALR-1", "entry_key": "e1", "source_doctype": "Journal Entry Voucher", "source_name": "JV-1",
            "posting_date": __import__("datetime").date(2026, 3, 1), "project": "HOB-1", "base_currency": "NGN", "base_debit": 700, "base_credit": 0,
            "account_name_snapshot": "Site Materials", "root_type_snapshot": "Expense"}])
    data = site.get("/api/projectone/portfolio/executive-workspace", headers=BOSS).json()["data"]
    naira = next(row for row in data["financial_by_currency"] if row["currency"] == "NGN")
    assert naira["actual_cost"] == 700 and naira["approved_budget"] == 5000000


def test_a_role_that_only_fills_documents_can_still_pick_from_a_master(site):
    new_doc("Business Unit", business_unit_code="BU1", business_unit_name="Head Office").insert(ignore_permissions=True)
    picker = {"X-Velora-User": "acc", "X-Velora-Roles": "Accountant"}
    assert site.get("/api/search-link", params={"doctype": "Business Unit", "txt": "head"}, headers=picker).status_code == 200
    assert site.get("/api/search-link", params={"doctype": "Payroll Run", "txt": ""}, headers=picker).status_code == 403




def test_programme_intelligence_reads_real_records(site):
    from velora import get_list
    new_doc("Project Programme", programme_name="Campus", status="Open").insert(ignore_permissions=True)
    programme = get_list("Project Programme", fields=["name"])[0]["name"]
    new_doc("Project", **{**PROJECT, "programme": programme}).insert(ignore_permissions=True)
    a = new_doc("Project Task", project="HOB-1", task_code="T1", title="Foundation", planned_start="2026-01-05", planned_finish="2026-01-09", duration_days=5).insert(ignore_permissions=True)
    b = new_doc("Project Task", project="HOB-1", task_code="T2", title="Walls", planned_start="2026-01-12", planned_finish="2026-01-16", duration_days=5).insert(ignore_permissions=True)
    new_doc("Task Dependency", project="HOB-1", predecessor=a.name, successor=b.name, relationship="Finish to Start", active=1).insert(ignore_permissions=True)
    new_doc("Project Risk", project="HOB-1", risk_code="R1", title="Rain", probability=4, min_days=1, most_likely_days=3, max_days=6,
            min_cost=0, most_likely_cost=1000, max_cost=5000).insert(ignore_permissions=True)
    new_doc("Project Resource Allocation", project="HOB-1", resource_type="Employee", resource="ada", start_date="2026-01-05", end_date="2026-01-16", planned_hours=60).insert(ignore_permissions=True)
    c = TestClient(create_app())
    sched = c.post("/api/projectone/programmes/calendar-schedule", json={"programme_id": programme}, headers=BOSS)
    assert sched.status_code == 200, sched.text
    assert sched.json()["data"]["project_finish"] == "2026-01-16"
    risk = c.post("/api/projectone/programmes/risk-simulation", json={"programme_id": programme, "iterations": 200}, headers=BOSS)
    assert risk.status_code == 200, risk.text
    pos = c.post("/api/projectone/programmes/cost-resource-position", json={"programme_id": programme}, headers=BOSS)
    assert pos.status_code == 200, pos.text
    assert pos.json()["data"]["resource_totals"]["ada"]["demand_hours"] == 60
    assert c.post("/api/projectone/programmes/calendar-schedule", json={"programme_id": "NOPE"}, headers=BOSS).status_code == 404


def test_intervention_creates_a_corrective_action(site):
    new_doc("Project", **PROJECT).insert(ignore_permissions=True)
    r = site.post("/api/projectone/management/interventions/EX-1/submit",
                  json={"title": "Recover the slipped milestone", "owner": "pat", "due_date": "2026-03-01", "project": "HOB-1"}, headers=BOSS)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "Draft" and data["sent_for_approval"] is False
    doc = velora.get_doc("Project Corrective Action", data["name"])
    assert doc.action_owner == "pat" and doc.project == "HOB-1" and doc.exception_id == "EX-1"


def _row(doctype, **values):
    from velora import db
    from velora.db.tables import get_table
    with db.transaction() as conn:
        conn.execute(get_table(doctype).insert().values(**{"owner": "boss", "docstatus": 1, **values}))


def test_procurement_sales_inventory_and_assets_are_read_by_project(site):
    new_doc("Project", **PROJECT).insert(ignore_permissions=True)
    _row("Purchase Order", name="PO-1", project="HOB-1", currency="NGN", grand_total=1000, per_billed=25, supplier_name="Acme", document_status="Open")
    _row("Purchase Order", name="PO-2", project="HOB-1", currency="NGN", grand_total=500, per_billed=0, supplier_name="Acme", document_status="Closed")
    _row("Sales Order", name="SO-1", project="HOB-1", currency="NGN", grand_total=4000, per_billed=50, customer_name="Client", document_status="Open")
    _row("Stock Entry", name="SE-1", project="HOB-1", stock_entry_type="Material Issue", total_value=300, entry_status="Approved")
    _row("Stock Entry", name="SE-2", project="HOB-1", stock_entry_type="Material Receipt", total_value=999, entry_status="Approved")
    _row("Fixed Asset", name="FIX-1", project="HOB-1", asset_name="Crane", acquisition_cost=9000, carrying_amount=8000, accumulated_depreciation=1000, status="Active", docstatus=0)
    from velora_projectone.host_sources import FixedAssetSource, InventorySource, ProcurementSource, SalesSource
    from velora_projectone.projectone.integrations.source_readers import ReadQuery
    q = lambda c: ReadQuery("site", c, project_id="HOB-1")          # noqa: E731
    po = {r["name"]: r for r in ProcurementSource().read(q("commitments"))}
    assert po["PO-1"]["open_amount"] == 750 and po["PO-2"]["open_amount"] == 0
    so = SalesSource().read(q("billing_milestones"))[0]
    assert so["amount"] == 4000 and so["billed_amount"] == 2000
    usage = InventorySource().read(q("material_usage"))
    assert [u["name"] for u in usage] == ["SE-1"] and usage[0]["amount"] == 300
    assets = FixedAssetSource().read(q("asset_allocations"))
    assert assets[0]["asset_name"] == "Crane" and assets[0]["carrying_amount"] == 8000


def test_executive_workspace_shows_every_source_connected(site):
    new_doc("Project", **PROJECT).insert(ignore_permissions=True)
    ws = site.get("/api/projectone/portfolio/executive-workspace", headers=BOSS)
    assert ws.status_code == 200, ws.text
    sources = ws.json()["data"]["source_health"]["sources"]
    assert {n: s["status"] for n, s in sources.items()} == {n: "connected" for n in ("accounting", "hrms", "procurement", "sales", "inventory", "fixed_assets")}


def test_forecast_cost_is_used_when_entered(site):
    from velora import get_list
    new_doc("Project Programme", programme_name="P", status="Open").insert(ignore_permissions=True)
    programme = get_list("Project Programme", fields=["name"])[0]["name"]
    new_doc("Project", **{**PROJECT, "programme": programme, "forecast_cost": 6500000}).insert(ignore_permissions=True)
    r = site.post("/api/projectone/programmes/cost-resource-position", json={"programme_id": programme}, headers=BOSS)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["projects"][0]["forecast_cost"] == 6500000
