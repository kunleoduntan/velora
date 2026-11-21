# VeloraERP

VeloraERP is the integrated accounting and business core application for the Velora framework. It is released independently from the framework.

## Current release
- VeloraERP: **0.22.0**
- Required Velora Framework: **>=0.85.0,<0.86**
- Current scope: integrated finance and commercial documents, Sales/Purchase invoicing and returns, receipts/payments, GRNI matching, immutable stock and financial ledgers, warehouse transfers, serial/batch traceability, Landed Cost Voucher capitalisation, FIFO, Moving Average and periodic Weighted Average valuation, Opening Stock Entry, Stock Revaluation and Inventory Item cost-based selling-price protection.

## Finance and native GUI integration
VeloraERP uses the native Velora React Desk. Finance DocTypes appear in the Finance module navigation; Trial Balance, Account Ledger, Customer Ledger, Supplier Ledger, Employee Ledger, Customer Statement and Supplier Statement appear in Reports; Income Statement and Statement of Financial Position are available in the framework Financial Report Designer. The company Finance workspace is seeded during installation and upgrade with operational shortcuts, KPIs and activity.

Financial Voucher and Opening Balance Entry use the standard Velora document lifecycle, metadata forms, child-table grid, permissions, audit trail and contextual navigation actions. There is no parallel front end or bypass around framework security.

## Financial Posting Engine
- `post_financial_transaction(...)` is the supported service entry point for source applications.
- Every posting is captured in a Financial Posting Batch with child Financial Posting Lines.
- The service enforces source-event idempotency, account eligibility, period status, currency conversion, party tracking, dimensions, and debit/credit equality in transaction and base currency.
- The only supported writer of Account Ledger Records is the posting engine. Ledger rows are append-only; corrections use `reverse_financial_posting(...)`.
- Posting batch and ledger writes occur in the same Velora database transaction. A failure rolls back both.
- `get_account_balance(...)` and `get_account_activity(...)` provide ledger-based query services.

## Customer, Supplier and Employee ledgers (v0.6.0)
- Customer and Supplier masters include group classification, default control account, currency and payment terms. Customer records also include credit limit, credit hold and optional Customer Advance Liability account controls; Supplier records include optional Supplier Advance Asset account controls.
- Customer default control accounts must be active Receivables Asset control accounts; Supplier defaults must be active Payables Liability control accounts.
- The posting engine validates that party references exist, are active and match the financial class of the party-tracked account.
- Customer Statement and Supplier Statement are ledger-backed reports. `get_party_balances()` and `reconcile_party_control_account()` provide party subledger views and control-account reconciliation checks.
- Customer and Supplier records with ledger activity cannot be deleted; they can be disabled.

## Financial reporting integration
VeloraERP declares `velora_erp.finance.reporting_provider` in its app hooks. The provider supplies canonical account rows, base-currency account totals and transaction-level ledger details to the framework's Financial Report Designer and drill-down engine. The framework continues to support the legacy Accounts reporting path for existing installations; VeloraERP does not use legacy `GL Entry` tables.

Included reports and layouts:
- Trial Balance — opening, period movement and closing balances, with account-group hierarchy.
- Account Ledger — source-document and source-line drill-through, transaction and base currency values, exchange rates, account classification snapshots, party, dimensions, tax, settlement, inventory, asset and organisational context, and running balances.
- Income Statement — seeded editable financial report layout.
- Statement of Financial Position — seeded editable financial report layout with a balance check.

## Controlled source documents
- Financial Voucher: controlled manual adjustment. If Finance Settings requires approval, an independent Finance Manager or System Manager must approve before submission. Self-approval is blocked. Submission posts through the central engine.
- Opening Balance Entry: always requires independent approval, accepts only Asset, Liability and Equity accounts, uses company base currency and rate 1, and posts once using a unique migration reference.
- Submitted source documents cannot be cancelled or deleted. Corrections use the controlled reversal process.

## Installation and upgrade
Install or update `velora_erp` in the target company database using the Velora application manager or supported app installation command, then run the normal Velora upgrade process. The v0.4 post-model-sync patch seeds the Finance workspace and starter financial statement layouts. The v0.5 post-model-sync patch extends existing Finance workspaces with Customer, Supplier, Payment Terms and statement shortcuts. The v0.6 post-model-sync patch refreshes the workspace with Customer Ledger, Supplier Ledger and Employee Ledger shortcuts. The v0.8 post-model-sync patch adds Sales Invoice and Purchase Invoice shortcuts.

## Compatibility and migration
- Velora Framework: >=0.85.0,<0.86.
- Existing `velora_accounts` remains unchanged. Do not install it alongside `velora_erp` in the same company database because the applications define overlapping DocTypes, including `Account`. A controlled migration bridge is required before replacing legacy data.

