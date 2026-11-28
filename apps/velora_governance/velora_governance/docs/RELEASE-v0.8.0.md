# Velora Governance v0.8.0 — Automated Disclosure Orchestration & Report Assembly

## Delivered
- Added Sustainability Reporting Run register for reporting-period orchestration auditability.
- Added normalized disclosure data requirement extraction to support automated collection-task orchestration.
- Added orchestration service that assesses applicable disclosures from normalized datapoint, evidence and narrative records.
- Added aggregated reporting-period readiness, ready/gap counts, not-applicable counts, missing-disclosure list and draft report content blocks.
- Generated report status is deterministic: In Progress where gaps remain, Ready for Review when all applicable disclosures are ready.
- Pure service functions do not bypass permissions or persist data; caller must perform permission-aware reads and transactional writes, and use framework approval/workflow engine for review and publication.

## Validation
- Reporting orchestration and requirement extraction tests included.
- Python compilation and package integrity checks required before release.

## Limitations
This batch delivers service-level orchestration and run metadata. Production persistence adapters, task creation, framework-native report document assembly/export, PostgreSQL qualification, UX/UAT, and security review remain outstanding.
