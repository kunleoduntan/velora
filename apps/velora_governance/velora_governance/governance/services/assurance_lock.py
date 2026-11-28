"""Assured data must not change silently.

Once a Sustainability Assurance for a reporting period is Completed (and still locks), GHG Calculations and Data Points of that entity and period
cannot be created, edited or deleted. A Governance Administrator can release the lock on the assurance record, which needs a written reason and is
stamped with who and when (and is recorded in the document history); a new assurance engagement locks the period again.
"""
from __future__ import annotations

from velora import get_list, throw

STANDARDS = ["ISAE 3000 (Revised)", "ISSA 5000", "ISAE 3410 (GHG statements)", "AA1000AS", "Other"]
OPINIONS = ["Unmodified", "Qualified", "Adverse", "Disclaimer"]
ASSURANCE_LEVELS = {"Limited", "Reasonable"}


def _period_labels(period_name: str | None) -> set[str]:
    if not period_name:
        return set()
    rows = get_list("Sustainability Reporting Period", filters=[["name", "=", period_name]], fields=["name", "period_name"], limit=1, ignore_permissions=True)
    labels = {period_name}
    for r in rows:
        labels |= {r.get("name"), r.get("period_name")}
    return {x for x in labels if x}


def locking_assurance(governance_entity: str | None, reporting_period: str | None) -> str | None:
    """Name of the Completed, still-locking assurance covering this entity and period, if any."""
    if not governance_entity or not reporting_period:
        return None
    rows = get_list("Sustainability Assurance", filters=[["governance_entity", "=", governance_entity], ["assurance_status", "=", "Completed"], ["locks_period_data", "=", 1]],
                    fields=["name", "reporting_period"], limit=1000, ignore_permissions=True)
    for r in rows:
        if reporting_period in _period_labels(r.get("reporting_period")):
            return r["name"]
    return None


def assert_unlocked(governance_entity: str | None, reporting_period: str | None, what: str) -> None:
    held = locking_assurance(governance_entity, reporting_period)
    if held:
        throw(f"{what} cannot be changed: reporting period {reporting_period} is locked by the completed assurance {held}. "
              "A Governance Administrator can release the lock on that assurance record, giving a reason.")
