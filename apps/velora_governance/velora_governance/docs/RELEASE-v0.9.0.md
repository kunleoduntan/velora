# Velora Governance v0.9.0 — Automated Data Collection & Report Assembly Foundation

## Delivered
- Idempotent collection-task specification generator for applicable disclosures, including separate data, evidence and narrative tasks.
- Task keys include reporting period, disclosure and task type; persistence adapters can enforce uniqueness to avoid duplicate tasks on reruns.
- Not-applicable disclosures are excluded from task generation.
- Normalized matching helper maps data points and evidence to disclosure requirements, preserving record names and statuses.
- Persistence-ready report package builder combines disclosure assessments, source matches, readiness summaries, missing disclosures and generated report content blocks.
- Generated readiness is based on complete/verified/approved data, submitted/verified/approved evidence, and non-empty narrative according to configured requirements.
- Services remain side-effect-free; application adapters must apply permission-aware reads, transactional writes, uniqueness constraints, and framework workflow/approval engine controls.

## Validation
- Focused sustainability reporting tests: 6 passed.
- Python compilation passed.
- Metadata JSON parse and uniqueness validation performed during release packaging.
- Full framework installation/integration tests could not be run because the Velora framework package is not installed in this environment.

## Limitations
- Actual task persistence, document creation, framework-native lifecycle calls, workflow approval configuration, database migrations, UI/UAT, PostgreSQL qualification and security review remain to be validated in a framework-enabled environment.
- This release provides tested orchestration primitives and report-package assembly, not a production-ready persistence adapter or final report export renderer.
