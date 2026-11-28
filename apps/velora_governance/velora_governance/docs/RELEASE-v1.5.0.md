# Velora Governance v1.5.0

## Report Review Operations & Final Report Assembly

This release adds report review operations, review issue tracking metadata, report revision snapshots, section-completeness and finalisation readiness helpers, and escaped print-friendly HTML report assembly.

### Delivered
- Review queue filtering and counts by status, reviewer, and report.
- Validated review assignment payload helper and permission-checked API for creating review records.
- Sustainability Report Review Issue DocType, issue creation and resolution APIs.
- Sustainability Report Revision DocType with JSON snapshot, author, revision number, change summary and status.
- Report revision API captures report and section snapshot and advances the current revision marker.
- Print-friendly HTML report assembly API; source content is HTML-escaped.
- Completeness and finalisation readiness checks. These are readiness guards only and do not replace or hardcode Velora Workflow Engine routing or approval decisions.
- Sustainability workspace shortcuts for Review Queue, Review Issues and Report Revisions.

### Not delivered / qualification limitations
- No PDF or DOCX exporter is included; the report assembly endpoint returns print-friendly HTML.
- Live Velora runtime, browser UAT, persistence, workflow-engine execution, PostgreSQL, permissions matrix and security qualification have not been tested in this environment.
- The available source baseline is the v1.3.0 source archive. The previously described v1.4.0 lifecycle implementation was not available as a source artifact in the workspace; this release reintroduces the relevant revision and review operations on the verified v1.3.0 source baseline. Do not treat v1.4.0 as merged unless its original source is independently reconciled.
- The wheel is assembled as a ZIP-format build artifact; native installation qualification remains pending.
