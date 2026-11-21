# VeloraERP 0.23.0 — Enterprise Settings and Configuration Completion

## Delivered
- Registered 19 company-scoped, typed settings contracts for finance, localisation, inventory and sales policies: 13 are operationally bound; 6 structural accounting-identity settings remain catalogue-only until a dedicated migration workflow exists.
- Added a controlled settings binding layer: only published legal-entity settings override existing Finance Settings and Inventory Settings values. Existing settings DocTypes remain intact and continue to provide the operational baseline.
- Connected governed overrides to the financial posting engine and inventory selling-price/cost-protection service.
- Added company setup readiness assessment covering Finance Settings, Inventory Settings, chart of accounts, financial year, financial periods, customers, suppliers and warehouses.
- Added native React Desk Company Setup Readiness page and Sales workspace shortcut.
- Added an application provider hook for company setup readiness, served through the framework API.
- Added an idempotent upgrade hook to seed missing settings contracts without changing existing values.

## Safety and migration
- No automatic conversion of existing settings records into published governance versions. This avoids changing live accounting behaviour during upgrade.
- Published overrides are entity-database scoped; no branch or cross-company inheritance is introduced.
- Only settings explicitly bound to operational services affect transaction behaviour.

## Known limitations
- Sales, Purchasing, Tax, Banking, Fixed Asset and Budget configuration domains are not yet complete end-to-end; this release establishes the settings binding and setup-readiness foundation for those domains.
- Setup readiness is a configuration checklist, not a certification of statutory compliance, opening balances or production security.
- Full frontend build/test could not be executed in this environment because npm dependency installation timed out.
