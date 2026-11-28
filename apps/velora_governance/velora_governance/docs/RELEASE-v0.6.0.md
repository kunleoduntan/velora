# Velora Governance v0.6.0 — Sustainability & ESG Foundation

## Added
- Sustainability Settings (company singleton implemented through the framework's native DocType and series; one-record validation)
- Reporting framework registry: IFRS S1, IFRS S2, GRI, SASB, ESRS, GHG Protocol, UN SDGs and FRC SRG 1
- Standards and disclosure mapping registry
- Starter disclosure mapping for IFRS S1/S2, FRC SRG 1, GRI, ESRS, GHG Protocol scopes and all 17 UN SDGs
- Disclosure Applicability
- Impact, Financial and Double Materiality Assessment
- Materiality Topics and scoring
- Stakeholder profiles and engagement
- Sustainability Metrics and framework mappings
- Numeric, percentage, currency, boolean and text sustainability data points
- Sustainability Targets with progress calculation and history
- Sustainability Initiatives
- Sustainability Risks and Opportunities
- Emission Sources, configurable Emission Factors and GHG Calculations
- Scope 1, Scope 2 and Scope 3 source classifications
- Sustainability Reports, framework sections and readiness calculation
- Sustainability Assurance records
- Sustainability Data Collection Tasks, calendar integration and overdue automation
- Sustainability workspace and dashboard KPIs

## Automation
- Sustainability Data Points update linked numeric targets.
- Matching data points complete open data-collection tasks.
- Report readiness is calculated from completed and not-applicable sections.
- GHG calculations use configured factors and unit validation; factors are not hardcoded.
- Daily automation marks overdue sustainability data tasks.

## Validation
- 32 automated tests passed
- 113 DocTypes registered and cross-validated
- SQLite integrated installation and lifecycle passed
- Integrated sustainability workflow: framework/disclosure → materiality → stakeholder engagement → metric/data point → target → initiative → risk/opportunity → emission source/factor → GHG calculation → report → assurance
- Data collection task completion and overdue automation passed
- Package inspection, compilation, wheel and source ZIP integrity passed

## Important limitations
- Framework/standard/disclosure starter mappings are configurable and require current legal, jurisdictional and entity-applicability validation before regulatory reporting.
- Emission factors are configured by the customer; no factors are presented as authoritative defaults.
- Sustainability report content assembly and publishing file generation are tracked, but a complete automated report-generation engine is future work.
- Recurring data-collection task generation, scenario analysis, assurance workflow integration and production dashboard UAT remain future work.
- PostgreSQL production qualification, cross-entity row-scope security, browser UAT and external security review are not complete.

**Status: Source/package and SQLite integration validation passed; not production-qualified or final sign-off.**
