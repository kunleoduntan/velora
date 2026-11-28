"""Evidence-driven v5.5 integration qualification gate."""
REQUIRED_EVIDENCE = [
    "native_persistence", "permission_enforcement", "workflow_integration",
    "notification_delivery", "scheduler_execution", "ui_surface_wiring",
    "browser_e2e", "migration_rollback", "backup_restore", "uat_signoff",
]

def evaluate_v5_5_qualification(evidence):
    evidence = dict(evidence or {})
    missing = [name for name in REQUIRED_EVIDENCE if not evidence.get(name)]
    failed = [name for name in REQUIRED_EVIDENCE if evidence.get(name) is False]
    status = "qualified" if not missing and not failed else "not_qualified"
    return {"status": status, "production_qualified": status == "qualified",
            "required_evidence": list(REQUIRED_EVIDENCE), "missing_evidence": missing,
            "failed_evidence": failed, "evidence": evidence}
