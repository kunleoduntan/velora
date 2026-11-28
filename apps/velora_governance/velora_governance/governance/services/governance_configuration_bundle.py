"""v4.9 validated configuration bundle handling; approvals stay in native workflow."""
from copy import deepcopy

BUNDLE_KEYS = {"automation_rules", "templates", "schedules", "routing", "portal_views", "settings"}


def export_configuration_bundle(configuration, *, bundle_name="Governance Configuration", version="1"):
    configuration = configuration or {}
    return {"bundle_name": bundle_name, "bundle_version": str(version), "schema_version": "4.9.0",
            "configuration": {key: deepcopy(configuration.get(key, [] if key != "settings" else {})) for key in sorted(BUNDLE_KEYS)},
            "approval_workflow_included": False}


def validate_configuration_bundle(bundle, *, validation_callback=None):
    issues = []
    if not isinstance(bundle, dict): issues.append({"code": "bundle_not_object", "message": "Bundle must be an object."})
    else:
        if not bundle.get("bundle_name"): issues.append({"code": "missing_bundle_name", "message": "Bundle name is required."})
        config = bundle.get("configuration")
        if not isinstance(config, dict): issues.append({"code": "configuration_not_object", "message": "Configuration payload must be an object."})
        else:
            unknown = set(config) - BUNDLE_KEYS
            if unknown: issues.append({"code": "unknown_configuration_keys", "message": "Unknown keys: " + ", ".join(sorted(unknown))})
            if validation_callback:
                result = validation_callback(config)
                issues.extend(result.get("issues", []))
    return {"valid": not issues, "issues": issues, "issue_count": len(issues), "import_enabled": False,
            "approval_required": True, "approval_via_native_workflow": True, "version": "4.9.0"}


def prepare_configuration_import(bundle, *, validation_result, permission_checked=False):
    if not permission_checked:
        return {"prepared": False, "reason": "permission_check_required", "apply_enabled": False}
    if not validation_result or not validation_result.get("valid"):
        return {"prepared": False, "reason": "validation_failed", "apply_enabled": False}
    return {"prepared": True, "configuration": deepcopy(bundle.get("configuration") or {}),
            "apply_enabled": False, "approval_required": True, "approval_via_native_workflow": True}
