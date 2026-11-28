"""Runtime configuration for Governance automation; validation is fail-closed."""
from __future__ import annotations
import json

DEFAULT_CONFIGURATION = {
    "automation_enabled": 1,
    "reminder_days_before": "30,14,7,3,1,0",
    "escalation_days_overdue": "1,7,14,30",
    "terminal_statuses": "Completed,Cancelled,Closed,Resolved",
    "max_attempts": 5,
    "max_batch_size": 100,
    "retry_base_minutes": 5,
    "retry_max_hours": 24,
    "owner_field_mapping": "{}",
    "recipient_overrides": "{}",
}
OWNER_FIELD_ALLOWLIST = {
    "Board Action": {"assigned_owner"},
    "Governance Obligation": {"responsible_owner"},
    "Corporate Filing": {"responsible_owner"},
    "Annual Return": set(),
    "Regulatory Correspondence": {"responsible_owner"},
    "Sustainability Data Collection Task": {"responsible_owner"},
}


def _csv_ints(value, *, minimum=0, maximum=3650):
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = [part.strip() for part in str(value or "").split(",") if part.strip()]
    parsed = []
    for value in values:
        number = int(value)
        if number < minimum or number > maximum:
            raise ValueError(f"numeric value {number} outside allowed range {minimum}..{maximum}")
        parsed.append(number)
    if len(set(parsed)) != len(parsed):
        raise ValueError("duplicate numeric values are not allowed")
    return sorted(parsed)


def _csv_strings(value):
    values = value if isinstance(value, (list, tuple)) else str(value or "").split(",")
    return sorted({str(v).strip() for v in values if str(v).strip()})


def validate_configuration(values):
    values = {**DEFAULT_CONFIGURATION, **(values or {})}
    errors = []
    try:
        reminders = _csv_ints(values.get("reminder_days_before"), maximum=3650)
        if not reminders:
            errors.append("at least one reminder offset is required")
    except (TypeError, ValueError) as exc:
        reminders, errors = [], errors + [f"reminder days: {exc}"]
    try:
        escalations = _csv_ints(values.get("escalation_days_overdue"), minimum=1, maximum=3650)
        if not escalations:
            errors.append("at least one escalation offset is required")
    except (TypeError, ValueError) as exc:
        escalations, errors = [], errors + [f"escalation days: {exc}"]
    terminal = _csv_strings(values.get("terminal_statuses"))
    if not terminal:
        errors.append("terminal statuses cannot be empty")
    bounded = {"max_attempts": (1, 20), "max_batch_size": (1, 250),
               "retry_base_minutes": (1, 1440), "retry_max_hours": (1, 168)}
    integers = {}
    for key, (minimum, maximum) in bounded.items():
        try:
            value = int(values.get(key, DEFAULT_CONFIGURATION[key]))
            if not minimum <= value <= maximum:
                raise ValueError(f"must be between {minimum} and {maximum}")
            integers[key] = value
        except (TypeError, ValueError) as exc:
            errors.append(f"{key}: {exc}")
    try:
        owner_map = values.get("owner_field_mapping") or "{}"
        owner_map = owner_map if isinstance(owner_map, dict) else json.loads(owner_map)
        if not isinstance(owner_map, dict):
            raise ValueError("must be a JSON object")
        for doctype, fieldname in owner_map.items():
            if doctype not in OWNER_FIELD_ALLOWLIST:
                raise ValueError(f"unsupported source DocType: {doctype}")
            if fieldname not in OWNER_FIELD_ALLOWLIST[doctype]:
                raise ValueError(f"unsupported owner field {fieldname!r} for {doctype}")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        owner_map, errors = {}, errors + [f"owner field mapping: {exc}"]
    try:
        overrides = values.get("recipient_overrides") or "{}"
        overrides = overrides if isinstance(overrides, dict) else json.loads(overrides)
        if not isinstance(overrides, dict):
            raise ValueError("must be a JSON object")
        for doctype, recipient in overrides.items():
            if doctype not in OWNER_FIELD_ALLOWLIST:
                raise ValueError(f"unsupported source DocType: {doctype}")
            if not isinstance(recipient, str) or not recipient.strip() or len(recipient.strip()) > 140:
                raise ValueError(f"recipient for {doctype} must be a non-empty user identifier")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        overrides, errors = {}, errors + [f"recipient overrides: {exc}"]
    return {"valid": not errors, "errors": errors,
            "normalized": {"automation_enabled": int(bool(values.get("automation_enabled", 1))),
                "reminder_days_before": reminders, "escalation_days_overdue": escalations,
                "terminal_statuses": terminal, **integers, "owner_field_mapping": owner_map,
                "recipient_overrides": overrides}}


def load_configuration(api=None):
    """Load GAC settings through native Document API; default safely if not seeded."""
    if api is None:
        from velora import get_list, get_doc
        api = {"get_list": get_list, "get_doc": get_doc}
    rows = api["get_list"]("Governance Automation Configuration", filters={"name": "GAC"},
        fields=["name"], limit=1, ignore_permissions=True)
    if not rows:
        return validate_configuration(DEFAULT_CONFIGURATION)["normalized"]
    doc = api["get_doc"]("Governance Automation Configuration", "GAC", ignore_permissions=True)
    result = validate_configuration(doc.as_dict() if hasattr(doc, "as_dict") else dict(doc))
    if not result["valid"]:
        # Invalid administrator configuration disables execution instead of guessing.
        normalized = validate_configuration(DEFAULT_CONFIGURATION)["normalized"]
        normalized["automation_enabled"] = 0
        normalized["configuration_errors"] = result["errors"]
        return normalized
    return result["normalized"]
