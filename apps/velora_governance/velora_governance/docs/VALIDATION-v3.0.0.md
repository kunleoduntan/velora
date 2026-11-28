# Validation — Velora Governance v3.0.0

- Pytest: **55 passed**.
- Python compile check: passed.
- DocType JSON parse check: performed in packaging validation.
- Duplicate DocType names and duplicate fieldnames: checked in packaging validation.
- Source/release archive integrity: checked.
- Wheel archive and import smoke test: checked.

## Not production-qualified
Native Velora runtime adapter installation, persistent idempotency/audit records, permissions, workflow routing, scheduler, notification delivery, portal UI/browser tests, migration safety, deployment and user acceptance must be tested in the target environment.
