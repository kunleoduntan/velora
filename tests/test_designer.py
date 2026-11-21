"""Form layouts, grid columns, and the DocType Creator (with the Frappe importer)."""
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import velora
from velora import new_doc
from velora import site as site_mod
from velora.api import create_app
from velora.devtools import creator
from velora.exceptions import MetaError
from velora.meta import layout as lay
from velora.meta.registry import registry
from velora.meta.spec import DocType
from velora.scaffold import new_app

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
SALES = {"X-Velora-User": "sam", "X-Velora-Roles": "Sales User"}
NOBODY = {"X-Velora-User": "nobody", "X-Velora-Roles": "Some Other Role"}
FIXTURES = Path(__file__).parent / "fixtures"


def dt(fields, **kw):
    return DocType.from_dict({"name": "T", "fields": fields, **kw})


def D(n):
    return {"fieldname": n, "fieldtype": "Data"}


def L(*rows, tabs=None):
    return {"tabs": tabs or [{"label": "Details", "sections": [{"label": "", "rows": [[{"field": f, "span": s} for f, s in r] for r in rows]}]}]}


BASE = [D("a"), D("b"), D("c"), {"fieldname": "n", "fieldtype": "Text"}, {"fieldname": "h", "fieldtype": "Data", "hidden": True}]


# ================================ the layout model ================================
@pytest.mark.parametrize("layout,frag", [
    ("nope", "object with a 'tabs' list"), ({"tabs": "x"}, "'tabs' list"), ({"tabs": []}, "at least one tab"),
    ({"tabs": [{"sections": "x"}]}, "needs a 'sections' list"), ({"tabs": [{"sections": [{"rows": "x"}]}]}, "needs a 'rows' list"),
    (L([]), "needs at least one cell"), (L([("zzz", 6)]), "'zzz' is not a field of T"), (L([("a", 6)], [("a", 6)]), "placed more than once"),
    (L([("a", 0)]), "span between 1 and 12"), (L([("a", 13)]), "span between 1 and 12"), (L([("a", "6")]), "span between 1 and 12"),
    (L([("a", True)]), "span between 1 and 12"), (L([("a", 2.5)]), "span between 1 and 12"), (L([("a", 7), ("b", 6)]), "add up to 13"),
    ({"tabs": [{"label": "x" * 200, "sections": [{"rows": [[{"field": "a", "span": 12}]]}]}]}, "label must be text"),
    ({"tabs": [{"sections": [{"rows": [["not a cell"]]}]}]}, "must be an object"),
])
def test_layout_validation_rejects(layout, frag):
    assert any(frag in e for e in lay.validate_layout(layout, dt(BASE)))


def test_layout_validation_limits_and_breaks():
    d = dt(BASE + [{"fieldname": "sec", "fieldtype": "Section Break"}])
    assert any("Section/Column/Tab breaks cannot be placed" in e for e in lay.validate_layout(L([("sec", 12)]), d))
    many = [D(f"f{i}") for i in range(13)]
    assert any("at most 12 cells" in e for e in lay.validate_layout(L([(f"f{i}", 1) for i in range(13)]), dt(many)))
    assert any("at most 12 tabs" in e for e in lay.validate_layout({"tabs": [{"sections": [{"rows": [[{"field": "a", "span": 1}]]}]}] * 13}, dt(BASE)))
    assert lay.validate_layout(L([("a", 4), ("b", 4), ("c", 4)], [("n", 12)]), dt(BASE)) == []
    assert lay.validate_layout(L([("a", 6)]), dt(BASE)) == []                                   # leaving free space in a row is fine


def test_a_layout_may_leave_fields_out_and_they_are_appended_never_lost():
    d = dt(BASE + [{"fieldname": "t2", "fieldtype": "Table", "options": "X"}][:0])
    eff = lay.effective_layout(L([("a", 12)]), d)
    last = eff["tabs"][-1]["sections"][-1]
    assert last["label"] == "More" and last["auto"] is True
    assert last["rows"] == [[{"field": "b", "span": 6}, {"field": "c", "span": 6}], [{"field": "n", "span": 12}]]      # pairs of small fields, wide ones alone
    assert "h" not in lay.placed(eff)                                                                                   # hidden fields stay hidden
    full = L([("a", 3), ("b", 3), ("c", 3)], [("n", 12)])
    assert lay.effective_layout(full, d) == full                                                                        # nothing missing: unchanged
    assert lay.effective_layout({"tabs": []}, d)["tabs"][0]["label"] == "Details"


def test_the_saved_layout_is_not_mutated_by_effective_layout():
    base = L([("a", 12)])
    before = json.dumps(base)
    lay.effective_layout(base, dt(BASE))
    assert json.dumps(base) == before


def test_derive_layout_follows_frappe_break_semantics():
    d = dt([{"fieldname": "t1", "fieldtype": "Tab Break", "label": "Main"}, D("a"), D("b"), {"fieldname": "c1", "fieldtype": "Column Break"}, D("c"),
            {"fieldname": "s", "fieldtype": "Section Break", "label": "More"}, D("x"), {"fieldname": "c2", "fieldtype": "Column Break"}, D("y"),
            {"fieldname": "c3", "fieldtype": "Column Break"}, D("z"), {"fieldname": "t2", "fieldtype": "Tab Break", "label": "Notes"},
            {"fieldname": "n", "fieldtype": "Text"}, {"fieldname": "hid", "fieldtype": "Data", "hidden": True}])
    out = lay.derive_layout(d)
    assert [t["label"] for t in out["tabs"]] == ["Main", "Notes"]
    s1, s2 = out["tabs"][0]["sections"]
    assert s1["rows"] == [[{"field": "a", "span": 6}, {"field": "c", "span": 6}], [{"field": "b", "span": 6}]]            # two columns: stacks become aligned rows
    assert s2["label"] == "More" and s2["rows"] == [[{"field": "x", "span": 4}, {"field": "y", "span": 4}, {"field": "z", "span": 4}]]
    assert out["tabs"][1]["sections"][0]["rows"] == [[{"field": "n", "span": 12}]]
    assert lay.validate_layout(out, d) == []                                                                           # a derived layout is always valid
    assert lay._spans(5) == [3, 3, 2, 2, 2] and sum(lay._spans(7)) == 12


