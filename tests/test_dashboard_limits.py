"""Dashboards: widgets are validated when saved, and a stored dashboard with bad values can never become a server error."""
import pytest

from velora import dashboards, new_doc
from velora.exceptions import ValidationError


def save(widgets, **kw):
    return dashboards.save({"name": kw.pop("name", "Sales"), "widgets": widgets, **kw})


GOOD = {"type": "group_by", "doctype": "Customer", "field": "status", "limit": 5}


def test_a_valid_dashboard_saves_and_runs(site):
    new_doc("Customer", customer_name="A", status="Active").insert()
    d = save([GOOD, {"type": "number", "doctype": "Customer"}, {"type": "aggregate", "doctype": "Customer", "fields": ["credit_limit"]}])
    out = dashboards.run(d["id"])
    assert out["results"][0]["value"] == [{"value": "Active", "count": 1}] and out["results"][1]["value"] == 1


@pytest.mark.parametrize("limit", [0, -3, 101, 10 ** 9, "abc", "5", 2.5, True, None, [1]])
def test_a_widget_limit_must_be_a_whole_number_from_1_to_100(site, limit):
    with pytest.raises(ValidationError, match="limit must be a whole number from 1 to 100"):
        save([{**GOOD, "limit": limit}])


@pytest.mark.parametrize("limit", [1, 12, 100])
def test_limits_inside_the_range_are_accepted(site, limit):
    assert save([{**GOOD, "limit": limit}])["widgets"][0]["limit"] == limit


def test_sizes_are_capped(site):
    with pytest.raises(ValidationError, match="at most 50 widgets"):
        save([{"type": "number", "doctype": "Customer"}] * 51)
    assert len(save([{"type": "number", "doctype": "Customer"}] * 50, name="Full")["widgets"]) == 50
    with pytest.raises(ValidationError, match="name is too long"):
        save([GOOD], name="x" * 141)
    with pytest.raises(ValidationError, match="at most 20 field names"):
        save([{"type": "aggregate", "doctype": "Customer", "fields": ["credit_limit"] * 21}])
    with pytest.raises(ValidationError, match="list of at most 20"):
        save([{"type": "aggregate", "doctype": "Customer", "fields": [1, 2]}])
    with pytest.raises(ValidationError, match="must be a field name"):
        save([{"type": "group_by", "doctype": "Customer", "field": ["status"]}])


@pytest.mark.parametrize("bad", ["abc", None, -5, 10 ** 9, [], {}, 2.9])
def test_a_dashboard_stored_with_a_bad_limit_still_runs_instead_of_failing(site, bad):
    """Dashboards saved before validation existed may hold anything."""
    d = save([GOOD])
    from sqlalchemy import update
    with dashboards.db.transaction() as c:
        c.execute(update(dashboards.dashboard).where(dashboards.dashboard.c.id == d["id"]).values(widgets=[{**GOOD, "limit": bad}]))
    assert dashboards.run(d["id"])["results"][0]["type"] == "group_by"


def test_the_limit_helper():
    assert [dashboards._limit(v) for v in ("abc", None, -5, 0, 7, 100, 101, 10 ** 9, 2.9, "8")] == [12, 12, 1, 1, 7, 100, 100, 100, 2, 8]


def test_kpi_targets_calculate_attainment_and_variance(site):
    new_doc("Customer", customer_name="KPI A", status="Active", credit_limit=120).insert()
    d = save([{"type":"number","doctype":"Customer","target_value":1,"target_direction":"at_least","unit":"customers"},
              {"type":"aggregate","doctype":"Customer","fields":["credit_limit"],"target_value":100,"target_field":"credit_limit","target_direction":"at_least","unit":"NGN"}])
    result = dashboards.run(d["id"])["results"]
    assert result[0]["kpi"]["passed"] is True
    assert result[0]["kpi"]["variance"] == 0
    assert result[1]["kpi"]["actual"] == 120
    assert result[1]["kpi"]["attainment_percent"] == 120
    assert result[1]["kpi"]["passed"] is True


@pytest.mark.parametrize("widget", [
    {"type":"number","doctype":"Customer","target_value":"bad"},
    {"type":"number","doctype":"Customer","target_value":float("inf")},
    {"type":"group_by","doctype":"Customer","field":"status","target_value":5},
    {"type":"number","doctype":"Customer","target_value":5,"target_direction":"equal"},
    {"type":"aggregate","doctype":"Customer","fields":["credit_limit"],"target_value":5,"target_field":"status"},
])
def test_invalid_kpi_target_is_rejected(site, widget):
    with pytest.raises(ValidationError):
        save([widget])
