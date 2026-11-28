# Velora Governance v1.7.0

Enterprise Governance, Board Management, Corporate Secretariat, Compliance, Risk and Sustainability Reporting application built on Velora Framework.

## Framework baseline
Compatible with Velora Framework `>=1.19.0,<1.20.0`. Uses framework-native DocTypes, Naming Series, permissions, audit history, workflow, notification, scheduler, lifecycle and workspace services.

## Naming Series
Numbered records use framework-native `series:` autoname defaults. Company-configured Naming Series Rules can override each DocType through framework `naming.rules`. No app-local counters or numbering service exist.

## v1.6.0 additions
- Board-ready sustainability report assembly with cover page, executive summary, configurable summary inputs, table of contents, numbered sections, targets, GHG emissions, materiality, disclosure and evidence appendices.
- Publication register with channel, audience, date, version, file/URL reference, SHA-256 content digest and publication status.
- Distribution history child table with delivery method, status, date and acknowledgment tracking.
- Permission-aware report assembly, publication preparation, release status and distribution APIs.
- Publication eligibility checks require finalization, complete applicable sections, no open review issues, a completed review record and publication channel.

## Cumulative scope
- Governance Foundation
- Board & Committee Management
- Meetings, Agenda, Attendance, Quorum, Papers and Packs
- Minutes, Decisions, Resolutions, Voting and Board Actions
- Corporate Secretariat, Statutory Registers, Shareholder Records and Annual Returns
- Regulatory Compliance, Obligations, Assessments, Evidence, Remediation and Filings
- Governance Policies, Conflict of Interest, Related Parties, Governance Risks and Controls
- Board Evaluation, Director Training and Succession Planning
- Sustainability/ESG: IFRS S1/S2, GRI, SASB, ESRS, GHG Protocol, UN SDGs and FRC SRG 1 starter mappings
- Materiality, stakeholders, metrics, data points, targets, initiatives, sustainability risks/opportunities, GHG calculations, reports and assurance
- Automatic calendar integration and daily due-date/review automation

## Security and approvals
Sensitive director, shareholder, conflict and related-party fields are permission level 1. Board-member portal access is not granted until board/entity row-scope security is implemented and tested. Approval workflows use the shared Velora Workflow Designer; no separate approval engine is included.

## v1.7.0 additions
- Native PDF and DOCX sustainability report export.
- Configurable export templates for board, management, regulatory and public reporting.
- Export preview, private report file attachments, publication register linking and distribution acknowledgments.
- Revision comparison summary (not a full tracked-change redline).