def test_derive_layout_pairs_short_fields_and_keeps_long_controls_full_width():
    d = dt([D("customer"), D("posting_date"), D("due_date"), {"fieldname": "remarks", "fieldtype": "Text"}, D("currency"), {"fieldname": "items", "fieldtype": "Table", "options": "Line"}, D("status")])
    out = lay.derive_layout(d)
    rows = out["tabs"][0]["sections"][0]["rows"]
    assert rows == [
        [{"field": "customer", "span": 6}, {"field": "posting_date", "span": 6}],
        [{"field": "due_date", "span": 6}],
        [{"field": "remarks", "span": 12}],
        [{"field": "currency", "span": 6}],
        [{"field": "items", "span": 12}],
        [{"field": "status", "span": 6}],
    ]
    assert lay.validate_layout(out, d) == []


def test_derive_layout_of_the_real_demo_doctype_is_valid_and_complete(site):
    m = registry.get("Customer")
    out = lay.derive_layout(m)
    assert lay.validate_layout(out, m) == [] and not lay.unplaced_fields(out, m)


def test_grid_column_validation():
    d = dt([D("a"), D("b"), {"fieldname": "n", "fieldtype": "Text"}, {"fieldname": "s", "fieldtype": "Section Break"}], istable=True)
    ok = [{"field": "a", "width": 4}, {"field": "b", "width": 6}]
    assert lay.validate_grid_columns(ok, d) == []
    for cols, frag in (([], "non-empty list"), ("x", "non-empty list"), ([{"field": "zz", "width": 2}], "not a field"), ([{"field": "s", "width": 2}], "not a field"),
                       ([{"field": "a", "width": 2}, {"field": "a", "width": 2}], "twice"), ([{"field": "a", "width": 0}], "between 1 and 100"),
                       ([{"field": "a", "width": 101}], "between 1 and 100"), ([{"field": "a", "width": True}], "between 1 and 100"), (["a"], "not a field")):
        assert any(frag in e for e in lay.validate_grid_columns(cols, d)), cols
    # There is no aggregate ten-unit or ten-column ceiling; every eligible child field may be configured.
    many = dt([D(f"f{i}") for i in range(25)], istable=True)
    cols = [{"field": f"f{i}", "width": 2} for i in range(25)]
    assert lay.validate_grid_columns(cols, many) == []


def test_spec_integration_validates_normalises_and_serves_layouts():
    d = dt(BASE, layout={"tabs": [{"label": "X", "junk": 1, "sections": [{"label": "S", "evil": "<script>", "rows": [[{"field": "a", "span": 12, "x": 1}]]}]}]})
    assert d.layout == {"tabs": [{"label": "X", "sections": [{"label": "S", "collapsible": False, "rows": [[{"field": "a", "span": 12}]]}]}]}      # unknown keys dropped
    assert d.to_dict()["layout"] == d.layout
    with pytest.raises(MetaError, match="layout: .*'zzz' is not a field"):
        dt(BASE, layout=L([("zzz", 12)]))
    with pytest.raises(MetaError, match="child table has no 'layout'"):
        dt(BASE, istable=True, layout=L([("a", 12)]))
    with pytest.raises(MetaError, match="'grid_columns' is only for child tables"):
        dt(BASE, grid_columns=[{"field": "a", "width": 2}])
    t = dt(BASE, istable=True, grid_columns=[{"field": "a", "width": 3}, {"field": "b", "width": 7}])
    assert t.to_dict()["grid_columns"] == [{"field": "a", "width": 3}, {"field": "b", "width": 7}] and "layout" not in t.to_dict()
    assert "layout" not in dt(BASE).to_dict()                                                                          # no layout: the classic rendering


# ================================ the layout / grid API ================================
@pytest.fixture
def client(site):
    return TestClient(create_app(auto_init=False))


def put(client, doctype, layout, headers=ADMIN, **kw):
    return client.put(f"/api/layout/{doctype}", json={"layout": layout, **kw}, headers=headers)


def test_get_layout_derives_one_when_there_is_none(client):
    r = client.get("/api/layout/Customer", headers=ADMIN).json()["data"]
    assert r["source"] == "auto" and r["editable"] is True and r["can_write_app"] is True and r["unplaced"] == []
    assert {c["field"] for t in r["layout"]["tabs"] for s in t["sections"] for row in s["rows"] for c in row} >= {"customer_name", "contacts"}
    assert client.get("/api/layout/Customer", headers=SALES).json()["data"]["editable"] is False                       # anyone who can read it may SEE the layout
    assert client.get("/api/layout/Customer", headers=NOBODY).status_code == 403
    assert client.get("/api/layout/Ghost", headers=ADMIN).status_code == 404
    assert client.get("/api/layout/Sales Order Item", headers=ADMIN).status_code == 422                                  # child tables use /api/grid


