"""Release qualification checklist evaluator; evidence is supplied by deployment testing."""
REQUIRED_GATES = ["runtime_integration", "permission_tests", "workflow_tests", "notification_tests",
                  "scheduler_tests", "browser_tests", "migration_tests", "backup_restore", "uat"]


def evaluate_governance_release_qualification(evidence=None, *, release_version="4.5.0"):
    evidence = evidence or {}
    gates = []
    for gate in REQUIRED_GATES:
        value = evidence.get(gate)
        passed = value is True or (isinstance(value, dict) and value.get("passed") is True and bool(value.get("evidence_ref")))
        gates.append({"gate": gate, "passed": passed, "evidence_ref": value.get("evidence_ref") if isinstance(value, dict) else None,
                     "status": "passed" if passed else "not_evidenced"})
    blocking = [gate for gate in gates if not gate["passed"]]
    return {"release_version": release_version, "gates": gates, "passed": len(gates)-len(blocking),
            "total": len(gates), "blocking_count": len(blocking), "blocking_gates": [g["gate"] for g in blocking],
            "qualification_status": "qualified_for_release_review" if not blocking else "not_qualified",
            "production_qualified": False,
            "statement": "This evaluator cannot certify production deployment; evidence must be verified and sign-off recorded by authorized reviewers."}
