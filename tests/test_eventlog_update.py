"""The plain-language history says what an update actually did."""
from velora.eventlog import from_update_report

CURRENT = {"targets": [{"status": "up_to_date", "label": "COMP-001"}]}


def report(status="up_to_date", **kw):
    return {"status": status, "code": {"framework": None, "apps": [], **kw.pop("code", {})}, "upgrade": kw.pop("upgrade", CURRENT), **kw}


def test_new_velora_code_with_current_databases_is_an_update_not_a_no_op():
    title, ok, steps, details = from_update_report(report(code={"framework": {"from": "0.49.1", "to": "0.49.2"}}))
    assert title == "Update complete" and ok and details == {"from_version": "0.49.1", "to_version": "0.49.2"}
    assert steps[0]["text"] == "Updated Velora from 0.49.1 to 0.49.2"


def test_updated_apps_or_packages_are_updates_too():
    assert from_update_report(report(code={"apps": [{"name": "accounting", "commits": 3}]}))[0] == "Update complete"
    assert from_update_report(report(packages=["pandas"]))[0] == "Update complete"


def test_nothing_new_is_still_reported_as_a_check():
    title, ok, steps, details = from_update_report(report())
    assert title == "Checked for updates: everything is current" and ok and details["to_version"] is None


def test_the_other_outcomes_keep_their_titles():
    assert from_update_report(report("success", upgrade={"targets": [{"status": "upgraded", "label": "COMP-001"}]}))[0] == "Update complete"
    assert from_update_report(report("rolled_back", code={"framework": {"from": "1", "to": "2"}}))[0] == "Update failed and was undone"       # a failed update is never called complete
    assert from_update_report(report("failed"))[0] == "Update failed" and from_update_report(report("partial"))[0] == "Update finished partially"