## Universal cash management (v0.7.0)
Receipt and Payment are distinct submittable cash documents with multiple debit/credit lines, independent approval, bank/cash account validation, party-aware posting, net cash versus gross accounting totals, and central-engine posting. Receipt supports customer receipts, other income, supplier refunds, advances, deferred income and other inflows. Payment supports supplier payments, expenses, customer refunds, employee reimbursements/advances, asset acquisitions, prepayments, loan repayments and other outflows. Opposite-side lines support withholding deductions and bank charges. See `velora_erp/docs/CASH-MANAGEMENT-v0.7.0.md`.

Recognition Schedule and Schedule Recognition support monthly prepayment amortisation and deferred-income recognition. A daily scheduler posts due periods through the Financial Posting Engine.

## Release boundary
VeloraERP is an evolving integrated accounting and business core, not yet a completed ERP suite. Sales Quotation, Purchase Requisition, full invoice settlement allocation and ageing, bank reconciliation, stock reservation, in-transit transfers, historical valuation replay, fixed assets, payroll and full credit-limit enforcement still require their own complete workflows and tests. Sales/Purchase Invoice recognition, customer/supplier statements, stock ledgers, Moving Average, FIFO, periodic Weighted Average, opening stock, stock revaluation, warehouse transfers, returns, GRNI matching and Landed Cost Voucher capitalisation are implemented. Tax amounts are captured but statutory tax calculation and returns remain separate work. The v0.15 React Desk source changes require a frontend production rebuild before live row repricing is available; server-side price calculation and cost-floor validation are active. PostgreSQL/Oracle, browser end-to-end, production concurrency and external security validation remain outstanding.


## Source posting adapters (v0.4.1)

Source modules implement `SourcePostingAdapter.build_posting(source)` and call `post_source_document(source, adapter)` from the source submit hook. See `velora_erp/docs/SOURCE-ADAPTER-CONTRACT-v0.4.1.md`. Adapters provide stable idempotency keys and posting instructions; only the Financial Posting Engine writes Account Ledger Records.

## v0.6.0 scope

See `RELEASE_NOTES-VELORAERP-v0.6.0.md`, `velora_erp/docs/PARTY-LEDGERS-v0.6.0.md` and `velora_erp/docs/SOURCE-ADAPTER-CONTRACT-v0.6.0.md` for detailed ledger metadata, party-ledger design and the extended source adapter contract. The v0.6 post-model-sync patch refreshes existing Finance workspaces.


## Customer, Supplier and Employee Ledgers (v0.6.0)

The Account Ledger Record remains the single immutable financial source of truth. Customer Ledger, Supplier Ledger and Employee Ledger are party-specific report views over those same records; they do not create parallel subledger balances. Employee party tracking supports employee receivables and payables, including advances, loans, reimbursements and payroll-related liabilities. Ledger detail now retains source-line, transaction/due/value dates, external and settlement references, tax context, item/warehouse/asset/project references and organisational tags where supplied by the posting adapter.

### v0.6.0 ledger model

The Finance workspace provides General Ledger (Account Ledger), Customer Ledger, Supplier Ledger and Employee Ledger access. Customer Statement and Supplier Statement remain separate presentation reports. Employee finance identity is deliberately distinct from the full HR employee profile and can later be linked to it. All party ledgers are filtered views of Account Ledger Records, never independent ledgers.


## v0.7.0 cash management
See `RELEASE_NOTES-VELORAERP-v0.7.0.md` and `velora_erp/docs/CASH-MANAGEMENT-v0.7.0.md`. Invoice references and allocation amounts are captured but automatic invoice allocation is deferred until Sales Invoice and Purchase Invoice are implemented.


## v0.8.0 Sales and Purchasing Invoicing

Sales Invoice and Purchase Invoice are independent, approval-controlled source documents. Sales invoices debit the selected Customer Receivables Control Account and credit revenue and any explicitly entered output tax. Purchase invoices debit the selected expense account and any explicitly entered input tax, and credit the Supplier Payables Control Account. Both use the source adapter contract and central posting engine. See `velora_erp/docs/SALES-PURCHASING-INVOICING-v0.8.0.md` for exact scope and limitations.

## v0.8.1 — Document Flow

The controlled `create_document_from` service currently supports Sales Invoice → Receipt and Purchase Invoice → Payment. It creates draft documents, retains source references, supports partial settlement amounts, and requires a bank/cash account. Other sales, purchasing, credit/debit, delivery and waybill flows are planned but are not yet included. See `velora_erp/docs/DOCUMENT-FLOW-v0.8.1.md`.

## v0.11.0 — Returns and Landed Cost

Use **Sales Return** and **Purchase Return** as the single operational return documents; separate credit-note and debit-note DocTypes are intentionally not introduced. Invoice-linked returns reverse the corresponding revenue/expense, tax and customer/supplier control-account values through the central Financial Posting Engine. Landed Cost Voucher captures eligible acquisition charges and calculates allocations by value, quantity, weight, volume or equal share. That was the v0.11.0 boundary; v0.12.0 enables approved Landed Cost Voucher capitalization through the Inventory Ledger. See `velora_erp/docs/INVENTORY-LEDGER-AND-STOCK-RECONCILIATION-v0.12.0.md`.