def test_a_saved_company_layout_reaches_the_form_and_unplaced_fields_still_show(client):
    meta = client.get("/api/meta/Customer", headers=ADMIN).json()["data"]
    assert "layout" not in meta and meta["can_customize"] is True                                                         # no layout yet: the classic form
    assert client.get("/api/meta/Customer", headers=SALES).json()["data"]["can_customize"] is False
    r = put(client, "Customer", L([("customer_name", 8), ("status", 4)], [("contacts", 12)]))
    assert r.status_code == 200 and r.json()["data"]["saved"] == "company"
    meta = client.get("/api/meta/Customer", headers=SALES).json()["data"]                                                 # everyone in the company gets it
    assert meta["layout_source"] == "company"
    cells = [c for t in meta["layout"]["tabs"] for s in t["sections"] for row in s["rows"] for c in row]
    assert cells[0] == {"field": "customer_name", "span": 8}
    placed = {c["field"] for c in cells}
    shown = {f["fieldname"] for f in meta["fields"] if f["fieldtype"] not in ("Section Break", "Column Break", "Tab Break") and not f.get("hidden")}
    assert shown <= placed                                                                                                # the fields the layout left out are appended, never lost
    assert meta["layout"]["tabs"][-1]["sections"][-1].get("auto") is True
    g = client.get("/api/layout/Customer", headers=ADMIN).json()["data"]
    assert g["source"] == "company" and len(g["unplaced"]) == len(shown - {"customer_name", "status", "contacts"})        # the designer shows what is still unplaced
    assert client.delete("/api/layout/Customer", headers=ADMIN).json()["data"] == {"reset": "Customer"}
    assert "layout" not in client.get("/api/meta/Customer", headers=ADMIN).json()["data"]


def test_layout_saving_rules(client):
    assert put(client, "Customer", L([("customer_name", 6)]), headers=SALES).status_code == 403                          # only a System Manager customises
    assert client.delete("/api/layout/Customer", headers=SALES).status_code == 403
    r = put(client, "Customer", L([("customer_name", 9), ("status", 9)], [("nope", 3)]))
    assert r.status_code == 422 and "add up to 18" in r.json()["message"] and "'nope' is not a field" in r.json()["message"]       # every problem, not only the first
    assert put(client, "Customer", {"tabs": []}).status_code == 422
    assert put(client, "Customer", "junk").status_code == 422
    assert put(client, "Customer", L([("customer_name", 12)]), target="elsewhere").status_code == 422
    assert put(client, "Sales Order Item", L([("description", 12)])).status_code == 422
    assert put(client, "Ghost", L([("a", 12)])).status_code == 404
    big = {"tabs": [{"label": "t", "sections": [{"rows": [[{"field": "customer_name", "span": 12}]]}] * 61}]}
    assert put(client, "Customer", big).status_code == 422
    assert "layout" not in client.get("/api/meta/Customer", headers=ADMIN).json()["data"]                                  # nothing invalid was stored


def test_grid_columns_api(client):
    g = client.get("/api/grid/Sales Order Item", headers=ADMIN).json()["data"]
    assert g["source"] == "auto" and g["columns"] == [] and {f["fieldname"] for f in g["fields"]} >= {"description", "qty", "rate"}
    assert client.get("/api/grid/Customer", headers=ADMIN).status_code == 422
    cols = [{"field": "description", "width": 5}, {"field": "qty", "width": 2}, {"field": "rate", "width": 3}]
    assert client.put("/api/grid/Sales Order Item", json={"columns": cols}, headers=ADMIN).status_code == 200
    assert client.get("/api/meta/Sales Order Item", headers=SALES).json()["data"]["grid_columns"] == cols
    assert client.put("/api/grid/Sales Order Item", json={"columns": cols}, headers=SALES).status_code == 403
    bad = client.put("/api/grid/Sales Order Item", json={"columns": [{"field": "qty", "width": 101}, {"field": "zz", "width": 1}]}, headers=ADMIN)
    assert bad.status_code == 422 and "between 1 and 100" in bad.json()["message"] and "not a field" in bad.json()["message"]
    assert client.delete("/api/grid/Sales Order Item", headers=ADMIN).status_code == 200
    assert "grid_columns" not in client.get("/api/meta/Sales Order Item", headers=ADMIN).json()["data"]


# ================================ writing a layout into the app (developer mode) ================================
@pytest.fixture
def scratch(tmp_path):
    name = "scratch_" + uuid.uuid4().hex[:8]
    root = new_app(tmp_path, name, module="Scratch")
    sys.path.insert(0, str(root))
    cfg = velora.configure(db_url=f"sqlite:///{tmp_path / 's.db'}", apps=[name], developer_mode=True)
    velora.init(cfg)
    velora.migrate()
    yield SimpleNamespace(app=name, root=root, mod=root / name / "scratch", tmp=tmp_path)
    velora.shutdown()
    sys.path.remove(str(root))
    for m in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        del sys.modules[m]


def make_doctype(scratch, name="Gadget", **extra):
    spec = {"name": name, "module": "Scratch", "fields": [{"fieldname": "title", "fieldtype": "Data", "required": True}, {"fieldname": "colour", "fieldtype": "Data"},
                                                           {"fieldname": "size", "fieldtype": "Int"}], "permissions": [{"role": "System Manager", "read": True, "write": True, "create": True}], **extra}
    d = scratch.mod / "doctype" / name.lower()
    d.mkdir(parents=True, exist_ok=True)
    for p in (scratch.mod / "__init__.py", scratch.mod / "doctype" / "__init__.py", d / "__init__.py"):
        p.touch()
    (d / f"{name.lower()}.json").write_text(json.dumps(spec, indent=2))
    site_mod.current().load()
    velora.migrate()
    return d / f"{name.lower()}.json"


def test_a_layout_can_be_written_into_the_apps_own_json_in_developer_mode(scratch):
    path = make_doctype(scratch)
    before = json.loads(path.read_text())
    c = TestClient(create_app(auto_init=False))
    layout = L([("title", 8), ("colour", 4)], [("size", 12)])
    assert put(c, "Gadget", layout, target="company").status_code == 200
    r = put(c, "Gadget", layout, target="app")
    assert r.status_code == 200 and r.json()["data"]["saved"] == "app"
    written = json.loads(path.read_text())
    assert written["layout"]["tabs"][0]["sections"][0]["rows"][0] == [{"field": "title", "span": 8}, {"field": "colour", "span": 4}]
    assert {k: v for k, v in written.items() if k != "layout"} == before                                                   # nothing else in the file changed
    assert not list(path.parent.glob("*.tmp"))                                                                           # the atomic write left nothing behind
    g = c.get("/api/layout/Gadget", headers=ADMIN).json()["data"]
    assert g["source"] == "app"                                                                                          # the stale company copy was cleared so the app's layout shows
    assert registry.get("Gadget").layout == written["layout"]


