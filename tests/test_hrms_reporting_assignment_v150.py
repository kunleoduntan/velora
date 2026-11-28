"""Focused date validation tests for HR reporting assignments."""
from datetime import date
import importlib
import sys
from pathlib import Path
import pytest


def _module_and_registry():
    project = Path(__file__).resolve().parents[1]
    app_path = str(project / "apps" / "velora_erp")
    if app_path not in sys.path:
        sys.path.insert(0, app_path)
    from velora.meta.registry import Registry
    registry = Registry()
    registry.load(["velora_erp", "velora_projectone"])
    module = importlib.import_module(registry._doctypes["Reporting Assignment"].controller_module)
    return module, registry


def test_reporting_assignment_date_parser():
    module, _registry = _module_and_registry()
    assert module._as_date("2026-01-15") == date(2026, 1, 15)
    assert module._as_date(date(2026, 1, 15)) == date(2026, 1, 15)
    assert module._as_date(None) is None


def test_reporting_assignment_rejects_invalid_date_range(monkeypatch):
    module, registry = _module_and_registry()
    from velora.exceptions import ValidationError
    # Exercise the controller without requiring a live database.
    controller = object.__new__(module.ReportingAssignment)
    controller.employee = "EMP-001"
    controller.department = "DEPT-001"
    controller.effective_from = "2026-05-01"
    controller.effective_to = "2026-04-30"
    controller.assignment_status = "Draft"
    controller.is_primary = 1
    with pytest.raises(ValidationError):
        controller.validate()


def test_reporting_assignment_rejects_overlapping_approved_primary_assignment(monkeypatch):
    module, _registry = _module_and_registry()
    from velora.exceptions import ValidationError
    from velora.permissions import Session
    controller = object.__new__(module.ReportingAssignment)
    controller.employee = "EMP-001"
    controller.department = "DEPT-002"
    controller.effective_from = "2026-06-01"
    controller.effective_to = "2026-12-31"
    controller.assignment_status = "Approved"
    controller.is_primary = 1
    controller.name = "RA-NEW"
    monkeypatch.setattr(module, "get_session", lambda: Session(user="hr-manager", roles=["HR Manager"]))
    monkeypatch.setattr(module, "get_list", lambda *a, **k: [
        {"name": "RA-OLD", "effective_from": "2026-01-01", "effective_to": "2026-08-31"}
    ])
    with pytest.raises(ValidationError, match="overlaps"):
        controller.validate()