## v0.12.0 — Inventory Ledger and Stock Reconciliation

The inventory foundation adds Inventory Item, Warehouse, Batch, Serial Number, Stock Ledger Record, Stock Reconciliation and Inventory Settings. Stock Reconciliation presents current stock balance, physical count, adjustment quantity, current cost, proposed price, current stock value and value adjustment. Positive quantity variances use the proposed price; shortages use current moving-average cost; an unchanged count does not revalue existing stock. Submission requires independent approval and appends immutable Stock Ledger Records plus central-engine financial adjustments.

Purchase Receipt, Delivery Note, Sales Return and Purchase Return now create inventory quantity and valuation movements for configured stock items. Landed Cost Voucher is submittable after independent approval and capitalises allocated acquisition costs into the on-hand inventory portion, while the portion attributable to consumed goods adjusts Cost of Goods Sold. Serial and batch tracking are supported. Inventory Settings must be configured before stock movements post. Moving Average is the only valuation method in this release; FIFO, stock transfer, opening stock entry, stock revaluation and Purchase Invoice-to-GRNI matching remain future work. See `velora_erp/docs/INVENTORY-LEDGER-AND-STOCK-RECONCILIATION-v0.12.0.md`.


## Inventory and warehouse operations (v0.13.0)

Purchase Receipt to Purchase Invoice conversion now supports partial GRNI matching by receipt line. Invoice submission clears the original GRNI at the receipt valuation and recognises differences in the configured Purchase Price Variance account. Draft and submitted invoices reserve received quantities; source receipt locking and final quantity revalidation protect the submit transaction. See `velora_erp/docs/GRNI-MATCHING-AND-STOCK-TRANSFER-v0.13.0.md`.

Stock Transfer moves stock between warehouses using paired immutable Stock Ledger Records at the source carrying cost. It does not create a financial posting because the movement is internal to one legal entity. The Stock Balance report derives quantity and carrying value from the Stock Ledger.


## v0.14.0 — Inventory Valuation Methods

Inventory Item now supports Moving Average, FIFO and periodic Weighted Average as distinct valuation policies. FIFO issues consume oldest cost layers and warehouse transfers preserve those layer costs. Weighted Average uses provisional issue costs during the period and an approved Inventory Valuation Closing to reconcile ending stock and COGS to the final periodic average. Opening Stock Entry provides a controlled stock migration document using an Equity clearing account. Stock Revaluation changes value without changing quantity. See `velora_erp/docs/INVENTORY-VALUATION-v0.14.0.md`.


## v0.15.0 — Inventory Item Selling Price and Cost Protection

VeloraERP now calculates optional cost-based selling prices from Last Purchase Cost (including allocated landed cost), Current Inventory Valuation or the Inventory Item Standard Cost Rate fallback. Customer Group, Inventory Item and default margins support Markup on Cost or Margin on Selling Price. Manual and fixed prices remain subject to server-side below-cost protection. Sales Order and Sales Invoice validations include line discounts and FX conversion; Delivery Note performs an actual warehouse issue-cost check, including FIFO layers. Stock UOM conversion factors now flow through purchase receipts, deliveries and returns. See `velora_erp/docs/SELLING-PRICING-AND-COST-PROTECTION-v0.15.0.md`.

## v0.24.0 — Purchase Invoice Amortisation and Shared Cost Allocation

Purchase Invoice supports amortised costs and shared-cost allocation. Amortised invoices post to a Prepayment Asset and generate independently approved Recognition Schedules with monthly, quarterly, half-yearly or yearly frequency. Shared costs can be split across active Cost Centres and Business Units or assigned to an Intercompany Due From account with a durable outbox instruction. The Purchase Invoice form uses collapsible, conditional sections. The receiving-company intercompany posting still requires the authorised cross-database integration service. See `velora_erp/docs/PURCHASE-INVOICE-AMORTISATION-AND-SHARED-COST-v0.24.0.md`.

## v0.25.0 — Finance Operations and Fixed Asset Lifecycle

VeloraERP now includes an approval-controlled Bank Transaction Processor with CSV paste/import, deterministic Bank Transaction Coding Rules and draft Batch Bank Transaction creation; balanced Batch Bank Transactions; period-end Accruals with scheduled reversal; Fixed Asset Requests; direct Fixed Asset Purchases; Fixed Asset Lease commencement and scheduled Payment settlement; Fixed Asset Revaluation; and Fixed Asset Disposal. Purchase Invoice lines can also be capitalised into the Fixed Asset Register after the invoice posting succeeds, avoiding a duplicate asset-purchase posting. Existing Financial Voucher remains the single native Journal Voucher. New Treasury and Fixed Assets workspaces are created during installation/migration. See `velora_erp/docs/FINANCE-OPERATIONS-AND-FIXED-ASSETS-v0.25.0.md`.
