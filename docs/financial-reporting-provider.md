# Financial Reporting Provider Contract — Velora 0.83.0

## Purpose

The financial statement designer and drill-down engine must not assume that every accounting application stores its authoritative ledger in a DocType named `GL Entry`. Velora now supports one installed app declaring an authoritative financial reporting provider in its `hooks.py`:

```python
financial_reporting_provider = "package.module"
```

The module must expose four callables:

| Function | Contract |
|---|---|
| `check_access()` | Enforce read permission and field-level visibility for every source used by the provider. Raise the framework's permission exception when access is denied. |
| `get_accounts()` | Return account rows with `name`, `account_number`, `root_type`, `is_group`, and `disabled`. |
| `get_account_totals(account_names, start_date, end_date, *, balance_at_date=False)` | Return rows with `account`, `debit`, and `credit`, in company base currency. For `balance_at_date=True`, include all activity through `end_date`; otherwise include the inclusive date range. |
| `get_ledger_entries(account_names, start_date, end_date, limit, *, balance_at_date=False)` | Return canonical transaction detail: `name`, `posting_date`, `account`, `voucher_type`, `voucher_no`, `party_type`, `party`, `remarks`, `debit`, `credit`, `is_reversal`, and `is_cancelled`. Amounts are in company base currency. |

## Provider selection and safety

- The active company's installed-app registry is the discovery boundary.
- No provider means the existing legacy Account/GL Entry path remains available.
- More than one provider is a configuration error. The framework refuses to guess which ledger is authoritative.
- Provider functions run inside the active company database context; cross-company access is not implied.
- Providers must implement their own permission checks. The framework validates the provider contract before execution.
- The provider is trusted application code, not company-stored executable content.
- The framework's report layout and drill-down UI remain unchanged; only the data adapter changes.

## VeloraERP implementation

VeloraERP declares `velora_erp.finance.reporting_provider`. It maps Account and Account Group to the canonical account shape and reads `Account Ledger Record` base-currency debit/credit values. Reversal entries are included as ordinary signed ledger activity; they net against their original postings without editing or deleting historical records.

The framework keeps the existing legacy path for installations still using `velora_accounts`. VeloraERP does not require or query the legacy `GL Entry` table.