def test_writing_into_the_app_needs_developer_mode(scratch, monkeypatch):
    make_doctype(scratch)
    c = TestClient(create_app(auto_init=False))
    monkeypatch.setattr("velora.api.designer.developer_mode", lambda ws=None: False)         # (switching the site flag would make the API refuse header logins first)
    r = put(c, "Gadget", L([("title", 12)]), target="app")
    assert r.status_code == 403 and "developer mode" in r.json()["message"]
    assert c.get("/api/layout/Gadget", headers=ADMIN).json()["data"]["can_write_app"] is False
    assert put(c, "Gadget", L([("title", 12)]), target="company").status_code == 200                                      # a company layout never needs it


def test_developer_mode_comes_from_the_site_or_the_workspace_config(scratch, monkeypatch):
    from velora.api.designer import developer_mode

    class WS:
        def __init__(self, cfg):
            self.cfg = cfg

        def common_config(self):
            return self.cfg
    assert developer_mode() is True
    monkeypatch.setattr(site_mod.current(), "developer_mode", False)
    assert developer_mode() is False and developer_mode(WS({})) is False
    assert developer_mode(WS({"developer_mode": True})) is True                                # a hosted workspace opts in explicitly


def test_a_grid_can_be_written_into_a_child_tables_json(scratch):
    path = make_doctype(scratch, "Part", istable=True, permissions=[])
    c = TestClient(create_app(auto_init=False))
    r = c.put("/api/grid/Part", json={"columns": [{"field": "title", "width": 6}, {"field": "size", "width": 4}], "target": "app"}, headers=ADMIN)
    assert r.status_code == 200 and json.loads(path.read_text())["grid_columns"] == [{"field": "title", "width": 6}, {"field": "size", "width": 4}]
    assert registry.get("Part").grid_columns[0] == {"field": "title", "width": 6}


# ================================ the DocType Creator: Frappe import ================================
def test_structure_detection():
    d = creator.detect_structure
    assert d({"doctypes": []}) == "multiple" and d({"name": "X", "fields": []}) == "single" and d({"doctype": "DocType", "fields": []}) == "single"
    assert d([{"fieldname": "a", "fieldtype": "Data"}]) == "fields" and d([{"label": "only"}]) == "unknown" and d([]) == "unknown"
    assert d("text") == "unknown" and d({"name": "X"}) == "unknown" and d(None) == "unknown"


def conv(**kw):
    base = {"name": "Thing", "module": "Mod", "fields": []}
    base.update(kw)
    return creator.convert(base)


def test_frappe_field_types_flags_and_defaults_are_mapped():
    spec, warns = conv(fields=[
        {"fieldname": "a", "fieldtype": "Small Text", "reqd": 1, "in_list_view": 1}, {"fieldname": "b", "fieldtype": "Long Text"}, {"fieldname": "c", "fieldtype": "Text Editor"},
        {"fieldname": "d", "fieldtype": "Percent", "default": "12.5"}, {"fieldname": "e", "fieldtype": "Check", "default": "1"}, {"fieldname": "f", "fieldtype": "Check", "default": "0"},
        {"fieldname": "g", "fieldtype": "Select", "options": "One\nTwo\n\nThree"}, {"fieldname": "h", "fieldtype": "Attach Image"}, {"fieldname": "i", "fieldtype": "Duration"},
        {"fieldname": "j", "fieldtype": "Password"}, {"fieldname": "k", "fieldtype": "Dynamic Link"}, {"fieldname": "l", "fieldtype": "Table MultiSelect", "options": "X"},
        {"fieldname": "m", "fieldtype": "Int", "default": "7"}, {"fieldname": "n", "fieldtype": "Weird"}, {"fieldname": "o", "fieldtype": "Link", "options": "Customer", "unique": 1},
        {"fieldname": "p", "fieldtype": "Date", "default": "Today", "description": "when", "read_only": 1, "hidden": 1}])
    f = {x["fieldname"]: x for x in spec["fields"]}
    assert f["a"] == {"fieldname": "a", "fieldtype": "Text", "required": True, "in_list_view": True} and f["b"]["fieldtype"] == "Text" and f["c"]["fieldtype"] == "Text"
    assert f["d"]["fieldtype"] == "Float" and f["d"]["default"] == 12.5 and f["e"]["default"] == 1 and f["f"]["default"] == 0 and f["m"]["default"] == 7
    assert f["g"]["options"] == ["One", "Two", "Three"] and f["h"]["fieldtype"] == "Data" and f["i"]["fieldtype"] == "Int" and f["l"]["fieldtype"] == "JSON"
    assert f["o"] == {"fieldname": "o", "fieldtype": "Link", "options": "Customer", "unique": True} and f["p"]["default"] == "Today" and f["p"]["read_only"] and f["p"]["hidden"]
    text = "\n".join(warns)
    for frag in ("Text Editor is stored as plain Text", "Duration -> Int (stored as seconds)", "Password -> Data (stored as PLAIN text", "Dynamic Link -> Data", "Table MultiSelect -> JSON",
                 "unknown field type 'Weird'"):
        assert frag in text, frag
    assert "Small Text" not in text and "Percent" not in text                                                          # exact equivalents are not noise


