"""Governance UI integration manifest contract; not a claim that UI is installed."""
REQUIRED_SURFACES = {
    "operations_dashboard": {"route": "governance/operations", "api": "governance.operations.dashboard"},
    "automation_monitor": {"route": "governance/automation", "api": "governance.automation.history"},
    "board_workspace": {"route": "governance/board-workspace", "api": "governance.portal.board_workspace"},
    "committee_workspace": {"route": "governance/committee-workspace", "api": "governance.portal.committee_workspace"},
    "configuration_center": {"route": "governance/configuration", "api": "governance.configuration.validate"},
}

def validate_ui_integration_manifest(manifest):
    manifest = dict(manifest or {})
    missing = []
    invalid = []
    for key, required in REQUIRED_SURFACES.items():
        item = manifest.get(key)
        if not isinstance(item, dict):
            missing.append(key); continue
        for field, value in required.items():
            if item.get(field) != value:
                invalid.append({"surface": key, "field": field, "expected": value,
                               "actual": item.get(field)})
    extra = sorted(set(manifest) - set(REQUIRED_SURFACES))
    return {"status": "valid" if not missing and not invalid else "invalid",
            "missing_surfaces": missing, "invalid_fields": invalid, "extra_surfaces": extra,
            "ui_installed": False}
