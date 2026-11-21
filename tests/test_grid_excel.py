"""Excel (.xlsx) in and out of a child-table grid, and the Excel error report."""
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from velora import dataimport as di
from velora import new_doc
from velora.api import create_app
from velora.exceptions import ValidationError

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}


def book(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_grid_export_round_trips_through_grid_parse(site):
    data, name, _ = di.grid_export("Sales Order Item", [{"description": "Widget", "qty": 2, "rate": 100}, {"description": "=cmd()", "qty": 1, "rate": 5}])
    assert name.endswith(".xlsx")
    ws = load_workbook(io.BytesIO(data)).active
    heads = [c.value for c in ws[1]]
    assert any(h.startswith("Description") for h in heads) and ws.freeze_panes == "A2"
    got = di.grid_parse("Sales Order Item", data, name)
    assert got["errors"] == [] and got["unknown"] == []
    assert [(r["description"], r["qty"]) for r in got["rows"]] == [("Widget", 2), ("'=cmd()"[1:], 1)]


def test_grid_template_is_headings_only(site):
    data, name, _ = di.grid_export("Sales Order Item", None)
    assert "template" in name and load_workbook(io.BytesIO(data)).active.max_row == 1


def test_grid_parse_reports_bad_cells_and_unknown_headings(site):
    f = book([["Description", "Qty", "Bogus"], ["Ok", 1, "x"], ["Bad", "many", "y"]])
    got = di.grid_parse("Sales Order Item", f, "r.xlsx")
    assert [r["description"] for r in got["rows"]] == ["Ok"]
    assert got["errors"] and got["errors"][0]["row"] == 3 and got["errors"][0]["column"] == "Qty"
    assert got["unknown"] == ["Bogus"]


def test_grid_parse_refuses_non_excel_and_non_child_tables(site):
    with pytest.raises(di.ImportFileError):
        di.grid_parse("Sales Order Item", b"a,b\n1,2", "x.csv")
    with pytest.raises(ValidationError):
        di.grid_columns("Customer")


def test_errors_come_back_as_excel(site):
    x = di.errors_xlsx({"failed_rows": [{"data": {"Customer Name": "A"}, "error": "boom"}]})
    ws = load_workbook(io.BytesIO(x)).active
    assert [c.value for c in ws[1]] == ["Customer Name", "Error"] and ws["B2"].value == "boom"


def test_routes(site):
    api = TestClient(create_app(auto_init=False))
    assert api.get("/api/grid-excel/Sales Order Item/template", headers=ADMIN).status_code == 200
    r = api.post("/api/grid-excel/Sales Order Item/export", json={"rows": [{"description": "A", "qty": 1}]}, headers=ADMIN)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    r = api.post("/api/grid-excel/Sales Order Item/read", content=r.content, headers={**ADMIN, "X-Filename": "a.xlsx"})
    assert r.json()["data"]["rows"][0]["description"] == "A"
    r = api.post("/api/data-import/errors-xlsx", json={"failed_rows": [{"data": {"a": 1}, "error": "e"}]}, headers=ADMIN)
    assert r.status_code == 200 and r.content[:2] == b"PK"
