# VeloraERP v0.2.0 — Start Here

## Compatibility
- Use Velora Framework v0.82.x.
- VeloraERP is independently versioned and requires Velora >=0.82,<0.83.
- Do not install the legacy `velora_accounts` app alongside `velora_erp` on the same company database. Both define overlapping accounting DocTypes. Keep legacy data intact; a controlled migration bridge will be designed separately.

## Installation and upgrade
1. Add the `velora_erp` application to the framework workspace.
2. Install it into a development company database using the supported Velora application manager/CLI.
3. Run the normal migration/upgrade process.
4. Fresh installs create Finance Settings and seed 26 standard Account Types. Existing v0.1.x company databases receive Account Type seed data through the v0.2 post-model-sync patch.

## Configure Finance
1. Create Account Groups for Asset, Liability, Equity, Income and Expense.
2. Add child Account Groups as needed. Each branch retains its financial class.
3. Select an Account Type and create postable Accounts under compatible Account Groups. Financial class and normal balance are derived.
4. Create Cost Centres.
5. Define Accounting Dimensions and controlled Dimension Values where required.
6. Define Financial Statement Rows and then Account Statement Mappings.

## Important release boundary
Do not create opening balances or process live postings yet. This release does not include the central posting engine, Account Ledger, opening balance migration or executable financial statement engine. Those are planned before live financial processing.