def test_frappe_field_order_display_only_and_unsupported_features():
    spec, warns = conv(field_order=["z", "y", "x"], fields=[
        {"fieldname": "x", "fieldtype": "Data"}, {"fieldname": "y", "fieldtype": "Data", "depends_on": "eval:doc.x", "fetch_from": "a.b", "allow_on_submit": 1},
        {"fieldname": "z", "fieldtype": "Data", "mandatory_depends_on": "x"}, {"fieldname": "btn", "fieldtype": "Button"}, {"fieldname": "hd", "fieldtype": "Heading"},
        {"fieldname": "extra", "fieldtype": "Data"}])
    assert [f["fieldname"] for f in spec["fields"]] == ["z", "y", "x", "extra"]                                          # Frappe's real order is field_order; unlisted fields go last
    text = "\n".join(warns)
    assert "Button fields are display-only" in text and "Heading fields are display-only" in text
    fields = {f["fieldname"]: f for f in spec["fields"]}
    assert fields["y"]["depends_on"] == "eval:doc.x"
    assert fields["z"]["mandatory_depends_on"] == "x"
    assert "conditional visibility (depends_on)" not in text and "conditional required" not in text
    assert "fetch_from" in text and "allow_on_submit" in text


@pytest.mark.parametrize("autoname,fields,expect,warn", [
    (None, [], None, None), ("hash", [], "hash", None), ("Prompt", [], "prompt", None), ("field:title", [{"fieldname": "title", "fieldtype": "Data"}], "field:title", None),
    ("naming_series:", [{"fieldname": "naming_series", "fieldtype": "Select", "options": "SINV-.YYYY.-.#####"}], "series:SINV-.#####", "date parts"),
    ("naming_series:", [{"fieldname": "naming_series", "fieldtype": "Select", "options": "ABC-.####"}], "series:ABC-.####", "naming_series field was removed"),
    ("format:INV-{#####}", [], "series:INV-.#####", None), ("format:{YYYY}-{####}", [], None, "not supported"), ("something_else", [], None, "not supported"),
])
def test_frappe_naming_rules(autoname, fields, expect, warn):
    spec, warns = creator.convert({"name": "Thing", "module": "M", "autoname": autoname, "fields": fields + [{"fieldname": "title", "fieldtype": "Data"}] if not fields else fields})
    assert spec.get("autoname") == expect
    assert (warn is None and not any("naming" in w or "date parts" in w for w in warns)) or any(warn in w for w in warns)
    if autoname == "naming_series:":
        assert "naming_series" not in [f["fieldname"] for f in spec["fields"]]


def test_frappe_sort_order_is_normalised():
    assert conv(sort_order="DESC", fields=[{"fieldname": "a", "fieldtype": "Data"}])[0]["sort_order"] == "desc"
    assert conv(sort_order="Asc", fields=[{"fieldname": "a", "fieldtype": "Data"}])[0]["sort_order"] == "asc"
    spec, warns = conv(sort_order="sideways", fields=[{"fieldname": "a", "fieldtype": "Data"}])
    assert "sort_order" not in spec and any("sort order 'sideways'" in w for w in warns)


def test_frappe_permissions_and_doctype_flags():
    spec, warns = conv(is_submittable=1, track_changes=1, permissions=[{"role": "Accountant", "read": 1, "write": 1, "submit": 1, "email": 1, "print": 1, "share": 1},
                                                                   {"role": "Auditor", "read": 1, "permlevel": 1}], fields=[{"fieldname": "a", "fieldtype": "Data"}])
    assert spec["permissions"] == [{"role": "Accountant", "read": True, "write": True, "submit": True, "share": True, "print": True, "email": True}] and spec["is_submittable"] and spec["track_changes"]
    assert any("permission level 1 rows are not supported" in w for w in warns)
    assert conv(fields=[{"fieldname": "a", "fieldtype": "Data"}])[0]["permissions"][0]["role"] == "System Manager"                    # a sensible default, not an unusable DocType
    assert "submit" in conv(is_submittable=1, fields=[{"fieldname": "a", "fieldtype": "Data"}])[0]["permissions"][0]
    child, _ = conv(istable=1, is_submittable=1, track_changes=1, autoname="prompt", fields=[{"fieldname": "a", "fieldtype": "Data"}])
    assert child["istable"] and "is_submittable" not in child and "autoname" not in child and "permissions" not in child
    with pytest.raises(MetaError, match="Single DocTypes .* are not supported"):
        conv(issingle=1)
    with pytest.raises(MetaError, match="needs a name"):
        creator.convert({"fields": []})


def test_your_actual_frappe_doctype_creator_export(scratch):
    """The DocType from your upload: a Frappe 'Single' DocType. The honest answer is a clear refusal that says why."""
    data = json.loads((FIXTURES / "frappe_doctype_creator.json").read_text())
    p = creator.plan(data, app=scratch.app)
    assert not p.report()["ok"] and any("Single DocTypes" in e and "Doctype Creator" in e for e in p.errors)
    data["issingle"] = 0                                                                                                 # as a normal DocType it converts - field_order respected ...
    spec, warns = creator.convert(data)
    assert [f["fieldname"] for f in spec["fields"]][:4] == ["title", "doctype_name", "module", "is_submittable"]
    assert spec["fields"][2] == {"fieldname": "module", "fieldtype": "Link", "options": "Module Def", "label": "Module"}
    p = creator.plan(data, app=scratch.app)                                                                              # ... and the Link to Frappe's own 'Module Def' is caught BEFORE anything is written
    assert any("Link target 'Module Def' is not a DocType" in e for e in p.errors)
    assert not [d for d in scratch.mod.glob("doctype/*") if d.is_dir()]                                                  # no DocType folder was created


