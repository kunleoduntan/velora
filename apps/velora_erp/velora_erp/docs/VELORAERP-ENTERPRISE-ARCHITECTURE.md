# VeloraERP Enterprise Architecture and Finance Design Standard

**Document status:** Baseline design standard  
**Applies to:** VeloraERP and extensions consuming its finance services  
**Framework baseline:** Velora 0.83.x  
**Application baseline:** VeloraERP 0.4.x

## 1. Product ambition and engineering standard

VeloraERP is intended to compete in complex, multi-entity enterprise environments. The ambition to outperform established ERP products is a product objective, not a claim of current capability. It must be earned through measurable quality: accounting correctness, control coverage, usability, reliability, extensibility, security, performance, implementation effort and total cost of ownership.

We will not attempt to win by copying a competitor's screens or by accumulating the largest number of features. We will build a coherent enterprise platform with strong financial foundations and excellent operational workflows.

### Enterprise quality gates

A capability is not complete merely because a form saves. Each material feature must have:
- Defined business owner, lifecycle, data ownership and accounting impact.
- Metadata, server-side validation, permissions and workflow.
- Audit events and traceability.
- Idempotent processing where retries or integrations are possible.
- Database constraints and transaction boundaries appropriate to the data.
- Unit, integration, migration, permission and negative-path tests.
- Operational observability: structured logs, metrics, correlation IDs and actionable errors.
- Documented APIs, configuration and upgrade behaviour.
- Performance tests for expected enterprise volumes.
- Backup, restore and recovery implications.
- Accessibility, keyboard navigation and responsive behaviour in the React experience.

## 2. Product and application boundaries

- **Velora Framework** provides metadata, document lifecycle, permissions, workflow, audit, APIs, notifications, files, reports, background jobs, UI infrastructure and database abstraction.
- **VeloraERP** provides the integrated accounting and business core.
- **Industry applications** add domain workflows and data while consuming VeloraERP services. They must not create a competing ledger or duplicate common financial masters.

Manufacturing and other specialist operations remain separate applications. They can consume inventory, purchasing, sales, costing and financial capabilities according to declared dependencies.

### Company and database isolation

Each legal entity operates in its own database. Company switching selects the corresponding database context. Operational master data and transactions are not shared across legal entities. Consolidation and intercompany services are explicitly authorised cross-database services, not shared operational tables.

## 3. Finance workspace

Finance is the first and foundational VeloraERP area. It owns:
1. Finance Overview
2. Account Structure
3. Financial Processing
4. Account Ledger and subledger controls
5. Sales and Receivables
6. Purchasing and Payables
7. Cash and Banking
8. Tax Management
9. Multi-Currency
10. Financial Periods and Closing
11. Financial Reporting and Analytics
12. Audit and Financial Controls

Inventory, Fixed Assets, Budget, Employee Finance and Payroll are integrated VeloraERP capabilities, each with clear subledger and posting contracts.

## 4. Finance account structure (implemented foundation in v0.2.0)

The first account-structure release establishes the master-data relationships before any posting engine is introduced.

| DocType | Responsibility | Key rules |
|---|---|---|
| Account Type | Configurable classification, financial class, normal balance and control defaults | Standard types are seeded; contra-account normal balances are supported |
| Account Group | Hierarchical account classification | Each branch retains one financial class; groups with accounts/children cannot change class |
| Account | Postable financial account | Financial class derives from its group; normal balance and party/reconciliation controls derive from Account Type |
| Cost Centre | Management accounting allocation hierarchy | Parent must be a group; hierarchy loops are rejected |
| Accounting Dimension | Configurable transaction analysis axis | Can use controlled values, installed masters or validated scalar values |
| Dimension Value | Controlled value set | Value code is unique within a dimension; parent values must belong to the same dimension |
| Financial Statement Row | Financial statement presentation hierarchy | Rows are statement-specific; only eligible summary rows receive account mappings |
| Account Statement Mapping | Account/group-to-report mapping | Exactly one mapping target; duplicate account/group mappings within a statement are rejected |

