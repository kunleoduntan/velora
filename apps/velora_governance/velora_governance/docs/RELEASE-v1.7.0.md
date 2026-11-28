# Velora Governance v1.7.0 — Native Document Export & Publication Operations

## Scope delivered
- Native PDF export with ReportLab: A4/Letter, portrait/landscape, configurable margins, cover page, headers, footers, page numbers, paragraphs, headings, lists and tables.
- Native DOCX export with python-docx: cover page, headings, paragraphs, bullet lists, tables, configurable margins, header/footer and page-number field.
- Export template DocType for board, management, regulatory, public and custom report layouts.
- Permission-aware export endpoint attaches private files to the report and can update a selected publication register file reference.
- HTML preview endpoint returns report preview and normalized export settings.
- Revision comparison summary API; it reports token/word counts and whether content changed. It is not a legal redline or tracked-change comparison.
- Distribution acknowledgment API.
- Sustainability workspace shortcut for export templates.
- Optional dependencies handled at runtime with clear missing-library errors.

## APIs
- `preview_sustainability_report_export`
- `export_sustainability_report_document`
- `compare_sustainability_report_revision`
- `acknowledge_sustainability_report_distribution`

## Security/operational notes
- Report read permission is checked before export/preview.
- Export templates are read-permission checked and must be active.
- Generated files are private attachments.
- Publication register linking is write-permission checked and validates that the selected publication belongs to the report.
- Workflow approval remains in the configured framework engine; export does not approve or publish reports.
- PDF/DOCX exports do not independently validate source-data correctness. Finalized/approved publication controls remain in force.
