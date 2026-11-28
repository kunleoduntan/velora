"""Validation for governance configuration payloads; approvals remain engine-driven."""
from datetime import datetime


def validate_governance_configuration(*, automation_rules=None, templates=None, schedules=None, routing=None):
    rules = list(automation_rules or [])
    templates = list(templates or [])
    schedules = list(schedules or [])
    routing = list(routing or [])
    issues = []
    rule_names = set()
    for idx, rule in enumerate(rules):
        name = str(rule.get("name") or rule.get("rule_id") or f"rule-{idx+1}")
        if name in rule_names:
            issues.append({"category": "automation_rule", "item": name, "severity": "error", "code": "duplicate_rule_id"})
        rule_names.add(name)
        if not rule.get("enabled", True):
            continue
        if not rule.get("trigger"):
            issues.append({"category": "automation_rule", "item": name, "severity": "error", "code": "missing_trigger"})
        if not rule.get("action_type"):
            issues.append({"category": "automation_rule", "item": name, "severity": "error", "code": "missing_action_type"})
        if rule.get("action_type") in {"approval", "approve", "reject"}:
            issues.append({"category": "automation_rule", "item": name, "severity": "error", "code": "approval_must_use_native_workflow_engine"})
    template_ids = {str(t.get("name") or t.get("template_id")) for t in templates}
    for t in templates:
        if not t.get("subject") and not t.get("body"):
            issues.append({"category": "template", "item": t.get("name", t.get("template_id")), "severity": "warning", "code": "empty_template"})
    for schedule in schedules:
        name = schedule.get("name", schedule.get("schedule_id"))
        if schedule.get("enabled", True) and not schedule.get("cron"):
            issues.append({"category": "schedule", "item": name, "severity": "error", "code": "missing_cron_expression"})
        if schedule.get("template") and str(schedule.get("template")) not in template_ids:
            issues.append({"category": "schedule", "item": name, "severity": "error", "code": "unknown_template_reference"})
    for route in routing:
        name = route.get("name", route.get("route_id"))
        if route.get("enabled", True) and not route.get("destination"):
            issues.append({"category": "routing", "item": name, "severity": "error", "code": "missing_destination"})
    errors = [issue for issue in issues if issue["severity"] == "error"]
    warnings = [issue for issue in issues if issue["severity"] == "warning"]
    return {"valid": not errors, "error_count": len(errors), "warning_count": len(warnings),
            "issues": issues, "approval_engine_boundary": "Approval routing and approvers must be configured in the native workflow engine, not duplicated here."}