### Account classification

The five financial classes are Asset, Liability, Equity, Income and Expense. Account Type separately controls normal balance, party tracking, control-account eligibility and reconciliation defaults. This is important because contra accounts can legitimately have a normal balance opposite to the broad financial class (for example, accumulated depreciation is an Asset-class account with a Credit normal balance).

Account Group determines the financial class. Account Type must be compatible with that class. The Account stores the resolved class and normal balance as derived values; users do not manually override them.

### Release boundary

The v0.2.0 release does not post opening balances, create ledger lines, evaluate financial statement formulas or enforce ledger-based account immutability. Those controls depend on the central posting engine and will be introduced before production financial transactions are enabled.

## 5. Unified Settings experience

Users will access one **Settings** workspace. This is a unified navigation and administration experience, not one giant configuration table.

### Settings sections

- Organisation and legal entity
- Accounting policies and account defaults
- Financial years and periods
- Currency and exchange-rate policy
- Tax and withholding configuration
- Receivables and credit policy
- Payables and supplier payment policy
- Banking and payment methods
- Inventory accounting and valuation
- Fixed asset policy and depreciation books
- Budget controls
- Payroll and employee tax accounting
- Document numbering and lifecycle defaults
- Approval policy and segregation of duties
- Localisation, language, date, number and regional formats
- Integrations and external service credentials
- Audit, retention and security controls

### Configuration data rules

- Every setting declares scope: platform default, application, legal entity, branch, module, user or integration.
- Inheritance is explicit and visible. Sensitive financial settings must not silently inherit across legal entities.
- Effective-dated settings are used when a policy can change over time.
- Configuration changes are permission-controlled, audited, validated and previewable.
- Credentials are stored using the framework's secrets facility; they are never exposed again after save.
- High-risk changes can require dual approval and a scheduled effective date.

## 6. Standard business document terminology

VeloraERP will use established, recognisable names where they accurately describe the business process. A familiar document name is not a reason to copy another ERP's internal implementation.

### 6.1 Sales lifecycle

| Document | Purpose |
|---|---|
| Lead | Potential customer or sales contact, if CRM capability is enabled |
| Sales Quotation | Commercial offer to a customer |
| Sales Order | Customer commitment and demand authorisation |
| Delivery Note | Evidence of goods dispatched/delivered |
| Sales Invoice | Receivable and revenue/tax recognition document |
| Sales Return | Physical/commercial return and corresponding customer financial reversal |
| Sales Return | Physical return of goods, where inventory is affected |
| Receipt | Customer money received |
| Customer Allocation | Application of receipts/credits to open invoices |
| Customer Statement | Account activity and outstanding balance presentation |

### 6.2 Purchasing lifecycle

| Document | Purpose |
|---|---|
| Purchase Requisition | Internal request to procure goods or services |
| Request for Quotation | Invitation to suppliers to quote |
| Supplier Quotation | Supplier's commercial offer |
| Purchase Order | Authorised commitment to purchase |
| Purchase Receipt | Evidence of goods received |
| Service Confirmation | Evidence that a service was performed/accepted |
| Purchase Invoice | Supplier liability and expense/asset/tax recognition |
| Purchase Return | Physical/commercial return and corresponding supplier financial reversal |
| Purchase Return | Physical return of goods |
| Payment | Money paid to a supplier or other beneficiary |
| Supplier Allocation | Application of payments/credits to open invoices |
| Supplier Statement | Supplier account activity and reconciliation |

### 6.3 Financial and treasury documents

- Payment
- Receipt
- Bank Transfer
- Bank Statement
- Bank Reconciliation
- Financial Voucher (working name for controlled non-subledger adjustments)
- Recurring Transaction Schedule
- Prepayment Schedule
- Accrual Schedule
- Foreign Currency Revaluation
- Period Closing Run
- Financial Year Closing Run

