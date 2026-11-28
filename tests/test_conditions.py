from types import SimpleNamespace

from velora.meta.conditions import evaluate_condition
from velora.meta.spec import DocType
from velora.devtools.creator import convert


def test_condition_evaluator_supports_frappe_eval_subset():
    doc = {"payment_type": "Expense", "amount": 2500, "approved": 1}
    assert evaluate_condition('eval:doc.payment_type == "Expense"', doc)
    assert evaluate_condition('eval:doc.amount > 0 and doc.approved == 1', doc)
    assert evaluate_condition('eval:doc.payment_type in ["Expense", "Refund"]', doc)
    assert evaluate_condition('eval:doc.approved', doc)
    assert evaluate_condition("payment_type", doc)
    assert not evaluate_condition("", doc)
    assert not evaluate_condition('eval:doc.payment_type == "Supplier"', doc)
    assert not evaluate_condition('eval:__import__("os").system("id")', doc)


def test_conditional_properties_round_trip_in_metadata():
    spec = {
        "name": "Conditional Sample", "module": "Core", "fields": [
            {"fieldname": "kind", "fieldtype": "Select", "options": ["Expense", "Supplier"]},
            {"fieldname": "supplier", "fieldtype": "Data", "depends_on": 'eval:doc.kind == "Supplier"',
             "mandatory_depends_on": 'eval:doc.kind == "Supplier"', "read_only_depends_on": 'eval:doc.kind == "Expense"'},
        ],
    }
    dt = DocType.from_dict(spec)
    field = dt.get_field("supplier")
    assert field.depends_on == 'eval:doc.kind == "Supplier"'
    assert field.mandatory_depends_on == 'eval:doc.kind == "Supplier"'
    assert field.read_only_depends_on == 'eval:doc.kind == "Expense"'
    exported = dt.to_dict()["fields"][1]
    assert exported["depends_on"] == field.depends_on
    assert exported["mandatory_depends_on"] == field.mandatory_depends_on
    assert exported["read_only_depends_on"] == field.read_only_depends_on


def test_metadata_rejects_unsafe_dependency_expressions():
    from velora.exceptions import MetaError
    import pytest
    with pytest.raises(MetaError):
        DocType.from_dict({"name": "Unsafe", "fields": [
            {"fieldname": "x", "fieldtype": "Data", "depends_on": 'eval:__import__("os").system("id")'}
        ]})


def test_frappe_creator_preserves_conditional_field_properties_without_warning():
    definition = {
        "name": "Conditional Sample", "module": "Core", "fields": [
            {"fieldname": "kind", "fieldtype": "Select", "options": "Expense\nSupplier"},
            {"fieldname": "supplier", "fieldtype": "Data", "depends_on": 'eval:doc.kind == "Supplier"',
             "mandatory_depends_on": 'eval:doc.kind == "Supplier"', "read_only_depends_on": 'eval:doc.kind == "Expense"'},
        ],
    }
    converted, warnings = convert(definition)
    conditional = converted["fields"][1]
    assert conditional["depends_on"].startswith("eval:")
    assert conditional["mandatory_depends_on"].startswith("eval:")
    assert conditional["read_only_depends_on"].startswith("eval:")
    assert not any("conditional" in warning for warning in warnings)


def test_advanced_field_properties_round_trip_from_visual_designer_metadata():
    definition = {
        "name": "Advanced Sample", "module": "Core", "fields": [
            {"fieldname": "status", "fieldtype": "Select", "options": ["Open", "Closed"]},
            {"fieldname": "reference", "fieldtype": "Data", "description": "External reference",
             "unique": True, "read_only": True, "hidden": True, "in_standard_filter": True,
             "depends_on": 'eval:doc.status == "Open"',
             "mandatory_depends_on": 'eval:doc.status == "Open"',
             "read_only_depends_on": 'eval:doc.status == "Closed"'},
        ],
    }
    field = DocType.from_dict(definition).get_field("reference")
    exported = field.to_dict()
    assert exported["description"] == "External reference"
    assert exported["unique"] and exported["read_only"] and exported["hidden"]
    assert exported["in_standard_filter"]
    assert exported["depends_on"] == 'eval:doc.status == "Open"'
    assert exported["mandatory_depends_on"] == 'eval:doc.status == "Open"'
    assert exported["read_only_depends_on"] == 'eval:doc.status == "Closed"'
