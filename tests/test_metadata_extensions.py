from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from velora.api import create_app
from velora import db
from velora.db.tables import get_table
from velora.meta.registry import registry
from velora.document import new_doc, get_doc

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
SALES = {"X-Velora-User": "sam", "X-Velora-Roles": "Sales User"}


def test_custom_field_is_company_local_metadata_and_physical_column(site):
    client = TestClient(create_app(auto_init=False))
    denied = client.post("/api/custom-fields/Customer", json={"fieldname": "custom_ref", "fieldtype": "Data"}, headers=SALES)
    assert denied.status_code == 403
    assert client.get("/api/custom-fields/Customer", headers=SALES).status_code == 403
    assert client.get("/api/metadata-extensions/export", headers=SALES).status_code == 403
    created = client.post("/api/custom-fields/Customer", json={"fieldname": "custom_ref", "fieldtype": "Data", "label": "External Reference"}, headers=ADMIN)
    assert created.status_code == 200, created.text
    meta = client.get("/api/meta/Customer", headers=SALES).json()["data"]
    custom = next(f for f in meta["fields"] if f["fieldname"] == "custom_ref")
    assert custom["label"] == "External Reference"
    table = get_table("Customer")
    assert "custom_ref" in table.c
    doc = new_doc("Customer", customer_name="Extension Test", custom_ref="REF-001")
    doc.insert()
    loaded = get_doc("Customer", doc.name)
    assert loaded.custom_ref == "REF-001"


def test_property_setter_overrides_company_metadata_and_can_reset(site):
    client = TestClient(create_app(auto_init=False))
    r = client.post("/api/property-setters/Customer", json={"fieldname": "customer_name", "property": "label", "value": "Trading Name"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    meta = client.get("/api/meta/Customer", headers=SALES).json()["data"]
    field = next(f for f in meta["fields"] if f["fieldname"] == "customer_name")
    assert field["label"] == "Trading Name"
    reset = client.delete("/api/property-setters/Customer/customer_name/label", headers=ADMIN)
    assert reset.status_code == 200
    meta = client.get("/api/meta/Customer", headers=SALES).json()["data"]
    field = next(f for f in meta["fields"] if f["fieldname"] == "customer_name")
    assert field["label"] == "Customer Name"


def test_removing_custom_field_preserves_database_column(site):
    client = TestClient(create_app(auto_init=False))
    assert client.post("/api/custom-fields/Customer", json={"fieldname": "custom_keep", "fieldtype": "Data"}, headers=ADMIN).status_code == 200
    r = client.delete("/api/custom-fields/Customer/custom_keep", headers=ADMIN)
    assert r.status_code == 200 and r.json()["data"]["data_preserved"] is True
    assert registry.get("Customer").get_field("custom_keep") is None
    # Physical columns are intentionally retained to avoid destructive data loss.
    assert "custom_keep" in {c["name"] for c in inspect(db.get_engine()).get_columns("tab_customer")}


def test_metadata_extensions_do_not_cross_company_databases(site, tmp_path):
    client = TestClient(create_app(auto_init=False))
    assert client.post("/api/custom-fields/Customer", json={"fieldname": "custom_company_only", "fieldtype": "Data"}, headers=ADMIN).status_code == 200
    from velora.site import Site, use
    other = Site("other-company", f"sqlite:///{tmp_path / 'other.db'}", apps=["velora_demo"], developer_mode=True)
    try:
        other.load()
        with use(other):
            from velora.db.schema import migrate
            migrate()
            assert registry.get("Customer").get_field("custom_company_only") is None
    finally:
        other.dispose()


def test_metadata_extension_export_import_between_company_databases(site, tmp_path):
    from velora.meta.extensions import export_metadata_extensions, import_metadata_extensions
    from velora.permissions import Session, session_as
    from velora.site import Site, use
    client = TestClient(create_app(auto_init=False))
    assert client.post("/api/custom-fields/Customer", json={"fieldname": "custom_migrated_ref", "fieldtype": "Data", "label": "Migrated Ref"}, headers=ADMIN).status_code == 200
    assert client.post("/api/property-setters/Customer", json={"fieldname": "custom_migrated_ref", "property": "required", "value": True}, headers=ADMIN).status_code == 200
    with session_as(Session("boss", frozenset({"System Manager"}))):
        package = export_metadata_extensions()
        repeated = import_metadata_extensions(package)
        assert repeated["custom_fields"] == 1 and repeated["property_setters"] == 1
    other = Site("import-company", f"sqlite:///{tmp_path / 'import-company.db'}", apps=["velora_demo"], developer_mode=True)
    try:
        other.load()
        with use(other), session_as(Session("boss", frozenset({"System Manager"}))):
            from velora.db.schema import migrate
            migrate()
            result = import_metadata_extensions(package)
            assert result["custom_fields"] == 1 and result["property_setters"] == 1
            field = registry.get("Customer").get_field("custom_migrated_ref")
            assert field is not None and field.required is True
    finally:
        other.dispose()