### 6.4 Inventory and asset documents

- Item
- Item Group
- Warehouse
- Stock Transfer
- Stock Adjustment
- Stock Reconciliation
- Stock Count
- Landed Cost Allocation
- Fixed Asset
- Asset Acquisition
- Depreciation Run
- Asset Transfer
- Asset Revaluation
- Asset Impairment
- Asset Disposal
- Asset Verification

### 6.5 Naming policy

- Use standard business names when they are clear and internationally understood.
- Avoid unnecessary renaming merely to look different from competitors.
- Do not use `GL Entry`, `General Ledger Entry` or `Journal Entry` as VeloraERP's core accounting record or core adjustment document names.
- Internal technical table names may differ from user-facing labels, but must be consistent, documented and stable.
- Do not use hyphens in DocType names.
- Document names, API identifiers and database identifiers are versioned contracts; changes require migration plans and compatibility tests.

## 7. Financial data architecture

### 7.1 Source transactions and financial records are distinct

Sales Invoice, Purchase Invoice, Payment, Receipt, asset events, payroll runs and inventory valuation events are business source documents. The Account Ledger is the authoritative posted financial record. The source document remains the business evidence and workflow record.

### 7.2 Central posting service

Only the central Financial Posting Service may create posted Account Ledger records. It accepts validated, classified posting instructions from source modules.

Posting service responsibilities:
1. Validate company/database context and authorisation.
2. Validate source document state and posting eligibility.
3. Resolve account mappings and accounting dimensions.
4. Validate financial period and posting date.
5. Validate currencies, rates and precision.
6. Validate balanced debit/credit totals in base currency.
7. Enforce idempotency and source-document uniqueness.
8. Persist the ledger batch and lines atomically.
9. Record source references, correlation ID, actor and audit events.
10. Return a durable posting reference to the source document.

### 7.3 Account Ledger record requirements

At minimum, ledger lines need:
- Company context and ledger/book identifier
- Posting date and financial period
- Account
- Debit and credit in base currency
- Transaction currency, debit/credit and exchange rate
- Source document type, ID and line reference
- Posting batch/reference
- Party type and party
- Branch, cost centre, project and configured dimensions
- Tax code and tax transaction reference where applicable
- Reversal and correction references
- Creation actor/time and correlation ID

### 7.4 Immutability and correction

Posted ledger lines are immutable. Corrections use reversal and replacement postings, preserving the original transaction and full lineage. A cancelled source document cannot erase posted history. Reversal permissions and periods are controlled.

### 7.5 Balancing and subledger reconciliation

- Every posting batch balances.
- Receivables reconcile to receivables control accounts.
- Payables reconcile to payables control accounts.
- Inventory valuation reconciles to inventory control accounts.
- Fixed asset cost and accumulated depreciation reconcile to their control accounts.
- Payroll liabilities reconcile to payroll control accounts.
- Tax subledgers reconcile to tax control accounts.
- Differences are surfaced as assigned exceptions; they are not silently adjusted.

## 8. Transaction lifecycle and approvals

The common lifecycle is configurable but must preserve explicit states such as Draft, Submitted, Pending Approval, Approved, Posted, Rejected, Cancelled and Reversed where relevant.

Approval policy supports:
- Amount thresholds and cumulative exposure
- Company, branch, department, account, category and dimension
- Maker-checker and multi-stage approval
- Delegation with effective dates and limits
- Conflict-of-interest and self-approval restrictions
- Escalation and service-level timers
- Evidence and reason capture
- Separation of preparation, approval, payment execution and reconciliation

A workflow approval does not itself mean a document has been posted. Posting is a distinct controlled action.

## 9. Enterprise document experience

The React application uses Velora's own enterprise design system. It should combine dense, efficient business forms with clear modern visual hierarchy.

