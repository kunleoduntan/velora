import pytest

from velora.exceptions import MetaError
from velora.meta.spec import DocType


def make(**over):
    base = {"name": "Thing", "fields": [{"fieldname": "title", "fieldtype": "Data"}]}
    base.update(over)
    return DocType.from_dict(base, source="test")


def test_valid_doctype_parses():
    dt = make()
    assert dt.get_field("title").has_column
    assert "title" in dt.column_names() and "name" in dt.column_names()


@pytest.mark.parametrize("fields,fragment", [
    ([{"fieldname": "Bad Name", "fieldtype": "Data"}], "invalid fieldname"),
    ([{"fieldname": "a", "fieldtype": "Nope"}], "unknown fieldtype"),
    ([{"fieldname": "a", "fieldtype": "Data"}, {"fieldname": "a", "fieldtype": "Int"}], "duplicate"),
    ([{"fieldname": "modified", "fieldtype": "Data"}], "system field"),
    ([{"fieldname": "l", "fieldtype": "Link"}], "needs 'options'"),
    ([{"fieldname": "s", "fieldtype": "Select"}], "Select needs options"),
])
def test_invalid_fields_report_all_problems(fields, fragment):
    with pytest.raises(MetaError, match=fragment):
        make(fields=fields)


def test_autoname_validation():
    with pytest.raises(MetaError, match="autoname"):
        make(autoname="whatever")
    with pytest.raises(MetaError, match="missing field"):
        make(autoname="field:nope")
    assert make(autoname="series:T-.####").autoname == "series:T-.####"


def test_field_autoname_forces_required_unique():
    f = make(autoname="field:title").get_field("title")
    assert f.required and f.unique


def test_registry_loads_demo_app(site):
    from velora import registry
    names = {d.name for d in registry.all()}
    assert {"Customer", "Customer Group", "Sales Order", "Sales Order Item", "Customer Contact"} <= names
    assert registry.get("Customer Contact").istable


def test_layout_breaks_keep_only_explicit_labels():
    dt = make(fields=[{"fieldname": "a", "fieldtype": "Data"}, {"fieldname": "col_x", "fieldtype": "Column Break"},
                      {"fieldname": "b", "fieldtype": "Data"}, {"fieldname": "sec_y", "fieldtype": "Section Break", "label": "More"}])
    by = {f["fieldname"]: f for f in dt.to_dict()["fields"]}
    assert by["col_x"]["label"] == "" and by["sec_y"]["label"] == "More" and by["a"]["label"] == "A"
