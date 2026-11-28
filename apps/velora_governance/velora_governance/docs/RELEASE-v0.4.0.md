# Velora Governance v0.4.0 — Corporate Secretariat & Compliance

## Cumulative product releases

### v0.1.0 — Governance Foundation
- Governance Settings and entities
- Boards, Board Members, appointments and director profile child tables
- Configurable governance type masters
- Skills catalogue and calculated Board Skills Matrix
- Governance Calendar foundation

### v0.2.0 — Board & Committee Management
- Board Committees, committee membership and charters
- Board/committee meeting scheduling, agenda, attendance and quorum
- Meeting calendar event synchronization
- Board Papers and Board Packs

### v0.3.0 — Minutes, Resolutions & Actions
- Meeting Minutes and version control
- Meeting decisions
- Configurable Resolution Types and voting thresholds
- Voting records, vote calculations and eligibility validation
- Resolution lifecycle
- Board Action register and progress updates
- Minutes decisions automatically create Board Actions
- Daily overdue action automation

### v0.4.0 — Corporate Secretariat & Compliance
- Regulatory Authorities and Requirements
- Governance Obligations and Compliance Assessments
- Compliance evidence and automated remediation Board Actions
- Filing Requirements, Corporate Filings and submission history
- Regulatory Correspondence and response deadlines
- Statutory Registers and controlled entries
- Shareholders, Shareholder Registers and Shareholding Entries
- Corporate Events with event-triggered filing creation
- Annual Returns
- Automatic Governance Calendar integration for obligations, filings, corporate events, registers, annual returns and correspondence
- Daily overdue maintenance automation
- Secretariat & Compliance workspace

## Automation
- Compliance Assessments marked Completed and Non-Compliant automatically create a remediation Board Action and update the Obligation.
- Corporate Events with a Filing Requirement automatically create a Corporate Filing based on the configured lead days.
- Calendar events are automatically created and synchronized for supported governance and secretariat records.
- Daily maintenance marks overdue actions, obligations, filings, annual returns and correspondence; statutory registers due for review are moved to Under Review.

## Validation
- 23 automated tests passed
- 62 DocTypes registered and cross-validated
- SQLite integrated installation and lifecycle test passed
- Integrated governance lifecycle: Entity → Board → Member → Appointment → Skills Matrix → Committee → Charter → Meeting → Paper → Pack → Resolution → Minutes → Action
- Integrated secretariat lifecycle: Regulatory Requirement → Obligation → Compliance Assessment → Remediation Action; Corporate Event → Filing; Statutory Register; Shareholder Register; Annual Return; Regulatory Correspondence
- App package inspection, compilation, wheel and source integrity passed
- 45 unique default native `series:` naming prefixes validated

## Not qualified
- Live PostgreSQL deployment/migration and production performance
- Full cross-entity row-scope security and Board Portal
- Browser/Desk UAT, responsive UX and accessibility qualification
- Document assembly and e-signature integrations
- External security review and backup/restore rehearsal
- Regulatory rule validation against current legal advice and authority guidance

**Status: Cumulative source and package validation passed; not PostgreSQL production-qualified or final sign-off.**