### Application shell
- Global navigation and role-aware workspaces
- Company/database switcher with visible active legal entity
- Global search and command palette
- Task inbox, approvals and notifications
- Recent records and favourites
- Context-aware help and user profile

### Transaction form
- Document identity, status, owner and lifecycle
- Command bar with actions permitted by state and role
- Header fields grouped by business purpose
- Editable line grid with keyboard-first entry
- Tax, discount, charge and currency breakdown
- Totals and validation summary
- Related documents and process flow
- Attachments, comments and audit timeline
- Approval history and posting references

### List and workbench
- Saved views, filters, grouping and column configuration
- Bulk actions with permission and confirmation controls
- Exception queues and aging analysis
- Export controls with audit logging
- Responsive performance for large datasets

The UI must not bypass server validation, permissions, workflows, posting rules or lifecycle controls.

## 10. Extension contract for industry applications

Industry applications integrate through versioned contracts:
- Master-data references and party services
- Document lifecycle and approval APIs
- Financial Posting Service
- Tax calculation service
- Payment and receipt services
- Inventory availability and valuation services
- Fixed asset services
- Employee/payroll services where licensed
- Reporting dimensions and analytics APIs
- Audit and evidence APIs

Each app declares required capabilities and compatible VeloraERP versions. It must not directly insert into finance tables or depend on undocumented internal fields.

## 11. Localisation and accounting frameworks

Country packs configure currency, fiscal defaults, tax rules, withholding, statutory reports, invoice requirements, payment conventions, account templates and terminology. Tax and statutory rules are effective-dated and versioned.

Initial target packs: Nigeria, Ghana, United Kingdom, United States and Côte d'Ivoire. The accounting engine remains country-neutral. Accounting-standard mappings and report presentations are configurable; software functionality alone does not constitute statutory or IFRS compliance certification.

## 12. Non-functional requirements

The release process must measure:
- Financial integrity and reconciliation correctness
- Availability, recovery point and recovery time objectives
- Transaction throughput and concurrent-user performance
- API latency and integration retry behaviour
- Data isolation and permission enforcement
- Audit completeness and tamper resistance
- Upgrade and rollback reliability
- Accessibility and usability
- Test coverage of critical financial paths
- Operational diagnostics and supportability

Targets must be set by deployment tier and validated by repeatable tests. We will not publish performance or compliance claims without evidence.

## 13. Delivery sequence

1. Finance foundation and unified settings
2. Common masters and account structure
3. Financial Posting Service and Account Ledger
4. Financial Voucher and recurring/accrual/prepayment controls
5. Sales and receivables
6. Purchasing and payables
7. Payments, receipts, banking and reconciliation
8. Tax and multi-currency
9. Inventory and valuation
10. Fixed assets
11. Budget management
12. Employee finance, payroll and employee tax
13. Financial reporting and analytics
14. Audit, period close and financial governance
15. Intercompany and consolidation

Every release must include migration, permissions, audit, negative-path and integration tests for the functionality it claims to deliver.

## 15. v0.3.0 posting engine implementation status

The first implementation of the financial posting architecture is delivered in VeloraERP v0.3.0:

- `Financial Posting Batch` is the submitted posting envelope and source-event record.
- `Financial Posting Line` stores each account debit or credit, party, cost centre and dimensions.
- `Account Ledger Record` is the append-only authoritative account-level record.
- `velora_erp.finance.engine.post_financial_transaction` is the supported posting service.
- `velora_erp.finance.engine.reverse_financial_posting` appends an exact reversal in an open period.
- `get_account_balance` and `get_account_activity` query the ledger source of truth.

The service validates the Financial Year and Financial Period, account eligibility, currency restrictions, required party values, cost centres, mandatory dimensions, Decimal conversions, and debit/credit equality in transaction and base currency. Batch and ledger writes share the framework transaction. Identical source-event retries are idempotent; conflicting content is rejected.

