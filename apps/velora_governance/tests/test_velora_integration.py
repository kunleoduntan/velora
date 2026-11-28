"""Velora Governance on the real framework next to VeloraERP: no clashes, seeded data, hooks, API route and Excel export."""
import base64
from datetime import date, timedelta
from io import BytesIO

import pytest
import velora
from velora import get_list, new_doc
from velora.permissions import Session, session_as

ADMIN = Session("Administrator", frozenset({"System Manager"}))
APPS = ["velora_notify", "velora_erp", "velora_projectone", "velora_admin", "velora_governance"]


@pytest.fixture
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'g.db'}", apps=APPS, developer_mode=True)
    velora.init(); velora.migrate()
    from velora_governance.setup import after_install
    with session_as(ADMIN):
        after_install()
        yield


def test_no_doctype_belongs_to_two_apps_and_governance_is_complete(site):
    from velora.meta.registry import registry
    mine = [d for d in registry.all() if d.app == "velora_governance"]
    assert len(mine) == 152 and not [d for d in mine if d.name in {x.name for x in registry.all() if x.app != "velora_governance"}]
    assert {"Board", "Governance Entity", "Sustainability Report", "Governance Exception"} <= {d.name for d in mine}


def test_install_seeds_reference_data_once_and_the_settings_record_has_one_name(site):
    from velora_governance.setup import after_install
    before = len(get_list("Board Type", fields=["name"], limit=100))
    assert before >= 5
    after_install()
    assert len(get_list("Board Type", fields=["name"], limit=100)) == before
    assert [r["name"] for r in get_list("Governance Exception Configuration", fields=["name"], limit=5)] == ["default"]


def test_doc_events_fire_for_governance_documents_saved_through_the_framework(site, monkeypatch):
    import velora_governance.governance.services.governance_automation_event_trigger as trig
    seen = []
    monkeypatch.setattr(trig, "on_source_update", lambda doc, method=None, *a, **k: seen.append((doc.doctype, doc.name)))
    ent_type = get_list("Governance Entity Type", fields=["name"], limit=1)[0]["name"]
    entity = new_doc("Governance Entity", entity_name="Acme Ltd", legal_name="Acme Limited", country="Nigeria", entity_type=ent_type).insert()
    auth = new_doc("Regulatory Authority", authority_name="CAC", country="Nigeria").insert()
    req = new_doc("Regulatory Requirement", authority=auth.name, requirement_code="R1", jurisdiction="Nigeria", requirement_title="Annual return", requirement_type="Filing", frequency="Annual").insert()
    obl = new_doc("Governance Obligation", requirement=req.name, governance_entity=entity.name, obligation_period="FY2026", responsible_owner="Administrator",
                  due_date=date.today() - timedelta(days=5), obligation_status="Open").insert()
    assert ("Governance Obligation", obl.name) in seen
    assert not [x for x in seen if x[0] == "Governance Entity"]       # only the listed doctypes are hooked


def test_governance_api_route_runs_permission_aware_reports_and_exports_excel(site):
    from fastapi.testclient import TestClient
    from velora.api.app import create_app
    client = TestClient(create_app(auto_init=False))
    h = {"X-Velora-User": "Administrator", "X-Velora-Roles": "System Manager"}
    fns = client.get("/api/governance/functions", headers=h)
    assert fns.status_code == 200, fns.text
    assert "export_governance_report_xlsx" in fns.json()["data"]
    cat = client.post("/api/governance/call/get_governance_report_catalog", headers=h, json={})
    assert cat.status_code == 200, cat.text
    reports = cat.json()["data"]
    assert len(reports) > 5
    rid = reports[0]["report_id"]
    out = client.post("/api/governance/call/export_governance_report_xlsx", headers=h, json={"report_id": rid})
    assert out.status_code == 200, out.text
    d = out.json()["data"]
    assert d["filename"].endswith(".xlsx")
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(base64.b64decode(d["content_base64"])))
    assert wb.sheetnames
    assert client.post("/api/governance/call/not_a_function", headers=h, json={}).status_code == 404
    nobody = {"X-Velora-User": "nobody@example.test", "X-Velora-Roles": "Guest"}
    denied = client.post("/api/governance/call/get_governance_exception_centre", headers=nobody, json={})
    assert denied.status_code in (403, 401), denied.text
