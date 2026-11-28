"""Platform integration readiness and release qualification diagnostics."""
REQUIRED_INTEGRATIONS = ["permissions", "workflow", "notification", "scheduler", "persistence", "portal_ui"]


def build_platform_readiness(*, integrations=None, migration_checks=None, test_results=None, release_version="3.0.0"):
    integrations = integrations or {}
    migration_checks = migration_checks or []
    test_results = test_results or {}
    checks = []
    for name in REQUIRED_INTEGRATIONS:
        status = integrations.get(name, "not_configured")
        ok = status in {True, "ready", "configured", "passed"}
        checks.append({"check": name, "status": "ready" if ok else str(status), "passed": ok})
    for check in migration_checks:
        item = dict(check)
        item.setdefault("check", "migration_check")
        item["passed"] = bool(item.get("passed"))
        checks.append(item)
    passed_tests = int(test_results.get("passed", 0) or 0)
    failed_tests = int(test_results.get("failed", 0) or 0)
    tests_ok = failed_tests == 0 and passed_tests > 0
    checks.append({"check": "test_suite", "status": "passed" if tests_ok else "not_qualified", "passed": tests_ok,
                  "passed_count": passed_tests, "failed_count": failed_tests})
    failures = [c for c in checks if not c.get("passed")]
    return {"release_version": release_version, "checks": checks, "total_checks": len(checks),
            "passed_checks": len(checks)-len(failures), "failed_checks": len(failures),
            "readiness": "ready_for_qualification_review" if not failures else "not_ready",
            "production_qualified": False,
            "qualification_boundary": "This diagnostic is advisory. Production qualification requires deployment-specific verification, UAT, permissions, workflow, scheduler, delivery, persistence, and UI tests.",
            "blocking_items": failures}