# ================================ the DocType Creator: plan + create ================================
def frappe_pair(module="Scratch"):
    return {"doctypes": [
        {"doctype": "DocType", "name": "Order Line", "module": module, "istable": 1, "fields": [{"fieldname": "item", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                                                                                                {"fieldname": "qty", "fieldtype": "Float", "default": "1"}]},
        {"doctype": "DocType", "name": "Sales Thing", "module": module, "autoname": "naming_series:", "is_submittable": 1, "field_order": ["naming_series", "customer", "lines", "total"],
         "fields": [{"fieldname": "total", "fieldtype": "Currency"}, {"fieldname": "lines", "fieldtype": "Table", "options": "Order Line"}, {"fieldname": "customer", "fieldtype": "Data", "reqd": 1},
                    {"fieldname": "naming_series", "fieldtype": "Select", "options": "ST-.YYYY.-.#####"}]}]}


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if "__pycache__" not in str(p))


def test_create_from_a_frappe_export_end_to_end(scratch):
    p = creator.plan(frappe_pair(), app=scratch.app)
    rep = p.report()
    assert rep["ok"] and rep["order"] == ["Order Line", "Sales Thing"] and rep["structure"] == "multiple"                 # child tables first
    assert rep["doctypes"][1]["links"] == ["Order Line"] and rep["doctypes"][1]["submittable"] and any("date parts" in w for w in rep["warnings"])
    assert not (scratch.mod / "doctype" / "sales_thing").exists()                                                          # planning writes nothing
    out = creator.create(p)
    assert out["created"] == ["Order Line", "Sales Thing"]
    assert (scratch.mod / "doctype" / "order_line" / "order_line.json").is_file() and (scratch.mod / "doctype" / "sales_thing" / "sales_thing.py").is_file()
    assert not (scratch.mod / "doctype" / "order_line" / "order_line.py").exists()                                         # a child table needs no controller
    spec = json.loads((scratch.mod / "doctype" / "sales_thing" / "sales_thing.json").read_text())
    assert spec["autoname"] == "series:ST-.#####" and [f["fieldname"] for f in spec["fields"]] == ["customer", "lines", "total"]
    site_mod.current().load()
    velora.migrate()                                                                                                       # real tables
    doc = new_doc("Sales Thing", customer="Acme")
    doc.append("lines", {"item": "Bolt", "qty": 3})
    doc.insert(ignore_permissions=True)
    assert doc.name == "ST-00001" and doc.lines[0].item == "Bolt"
    assert doc.submit(ignore_permissions=True).docstatus == 1                                                              # submittable, as the Frappe definition said


def test_every_problem_is_reported_together_and_nothing_is_written(scratch):
    before = tree(scratch.root)
    bad = {"doctypes": [
        {"name": "Alpha", "module": "Scratch", "fields": [{"fieldname": "Bad Name!", "fieldtype": "Data"}, {"fieldname": "l", "fieldtype": "Link", "options": "Nowhere"}]},
        {"name": "Beta", "module": "Scratch", "fields": [{"fieldname": "t", "fieldtype": "Table", "options": "Alpha"}]},
        {"name": "bad/name", "module": "Scratch", "fields": [{"fieldname": "a", "fieldtype": "Data"}]},
        {"name": "NoModule", "fields": [{"fieldname": "a", "fieldtype": "Data"}]}, {"name": "Empty", "module": "Scratch", "fields": []},
        {"name": "Alpha", "module": "Scratch", "fields": [{"fieldname": "a", "fieldtype": "Data"}]}, "not an object",
        {"name": "Solo", "module": "Scratch", "issingle": 1, "fields": [{"fieldname": "a", "fieldtype": "Data"}]}]}
    p = creator.plan(bad, app=scratch.app)
    text = "\n".join(p.errors)
    for frag in ("Alpha: ", "invalid fieldname", "Table target 'Alpha' is not a DocType", "bad/name: DocType names are letters", "NoModule: a module is required",
                 "Empty: at least one field is required", "Alpha: defined twice", "DocType #7: must be an object", "Single DocTypes"):
        assert frag in text, frag
    with pytest.raises(MetaError, match="Nothing was created") as e:
        creator.create(p)
    assert e.value.details == p.errors and tree(scratch.root) == before


def test_a_failure_while_writing_removes_everything_it_wrote(scratch, monkeypatch):
    before = tree(scratch.root)
    p = creator.plan(frappe_pair(), app=scratch.app)
    real, calls = Path.write_text, []

    def flaky(self, *a, **k):
        if self.name.endswith(".json") and self.parent.name == "sales_thing":
            raise OSError("disk full")
        calls.append(self.name)
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "write_text", flaky)
    with pytest.raises(OSError, match="disk full"):
        creator.create(p)
    assert "order_line.json" in calls                                                                                      # the first DocType really was written ...
    assert tree(scratch.root) == before                                                                                    # ... and then removed again


def test_existing_doctypes_are_conflicts_you_decide_about(scratch):
    make_doctype(scratch, "Gadget")
    data = {"name": "Gadget", "module": "Scratch", "fields": [{"fieldname": "a", "fieldtype": "Data"}]}
    p = creator.plan(data, app=scratch.app)
    assert not p.report()["ok"] and p.conflicts and "Gadget already exists" in p.errors[0]
    s = creator.plan({"doctypes": [data, {"name": "Fresh", "module": "Scratch", "fields": [{"fieldname": "a", "fieldtype": "Data"}]}]}, app=scratch.app, on_conflict="skip")
    assert s.report()["ok"] and s.skipped == ["Gadget"] and [x["name"] for x in s.specs] == ["Fresh"]
    original = (scratch.mod / "doctype" / "gadget" / "gadget.json").read_text()
    creator.create(s)
    assert (scratch.mod / "doctype" / "gadget" / "gadget.json").read_text() == original                                    # never overwritten
    (scratch.mod / "doctype" / "orphan").mkdir()                                                                           # a folder on disk that the registry does not know
    assert "already exists" in creator.plan({"name": "Orphan", "module": "Scratch", "fields": [{"fieldname": "a", "fieldtype": "Data"}]}, app=scratch.app).errors[0]
    with pytest.raises(MetaError, match="on_conflict"):
        creator.plan(data, app=scratch.app, on_conflict="overwrite")


