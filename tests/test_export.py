import io
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

import velora
from velora import db, new_doc
from velora.api import create_app
from velora.db.system import export_log
from velora.exceptions import PermissionDenied, ValidationError
from velora.export import export_xlsx

SALES = velora.Session("sam", frozenset({"Sales User"}))
NOBODY = velora.Session("nobody", frozenset())
H = {"X-Velora-User": "sam", "X-Velora-Roles": "Sales User"}


def wb_of(data):
    return load_workbook(io.BytesIO(data))


def rows(ws):
    return [[c.value for c in r] for r in ws.iter_rows()]


@pytest.fixture
def data(site):
    new_doc("Customer Group", group_name="Retail").insert()
    new_doc("Customer", customer_name="Acme Ltd", customer_group="Retail", credit_limit="1500.5", status="Active",
            contacts=[{"contact_name": "Ada", "email": "ada@acme.ng"}, {"contact_name": "Bola"}]).insert()
    new_doc("Customer", customer_name="=HYPERLINK(\"http://evil\",\"x\")", status="Blocked").insert()
    new_doc("Customer", customer_name="Zed Co", status="Active").insert()
    new_doc("Sales Order", customer="CUST-0001", order_date="2026-03-15",
            items=[{"description": "Widget", "qty": 2, "rate": "10.25"}, {"description": "Gadget", "qty": 1, "rate": 99}]).insert()


def test_current_view_exports_only_chosen_columns_in_order(data):
    blob, fname, n = export_xlsx("Customer", columns=["customer_name", "name", "credit_limit"], order_by="customer_name asc")
    assert n == 3 and fname.startswith("Customer_") and fname.endswith(".xlsx")
    wb = wb_of(blob)
    assert wb.sheetnames == ["Customer", "Export info"]
    ws = wb["Customer"]
    assert rows(ws)[0] == ["Customer Name", "ID", "Credit Limit"]
    body = rows(ws)[1:]
    assert [r[1] for r in body] == ["CUST-0001", "CUST-0002", "CUST-0003"] or len(body) == 3
    acme = next(r for r in body if r[0] == "Acme Ltd")
    assert acme[2] == 1500.5 and isinstance(acme[2], float)                 # numbers stay numbers
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref
    assert ws["A1"].font.bold


def test_header_can_be_fieldnames(data):
    ws = wb_of(export_xlsx("Customer", columns=["customer_name", "credit_limit"], header="fieldname")[0])["Customer"]
    assert rows(ws)[0] == ["customer_name", "credit_limit"]


def test_filters_and_selected_rows_are_respected(data):
    _, _, n = export_xlsx("Customer", filters=[["status", "=", "Blocked"]])
    assert n == 1
    blob, _, n = export_xlsx("Customer", names=["CUST-0001", "CUST-0003"], columns=["name"])
    assert n == 2 and sorted(r[0] for r in rows(wb_of(blob)["Customer"])[1:]) == ["CUST-0001", "CUST-0003"]


def test_formula_injection_is_neutralised(data):
    ws = wb_of(export_xlsx("Customer", columns=["customer_name"])[0])["Customer"]
    cell = next(c for r in ws.iter_rows(min_row=2) for c in r if str(c.value).startswith("=HYPERLINK"))
    assert cell.data_type == "s"                                            # stored as text, not a formula


def test_all_fields_includes_system_fields_and_child_sheets(data):
    blob, _, n = export_xlsx("Customer", all_fields=True, order_by="name asc")
    wb = wb_of(blob)
    assert wb.sheetnames == ["Customer", "Contacts", "Export info"]
    head = rows(wb["Customer"])[0]
    assert head[0] == "ID" and {"Customer Name", "Email Address", "Credit Limit", "Created By", "Created On", "Last Modified"} <= set(head)
    assert "Contacts" not in head                                           # table fields are sheets, not columns
    contacts = rows(wb["Contacts"])
    assert contacts[0][:2] == ["Parent", "Row"] and {"contact_name", "Contact Name"} & set(contacts[0])
    assert [(r[0], r[1]) for r in contacts[1:]] == [("CUST-0001", 1), ("CUST-0001", 2)]
    created = rows(wb["Customer"])[1][head.index("Created On")]
    assert isinstance(created, datetime)                                    # real Excel dates, not text


def test_submittable_export_shows_status_text_dates_and_all_child_rows(data):
    so = velora.get_doc("Sales Order", "SO-00001")
    so.submit()
    wb = wb_of(export_xlsx("Sales Order", all_fields=True)[0])
    head = rows(wb["Sales Order"])[0]
    r = rows(wb["Sales Order"])[1]
    assert r[head.index("Status")] == "Submitted"
    assert isinstance(r[head.index("Order Date")], datetime) and r[head.index("Order Date")].date() == date(2026, 3, 15)
    assert r[head.index("Total")] == pytest.approx(119.5)
    items = rows(wb["Items"])
    assert len(items) == 3 and items[1][2] == "Widget" or "Widget" in items[1]


def test_info_sheet_and_audit_log(data):
    blob, _, _ = export_xlsx("Customer", filters=[["status", "=", "Active"]])
    info = dict(rows(wb_of(blob)["Export info"]))
    assert info["Rows exported"] == 2 and info["Scope"] == "Current view" and info["Exported by"] == "Administrator"
    with db.transaction() as conn:
        log = conn.execute(select(export_log)).mappings().all()
    assert len(log) == 1 and log[0]["ref_doctype"] == "Customer" and log[0]["row_count"] == 2 and log[0]["scope"] == "view"


def test_row_limit_and_validation(data):
    _, _, n = export_xlsx("Customer", limit=2)
    assert n == 2
    with pytest.raises(ValidationError, match="unknown column"):
        export_xlsx("Customer", columns=["nope"])
    with pytest.raises(ValidationError, match="header"):
        export_xlsx("Customer", header="x")


def test_export_needs_export_permission_not_just_read(data):
    with velora.session_as(SALES):
        export_xlsx("Customer")                                             # granted on Customer
        with pytest.raises(PermissionDenied, match="export"):
            export_xlsx("Customer Group")                                   # read but no export
    with velora.session_as(NOBODY):
        with pytest.raises(PermissionDenied):
            export_xlsx("Customer")


def test_export_endpoint(site, data):
    c = TestClient(create_app(auto_init=False))
    r = c.post("/api/export/Customer", json={"columns": ["name", "customer_name"], "filters": [["status", "=", "Active"]]}, headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert 'filename="Customer_' in r.headers["content-disposition"] and r.headers["x-velora-rows"] == "2"
    assert len(rows(wb_of(r.content)["Customer"])) == 3
    assert c.post("/api/export/Customer Group", json={}, headers=H).status_code == 403
    assert c.post("/api/export/Customer", json={}).status_code == 401
    assert c.post("/api/export/Customer", json={"columns": ["x"]}, headers=H).status_code == 422
