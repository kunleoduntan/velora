"""Errors that help (velora.advice): every refusal can carry a hint, links that fix it and the field; warnings never block."""
from velora.advice import advise, collect, warn
from velora.exceptions import (DocStatusError, DuplicateEntryError, LinkValidationError, MandatoryError, PermissionDenied,
                               TimestampMismatchError, ValidationError)


def test_framework_rules_cover_the_everyday_refusals():
    a = advise(MandatoryError("Customer: Customer Name is required", details={"field": "customer_name"}))
    assert a["hint"] == "Fill in Customer Name, then save again." and a["field"] == "customer_name"
    a = advise(LinkValidationError("Sales Invoice: Customer 'Acme' does not exist (Customer)"))
    assert "Pick an existing Customer" in a["hint"] and a["actions"] == [{"label": "Create Customer", "href": "#/app/Customer/new"}]
    a = advise(PermissionDenied("sam@x.test has no 'submit' permission on Sales Invoice"))
    assert "None of your roles may submit Sales Invoice" in a["hint"] and a["actions"][0]["href"] == "#/settings/permissions"
    assert "already exists" in advise(DuplicateEntryError("dup"))["hint"]
    assert "Reload" in advise(TimestampMismatchError("changed"))["hint"]
    assert "Amend" in advise(DocStatusError("Cannot edit a cancelled document"))["hint"]


def test_explicit_advice_wins_and_unknown_errors_get_none():
    own = {"hint": "Do X.", "actions": []}
    assert advise(ValidationError("anything", advice=own)) is own
    assert advise(ValidationError("Something nobody has a rule for")) is None


def test_a_rule_for_one_kind_does_not_answer_another():
    # the Duplicate rule matches any text, but only for DuplicateEntryError
    assert advise(ValidationError("some text")) is None


def test_warnings_are_collected_per_request_and_never_raise():
    warn("outside a request is only logged")              # no bucket: must not fail
    with collect() as notes:
        warn("Rate is old", hint="Update it")
        warn("Rate is old", hint="Update it")              # the same note once
        assert notes == [{"message": "Rate is old", "hint": "Update it", "actions": []}]
    with collect() as notes:
        assert notes == []