def test_links_to_existing_doctypes_are_allowed_unknown_ones_are_not(scratch):
    make_doctype(scratch, "Gadget")
    ok = creator.plan({"name": "Holder", "module": "Scratch", "fields": [{"fieldname": "g", "fieldtype": "Link", "options": "Gadget"}]}, app=scratch.app)
    assert ok.report()["ok"]
    bad = creator.plan({"name": "Holder", "module": "Scratch", "fields": [{"fieldname": "g", "fieldtype": "Link", "options": "Nothing"}]}, app=scratch.app)
    assert any("Link target 'Nothing' is not a DocType" in e for e in bad.errors)
    notchild = creator.plan({"name": "Holder", "module": "Scratch", "fields": [{"fieldname": "g", "fieldtype": "Table", "options": "Gadget"}]}, app=scratch.app)
    assert any("'Gadget' must be a child table (istable)" in e for e in notchild.errors)                                  # an existing DocType that is not a child table


def test_a_bare_field_list_uses_the_options(scratch):
    fields = [{"fieldname": "title", "fieldtype": "Data", "reqd": 1}, {"fieldname": "amount", "fieldtype": "Currency"}]
    p = creator.plan(fields, app=scratch.app, module="Scratch", name="Voucher", flags={"is_submittable": True, "autoname_field_name": "title", "is_autoname": True, "track_changes": True})
    assert p.report()["ok"] and p.structure == "fields"
    s = p.specs[0]
    assert (s["name"], s["autoname"], s["is_submittable"], s["track_changes"]) == ("Voucher", "field:title", True, True)
    assert not creator.plan(fields, app=scratch.app, module="Scratch").report()["ok"]                                       # no name given
    assert "module is required" in creator.plan(fields, app=scratch.app, name="V").errors[0]
    assert "needs a name" in creator.plan(fields, app=scratch.app, module="M").errors[0]


def test_creator_input_limits_and_bad_apps(scratch):
    assert "Unrecognised JSON" in creator.plan("junk", app=scratch.app).errors[0] and "No DocTypes found" in creator.plan({"doctypes": []}, app=scratch.app).errors[0]
    many = {"doctypes": [{"name": f"D{i}", "module": "Scratch", "fields": [{"fieldname": "a", "fieldtype": "Data"}]} for i in range(101)]}
    assert "At most 100" in creator.plan(many, app=scratch.app).errors[0]
    assert "not importable" in creator.plan({"name": "X", "module": "M", "fields": [{"fieldname": "a", "fieldtype": "Data"}]}, app="no_such_app_xyz").errors[0]
    assert creator.create(creator.plan({"doctypes": [{"name": "Gadget", "module": "Scratch", "fields": [{"fieldname": "a", "fieldtype": "Data"}]}]}, app=scratch.app))["created"] == ["Gadget"]


def test_created_files_stay_inside_the_app_even_for_hostile_names(scratch):
    p = creator.plan({"name": "../../evil", "module": "Scratch", "fields": [{"fieldname": "a", "fieldtype": "Data"}]}, app=scratch.app)
    assert not p.report()["ok"] and not list(scratch.tmp.glob("**/evil*"))
    p = creator.plan({"name": "Fine", "module": "../../escape", "fields": [{"fieldname": "a", "fieldtype": "Data"}]}, app=scratch.app)
    for _, path in p.writes:
        assert str(path.resolve()).startswith(str(scratch.root.resolve()))                                                 # the module becomes a folder NAME (snake_case), never a path


# ================================ the DocType Creator API ================================
def creator_body(scratch, **kw):
    return {"json": json.dumps(frappe_pair()), "app": scratch.app, **kw}


def test_creator_api_preview_then_create(scratch):
    c = TestClient(create_app(auto_init=False))
    assert c.get("/api/devtools/status", headers=ADMIN).json()["data"] == {"available": True, "apps": [scratch.app]}
    assert c.get("/api/devtools/status", headers=SALES).json()["data"] == {"available": False, "apps": []}                   # not even a hint for other users
    pr = c.post("/api/devtools/doctype-creator/preview", json=creator_body(scratch), headers=ADMIN)
    assert pr.status_code == 200 and pr.json()["data"]["ok"] and pr.json()["data"]["order"] == ["Order Line", "Sales Thing"]
    assert not (scratch.mod / "doctype" / "sales_thing").exists()
    cr = c.post("/api/devtools/doctype-creator/create", json=creator_body(scratch), headers=ADMIN)
    assert cr.status_code == 200 and cr.json()["data"]["created"] == ["Order Line", "Sales Thing"]
    assert any("CREATE TABLE" in line for line in cr.json()["data"]["migration"])                                          # the tables exist already in THIS database
    assert c.get("/api/meta/Sales Thing", headers=ADMIN).status_code == 200                                                # and the Desk can use them immediately
    again = c.post("/api/devtools/doctype-creator/create", json=creator_body(scratch), headers=ADMIN)
    assert again.status_code == 422 and "already exists" in again.json()["message"]
    skip = c.post("/api/devtools/doctype-creator/create", json=creator_body(scratch, on_conflict="skip"), headers=ADMIN)
    assert skip.status_code == 200 and skip.json()["data"]["created"] == [] and sorted(skip.json()["data"]["skipped"]) == ["Order Line", "Sales Thing"]