The current release is an engine foundation, not a complete production ledger suite. Currency rounding accounts, master-backed party validation, provider-specific dimension validation, full audit correlation, trial balance, statement execution, opening balance migration, subledger reconciliation and live PostgreSQL/Oracle/browser/load testing remain outstanding.


## 13. Tight GUI and reporting integration (v0.4.0)

VeloraERP uses the native Velora React Desk rather than a parallel front end. The Finance module's DocTypes appear in the standard module navigation; script reports appear in the governed Reports navigation; financial statement layouts run through the existing Financial Report Designer and its statement drill-down.

Installation and upgrade seed a company-scoped Finance workspace with shortcuts to Account Structure, Financial Voucher, Opening Balance Entry, Trial Balance, Account Ledger, Financial Statements, Finance Settings and Financial Periods. It also provides ledger/voucher KPIs and the native activity feed. The workspace becomes the company default only when no company default already exists; a user's personal default continues to take precedence.

Financial Voucher and Opening Balance Entry use the framework's standard document shell, metadata-driven fields, child-table grid, save/submit lifecycle, permissions, workflow/audit infrastructure and list-view indicators. Contextual form actions navigate to the relevant ledger/reporting screens. No separate GUI data model or alternate permission system is introduced.

The framework 0.83 financial reporting provider contract is declared in `velora_erp.hooks`. The provider maps the VeloraERP Account and Account Group masters plus Account Ledger Record to the canonical financial statement and drill-down interface. All statement amounts use company base currency. The framework's legacy Account/GL Entry adapter remains available for existing installations, but VeloraERP does not write to or query those legacy tables.

### v0.4.0 controlled source documents

- Financial Voucher is a controlled adjustment source document. When Finance Settings requires approval, an independent Finance Manager or System Manager must approve it before submission. Self-approval is rejected. Submission calls the central posting service and records the resulting Financial Posting Batch reference.
- Opening Balance Entry is always independently approved, restricted to Asset, Liability and Equity accounts, uses company base currency and rate 1, and posts through the same engine. A unique migration reference and idempotency key prevent duplicate cutover posting.
- Both source documents reject cancellation after submission. Corrections require the controlled reversal process.

These are implemented foundations; live production database, browser, concurrency and security validation remain required before production use.


## Return and landed cost policy (v0.11.0)

VeloraERP standardises commercial returns as **Sales Return** and **Purchase Return**. Separate Sales Credit Note, Purchase Debit Note or Supplier Debit Note DocTypes are not introduced. Return documents are linked to the originating invoice and reverse the financial value through the central posting engine. From v0.12.0, stock-managed return lines also create inventory quantity and valuation movements through the Stock Ledger.

Landed Cost Voucher captures directly attributable acquisition charges and allocates them across received items using value, quantity, weight, volume or equal allocation. From v0.12.0 it requires independent approval, capitalises the on-hand portion into inventory valuation and adjusts Cost of Goods Sold for the consumed portion. See `INVENTORY-LEDGER-AND-STOCK-RECONCILIATION-v0.12.0.md`.


## Inventory ledger and stock reconciliation (v0.12.0)

The Inventory Engine maintains an append-only Stock Ledger Record as the source of truth for stock quantities and valuation. Stock Reconciliation is the approved physical count and stock adjustment document. Its lines display current stock balance, physical count, adjustment, current cost, proposed price, current value and value adjustment. Positive quantity differences are valued at the proposed price; shortages are removed at current moving-average cost; zero quantity differences do not revalue existing stock.

Purchase Receipt, Delivery Note, Sales Return and Purchase Return post quantity/value movements and corresponding financial entries through the central Financial Posting Engine. Serial and batch identities are maintained separately from the quantity ledger. Landed Cost Voucher capitalises eligible costs into stock still on hand and assigns the consumed portion to Cost of Goods Sold. Moving Average is implemented; FIFO, stock transfer, opening stock entry, stock revaluation and GRNI matching are not yet implemented. Backdated stock movements are blocked until historical reposting is available.
