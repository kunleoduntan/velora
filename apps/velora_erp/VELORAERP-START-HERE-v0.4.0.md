# VeloraERP v0.4.0 — Start Here

## Compatibility
- Velora Framework >=0.83,<0.84.
- VeloraERP 0.4.0.
- Do not install legacy `velora_accounts` in the same company database.

## Install / upgrade
1. Install or update `velora_erp` in the target company database.
2. Run the normal Velora migration/upgrade process.
3. The v0.4 post-model-sync patch seeds the company Finance workspace and shared Income Statement / Statement of Financial Position layouts.
4. Complete Finance Settings, Account Groups, Account Types, Accounts, Financial Year and Financial Period setup.
5. Review the Finance workspace and set it as the company default if another workspace is already selected.

## Finance workspace and GUI
The Finance workspace is integrated into the native Velora Desk. It links to Account Structure, Financial Voucher, Opening Balance Entry, Trial Balance, Account Ledger, Financial Statements, Finance Settings and Financial Periods. It includes permission-aware counts and the native activity feed. A personal default workspace takes precedence over the company Finance workspace.

Financial Voucher and Opening Balance Entry use standard Velora forms and child-table grids. The forms include contextual links to reports and their resulting Financial Posting Batch. The reports are listed in the Finance/Reports navigation and can also be opened from the workspace.

## Financial reporting
- **Trial Balance** reports opening balances, period debit/credit movements and closing balances by Account Group hierarchy.
- **Account Ledger** requires an Account or Party filter and shows opening balance, source document, transaction currency, exchange rate, base-currency debit/credit and running balance.
- **Income Statement** and **Statement of Financial Position** are seeded in the framework Financial Report Designer. Both execute against the VeloraERP Account Ledger through the framework's financial reporting provider.

## Controlled source documents
- Financial Voucher requires independent approval when Finance Settings has `require_approval_for_manual_vouchers` enabled. The creator cannot approve their own voucher.
- Opening Balance Entry always requires independent approval and is restricted to Asset, Liability and Equity accounts. It uses company base currency and exchange rate 1.
- Submission calls `post_financial_transaction(...)`; users must not create Account Ledger Records directly.
- Submitted vouchers and opening balance entries cannot be cancelled or deleted. Use controlled reversal processing for corrections.

## Provider contract
VeloraERP declares `financial_reporting_provider = "velora_erp.finance.reporting_provider"` in hooks.py. The framework validates and calls `check_access`, `get_accounts`, `get_account_totals` and `get_ledger_entries`. The provider is company-database scoped and returns base-currency amounts. See the framework documentation `docs/financial-reporting-provider.md`.

## Validation boundary
The v0.4.0 release has automated SQLite application tests and focused framework financial-report/workspace regression tests. PostgreSQL and Oracle integration, real browser workflows, high-volume concurrency, penetration testing and production backup/restore rehearsals are not claimed by this release.
