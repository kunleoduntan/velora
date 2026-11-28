"""Release gate and qualification report helpers."""
from datetime import datetime, timezone

REQUIRED_GATES = ["automated_tests", "migration_validation", "permission_tests", "workflow_integration",
                  "notification_delivery", "scheduler_execution", "browser_tests", "uat", "backup_restore"]

def build_production_gate_report(results, *, release_version, environment=None):
    results = dict(results or {})
    rows = [{"gate": gate, "status": results.get(gate, "not_run"),
             "passed": results.get(gate) in {True, "passed", "pass", "complete"}}
            for gate in REQUIRED_GATES]
    blockers = [r["gate"] for r in rows if not r["passed"]]
    return {"release_version": release_version, "environment": environment,
            "generated_at": datetime.now(timezone.utc).isoformat(), "gates": rows,
            "blockers": blockers, "status": "qualified" if not blockers else "not_qualified",
            "production_qualified": not blockers}
