"""v5.0 release-candidate gate; requires concrete evidence, never self-certifies."""
REQUIRED_RC_GATES = (
    "native_runtime_integration", "permission_enforcement", "workflow_integration", "notification_delivery",
    "scheduler_execution", "dashboard_ui", "automation_history_ui", "board_committee_portal_ui",
    "configuration_center_ui", "migration_validation", "backup_restore", "browser_e2e", "uat_signoff",
)


def evaluate_v5_release_candidate(evidence=None, *, release_version="5.0.0"):
    evidence = evidence or {}
    gates = {}
    for gate in REQUIRED_RC_GATES:
        item = evidence.get(gate) or {}
        passed = bool(item.get("passed")) and bool(item.get("evidence_ref"))
        gates[gate] = {"passed": passed, "evidence_ref": item.get("evidence_ref") if passed else None,
                      "status": "passed" if passed else "blocked"}
    blockers = [gate for gate, result in gates.items() if not result["passed"]]
    return {"release_version": release_version, "status": "qualified" if not blockers else "not_qualified",
            "qualified": not blockers, "gates": gates, "blocker_count": len(blockers), "blockers": blockers,
            "production_deployment_authorized": False, "note": "Qualification requires independent authorized deployment approval."}
