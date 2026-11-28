"""Production qualification checklist/report; advisory, not a production certification."""
QUALIFICATION_AREAS = ["installation", "migration", "permissions", "workflow", "automation_persistence",
                       "notification_delivery", "scheduler", "portal_ui", "browser_tests", "uat", "backup_restore"]

def build_qualification_report(*, release_version="3.5.0", evidence=None, notes=None):
    evidence = evidence or {}
    checks = []
    for area in QUALIFICATION_AREAS:
        item = evidence.get(area, {})
        status = item.get("status", "not_tested") if isinstance(item, dict) else str(item)
        passed = status in {"passed", "verified", "complete"}
        checks.append({"area": area, "status": status, "passed": passed,
                      "evidence": item.get("evidence", "") if isinstance(item, dict) else ""})
    blockers = [c for c in checks if not c["passed"]]
    return {"release_version": release_version, "checks": checks,
            "passed": len(checks)-len(blockers), "total": len(checks), "blockers": blockers,
            "qualification_status": "ready_for_signoff" if not blockers else "not_qualified",
            "production_qualified": False,
            "notes": notes or "Final production qualification requires deployment-specific evidence and authorized sign-off."}
