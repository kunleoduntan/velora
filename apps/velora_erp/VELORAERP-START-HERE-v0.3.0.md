# VeloraERP v0.3.0 — Start Here

## Compatibility
- Velora Framework >=0.82,<0.83.
- VeloraERP 0.3.0.
- Do not install legacy `velora_accounts` in the same company database.

## Install / upgrade
1. Install or update the `velora_erp` application in the target company database.
2. Run the normal Velora migration/upgrade process.
3. The v0.3 post-model-sync patch adds composite Account Ledger indexes.
4. Complete Finance Settings, Account Groups, Account Types, Accounts, Financial Year and Financial Period setup.
5. Ensure the posting date belongs to an Open Financial Year and Open Financial Period.

## Posting service contract
Source applications should call `velora_erp.finance.engine.post_financial_transaction(...)` from their submitted document lifecycle. The source document must already be submitted when it is registered as a local Velora DocType. Pass the source DocType/name, posting date, transaction currency, exchange rate and a list of debit/credit lines. Each line supports account, debit, credit, party type/party, cost centre, dimensions and line description.

The service returns a submitted Financial Posting Batch. Do not write Account Ledger Records directly. Use `get_account_balance(...)` and `get_account_activity(...)` for ledger queries.

## Reversals
Use `reverse_financial_posting(batch_name, reversal_date=..., reason=...)`. The reversal must be dated in an open Financial Period. It creates exact opposite ledger rows and references the original ledger rows. Do not cancel or delete a posted batch.

## Currency control
Base currency is taken from Finance Settings. Exchange rate must be positive; when transaction currency equals base currency, rate must be 1. Both transaction currency and base currency totals must balance. v0.3 rejects line-rounding mismatches; it does not yet provide a configured currency rounding account.

## Release boundary
This release provides posting infrastructure only. Sales Invoice, Purchase Invoice, Payment, Receipt, opening balance migration, financial statement execution and subledger reconciliation are still planned.