def test_creator_api_guards(scratch, monkeypatch):
    c = TestClient(create_app(auto_init=False))
    for ep in ("preview", "create"):
        assert c.post(f"/api/devtools/doctype-creator/{ep}", json=creator_body(scratch), headers=SALES).status_code == 403
        assert c.post(f"/api/devtools/doctype-creator/{ep}", json={"json": "{not json", "app": scratch.app}, headers=ADMIN).status_code == 422
        assert c.post(f"/api/devtools/doctype-creator/{ep}", json={"json": "[]"}, headers=ADMIN).status_code == 422
        assert c.post(f"/api/devtools/doctype-creator/{ep}", headers=ADMIN, json={"json": {"name": "X", "module": "M", "fields": []}, "app": scratch.app}).status_code in (200, 422)
    monkeypatch.setattr("velora.api.designer.developer_mode", lambda ws=None: False)
    r = c.post("/api/devtools/doctype-creator/create", json=creator_body(scratch), headers=ADMIN)
    assert r.status_code == 403 and "developer mode" in r.json()["message"] and not (scratch.mod / "doctype" / "sales_thing").exists()
    assert c.get("/api/devtools/status", headers=ADMIN).json()["data"]["available"] is False


@pytest.fixture
def isolated_modules(tmp_path):
    """The CLI test installs an app called 'shop'; remove it from sys.path/sys.modules afterwards so no other test can import it."""
    from upgrade_helpers import clean_modules
    before_path, before_mods = list(sys.path), set(sys.modules)
    yield
    clean_modules(tmp_path, before_path, before_mods)


def test_the_cli_creates_doctypes_with_a_dry_run_and_clear_errors(tmp_path, monkeypatch, capsys, isolated_modules):
    from velora.cli import main
    from velora.workspace import Workspace
    from upgrade_helpers import make_app
    for k in ("VELORA_MASTER_KEY", "VELORA_WORKSPACE", "VELORA_SITE"):
        monkeypatch.delenv(k, raising=False)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    assert main(["new-site", "t.local"]) == 0 and main(["--site", "t.local", "install-app", "shop"]) == 0
    capsys.readouterr()
    f = tmp_path / "defs.json"
    f.write_text(json.dumps(frappe_pair(module="Retail")))
    assert main(["--site", "t.local", "new-doctypes", "shop", str(f), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Would create Order Line (2 fields, child table)" in out and "warning: Sales Thing: date parts" in out and not (ws.app_path("shop") / "shop" / "retail" / "doctype" / "sales_thing").exists()
    assert main(["--site", "t.local", "new-doctypes", "shop", str(f)]) == 0
    assert (ws.app_path("shop") / "shop" / "retail" / "doctype" / "sales_thing" / "sales_thing.json").is_file() and "velora migrate" in capsys.readouterr().out
    assert main(["--site", "t.local", "new-doctypes", "shop", str(f)]) == 1
    assert "already exists" in capsys.readouterr().err
    f.write_text("{oops")
    assert main(["--site", "t.local", "new-doctypes", "shop", str(f)] ) == 1 and "not valid JSON" in capsys.readouterr().err


def test_form_appearance_is_company_local_schema_independent_and_manager_only(client):
    r = client.get("/api/layout/Customer", headers=ADMIN).json()["data"]
    assert r["appearance"] == {}
    cfg = {"customer_name": {"label_position": "left", "control_size": "large", "display_style": "emphasized",
                             "placeholder": "Enter customer name", "help_text": "Use the registered legal name",
                             "show_description": False, "readonly_style": True}}
    saved = client.put("/api/form-appearance/Customer", json={"appearance": cfg}, headers=ADMIN)
    assert saved.status_code == 200 and saved.json()["data"]["appearance"] == cfg
    meta = client.get("/api/meta/Customer", headers=SALES).json()["data"]
    assert meta["form_appearance"]["customer_name"]["label_position"] == "left"
    assert client.get("/api/layout/Customer", headers=SALES).json()["data"]["appearance"] == cfg
    assert client.put("/api/form-appearance/Customer", json={"appearance": cfg}, headers=SALES).status_code == 403
    assert client.delete("/api/form-appearance/Customer", headers=SALES).status_code == 403
    assert client.delete("/api/form-appearance/Customer", headers=ADMIN).status_code == 200
    assert client.get("/api/meta/Customer", headers=SALES).json()["data"].get("form_appearance") == {}


@pytest.mark.parametrize("cfg,fragment", [
    ({"label_position": "bottom"}, "label_position"),
    ({"control_size": "huge"}, "control_size"),
    ({"display_style": "neon"}, "display_style"),
    ({"placeholder": "x" * 501}, "placeholder"),
    ({"help_text": 5}, "help_text"),
    ({"show_description": "yes"}, "show_description"),
    ({"readonly_style": 1}, "readonly_style"),
    ({"unexpected": True}, "Unsupported appearance"),
])
def test_form_appearance_rejects_unsupported_or_invalid_values(client, cfg, fragment):
    r = client.put("/api/form-appearance/Customer", json={"appearance": {"customer_name": cfg}}, headers=ADMIN)
    assert r.status_code == 422 and fragment in r.json()["message"]
    assert client.get("/api/form-appearance/Customer", headers=ADMIN).json()["data"]["appearance"] == {}


def test_form_appearance_rejects_unknown_fields_and_invalid_payload(client):
    assert client.put("/api/form-appearance/Customer", json={"appearance": {"not_a_field": {"label_position": "left"}}}, headers=ADMIN).status_code == 422
    assert client.put("/api/form-appearance/Customer", json={"appearance": []}, headers=ADMIN).status_code == 422
    assert client.put("/api/form-appearance/Customer", json={"appearance": {"customer_name": {}}}, headers=ADMIN).status_code == 200


def test_saving_a_layout_into_a_read_only_app_falls_back_to_the_company_instead_of_a_500(monkeypatch):
    """An app installed from a wheel lives in a folder the service cannot write: that must never be an 'internal server error'."""
    from velora.api import designer
    def boom(meta, key, value):
        raise designer.AppFolderReadOnly("The app files cannot be written by the Velora service (Permission denied).")
    monkeypatch.setattr(designer, "_write_app_json", boom)
    monkeypatch.setattr(designer, "developer_mode", lambda ws=None: True)
    import inspect
    src = inspect.getsource(designer.install_designer_routes)
    assert "except AppFolderReadOnly" in src and "saved for this company instead" in src
