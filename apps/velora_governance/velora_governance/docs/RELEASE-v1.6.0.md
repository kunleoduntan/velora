# Velora Governance v1.6.0

## Board-Ready Sustainability Report Publishing & Export Foundation

### Delivered
- Board report HTML assembler with cover page, executive summary, summary metric cards, highlights, risks and management priorities.
- Table of contents and ordered report sections with anchors and page-friendly styling.
- Optional structured appendices for targets, GHG emissions, materiality topics, framework disclosures and evidence references.
- Escaped report metadata, section text, table cells and executive-summary text to reduce markup injection risk.
- Permission-aware API assembles report content from report sections, targets, GHG calculations, materiality assessments, disclosure assessments and evidence using framework list operations.
- Sustainability Report Publication register records report, entity, period, revision, publication date, channel, audience, URL/file reference, SHA-256 content digest, status, publisher and notes.
- Sustainability Report Distribution child table tracks recipient, recipient type, delivery method/date, delivery status and acknowledgment.
- Publication validation requires a finalized/published report, complete applicable sections, no open review issues, a completed review record and publication channel.
- API to create a publication-preparation register, mark a prepared publication as published after report finalization, and append distribution history.
- Workspace shortcut for Report Publications.
- Framework workflow and approval routing are not hardcoded; configured workflow remains authoritative.

### Tests and validation
- Six focused report publishing tests cover board report structure/appendices, safe escaping, executive-summary data behavior, publication blockers, eligible publication and SHA-256 stability.
- Existing v1.5.0 tests retained.
- Full app test suite: 32 passed.
- Python compilation, metadata JSON validation, duplicate names/fields and archive integrity validated.

### Qualification limitations
- This release assembles HTML suitable for browser print-to-PDF and downstream document conversion; a native PDF/DOCX exporter is not included.
- The runtime API is implemented but not live-qualified against a running Velora installation in this environment.
- Workflow-engine transitions, persistence behavior, permissions matrix, PostgreSQL, browser rendering, accessibility and UAT remain pending.
- The wheel is manually assembled because standard build dependencies/build configuration are not available in this environment. It is a test artifact pending native install qualification.
