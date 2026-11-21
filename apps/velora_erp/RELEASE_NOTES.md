# VeloraERP v0.4.0 — Integrated Finance Reporting and Opening Controls

## Framework compatibility
- Requires Velora Framework >=0.84,<0.85.
- Framework 0.83 adds the financial reporting provider contract and governed report shortcuts in workspaces.

## Added
- Financial Voucher and Financial Voucher Line with independent approval controls, self-approval prevention and central-engine posting.
- Opening Balance Entry with independent approval, balance-sheet-only account validation, base-currency-only processing and migration-reference idempotency.
- Trial Balance report with opening, movement and closing values and Account Group hierarchy.
- Account Ledger report with source-document traceability, transaction/base currency values, exchange rates and running balance.
- Seeded Income Statement and Statement of Financial Position layouts in the native Financial Report Designer.
- VeloraERP financial reporting provider so the framework's financial statement calculations and drill-down read Account Ledger Record rather than legacy GL Entry.
- Company Finance workspace with navigation shortcuts, KPIs and activity feed.
- Upgrade patch to seed the Finance workspace and financial statement layouts for existing installations.

## GUI integration
- Finance DocTypes use the native Velora Desk navigation and metadata-driven forms.
- Reports use the native Reports menu and financial statement screens.
- Voucher and opening balance forms include contextual navigation to ledger and financial reporting.
- No separate frontend, duplicate permission system or client-side accounting posting path is introduced.

## Controls
- Manual Financial Voucher approval follows Finance Settings; maker-checker self-approval is blocked.
- Opening Balance Entry always requires independent approval and only accepts Asset, Liability and Equity accounts.
- Both source documents post through the central Financial Posting Engine and cannot be cancelled after submission.

## Not included
Sales Invoice, Purchase Invoice, Sales Order, Purchase Order, Payment, Receipt, tax processing, bank reconciliation, subledger reconciliation and full period closing remain future releases.
