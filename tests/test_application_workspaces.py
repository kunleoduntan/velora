import pytest
from fastapi.testclient import TestClient
from velora.api import create_app

ADMIN={"X-Velora-User":"boss","X-Velora-Roles":"System Manager"}
SALES={"X-Velora-User":"sam","X-Velora-Roles":"Sales User"}
FINANCE={"X-Velora-User":"fin","X-Velora-Roles":"Finance User"}

@pytest.fixture
def client(site):
    return TestClient(create_app(auto_init=False))

def test_personal_workspace_is_private_and_owner_managed(client):
    made=client.post("/api/workspaces/personal",headers=SALES,json={"name":"My desk","widgets":[{"type":"shortcut","title":"Reports","route":"#/dashboards"}]})
    assert made.status_code==201, made.text
    wid=made.json()["data"]["id"]
    assert any(x["id"]==wid for x in client.get("/api/workspaces",headers=SALES).json()["data"])
    assert all(x["id"]!=wid for x in client.get("/api/workspaces",headers=FINANCE).json()["data"])
    assert client.get(f"/api/workspaces/{wid}",headers=FINANCE).status_code==403
    assert client.delete(f"/api/workspaces/{wid}",headers=FINANCE).status_code==403

def test_company_workspace_role_visibility_and_manager_only_write(client):
    denied=client.post("/api/workspaces/company",headers=SALES,json={"name":"Finance home","visibility":"company"})
    assert denied.status_code==403, denied.text
    made=client.post("/api/workspaces/company",headers=ADMIN,json={"name":"Finance home","visibility":"roles","roles":["Finance User"],"widgets":[{"type":"shortcut","title":"Reports","route":"#/financial-reports"}]})
    assert made.status_code==201
    wid=made.json()["data"]["id"]
    assert any(x["id"]==wid for x in client.get("/api/workspaces",headers=FINANCE).json()["data"])
    assert all(x["id"]!=wid for x in client.get("/api/workspaces",headers=SALES).json()["data"])

@pytest.mark.parametrize("widget",[
    {"type":"javascript","code":"alert(1)"},
    {"type":"shortcut","title":"Bad","route":"https://evil.example"},
    {"type":"shortcut","title":"Bad","route":"#/settings/security"},
    {"type":"group_by","doctype":"Employee","field":"missing_field"},
])
def test_unsafe_or_invalid_widgets_are_rejected(client,widget):
    r=client.post("/api/workspaces/personal",headers=SALES,json={"name":"Invalid desk","widgets":[widget]})
    assert r.status_code in (404,422)

def test_workspace_widget_count_is_bounded(client):
    r=client.post("/api/workspaces/personal",headers=SALES,json={"name":"Too big","widgets":[{"type":"activity"}]*31})
    assert r.status_code==422

def test_personal_default_landing_is_owner_scoped(client):
    made=client.post("/api/workspaces/personal",headers=SALES,json={"name":"My default","widgets":[{"type":"shortcut","title":"Reports","route":"#/dashboards","width":4}]})
    assert made.status_code==201, made.text
    wid=made.json()["data"]["id"]
    chosen=client.post(f"/api/workspaces/{wid}/default",headers=SALES)
    assert chosen.status_code==200, chosen.text
    assert chosen.json()["data"]["is_default"] is True
    landing=client.get("/api/workspaces/landing",headers=SALES)
    assert landing.status_code==200 and landing.json()["data"]["id"]==wid
    assert client.get("/api/workspaces/landing",headers=FINANCE).json()["data"] is None

def test_role_based_company_workspace_can_be_default_for_matching_role(client):
    made=client.post("/api/workspaces/company",headers=ADMIN,json={"name":"Finance landing","visibility":"roles","roles":["Finance User"],"widgets":[{"type":"activity","title":"Recent activity"}]})
    assert made.status_code==201, made.text
    wid=made.json()["data"]["id"]
    chosen=client.post(f"/api/workspaces/{wid}/default",headers=ADMIN)
    assert chosen.status_code==200, chosen.text
    assert client.get("/api/workspaces/landing",headers=FINANCE).json()["data"]["id"]==wid
    assert client.get("/api/workspaces/landing",headers=SALES).json()["data"] is None

@pytest.mark.parametrize("width",[0,5,-1,True,"2"])
def test_workspace_widget_width_is_strictly_validated(client,width):
    r=client.post("/api/workspaces/personal",headers=SALES,json={"name":"Bad width","widgets":[{"type":"activity","width":width}]})
    assert r.status_code==422

@pytest.mark.parametrize("filters", ["docstatus=0", 12, ["docstatus", "=", 0], [["missing_field", "=", 0]]])
def test_workspace_widget_filters_are_validated(client, filters):
    r=client.post("/api/workspaces/personal",headers=SALES,json={"name":"Invalid filters","widgets":[{"type":"number","title":"Draft invoices","doctype":"Sales Invoice","filters":filters}]})
    assert r.status_code in (404, 422)


def test_workspace_role_templates_are_present_in_designer_source():
    from pathlib import Path
    source=Path(__file__).parents[1] / "frontend" / "src" / "components" / "WorkspaceDesigner.tsx"
    text=source.read_text()
    for role in ("Finance Manager","Accountant","HR Manager","Payroll Officer","Procurement Officer","Asset Manager","Executive"):
        assert role in text
    assert "Recent Finance Activity" in text

