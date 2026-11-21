# VeloraERP — Finance Foundation and Enterprise Design Baseline v0.1.1

## Product architecture
- `velora` is the independently versioned application framework.
- `velora_erp` is a separately versioned accounting and business core application.
- Industry applications are separately versioned extensions that declare the VeloraERP capabilities and compatible versions they require.
- The existing `velora_accounts` app is retained as a legacy/reference app and is not a dependency of VeloraERP.

## Version compatibility and coordinated updates
- VeloraERP v0.1.1 declares `velora>=0.82,<0.83`.
- Framework-only updates and ERP-only updates can be released independently when compatibility permits.
- Cross-cutting changes must publish a tested framework/ERP version pair and explicit upgrade order.
- Keep separate repositories and tags for `velora` and `velora_erp`. A combined development workspace may contain both for integration testing.
- Back up each company database before applying migrations. Do not assume that application code updates imply successful schema/data migrations.

## Product naming
VeloraERP uses familiar business transaction names including Sales Invoice, Purchase Invoice, Sales Order, Purchase Order, Payment and Receipt. It will not adopt `GL Entry`, `General Ledger Entry` or `Journal Entry` as its core accounting record/document names. See `apps/velora_erp/docs/VELORAERP-ENTERPRISE-ARCHITECTURE.md`.

## Finance foundation included
- Finance Settings: a company-local configuration record with grouped General, Posting Controls, Currency, Tax Defaults, and Audit and Control settings.
- Financial Year.
- Financial Period linked to Financial Year.
- Install hook creating Nigeria/NGN defaults for a new company database; these are editable defaults, not jurisdiction restrictions.

## v0.1.1 design baseline
- Enterprise architecture and quality gates.
- Unified Settings workspace model with separately scoped configuration records.
- Standard sales, purchasing, treasury and asset document catalogue.
- Review of supplied Ecclesia source for useful domain capabilities and patterns, redesigned for Velora.
- Explicit source-reuse rule: business requirements and interaction patterns may inform design; Frappe code, hooks, database structures and UI are not transplanted.

## Important implementation boundary
The document catalogue is a planned scope, not proof of implementation. The Financial Posting Service, Account Ledger, Account Structure, Sales Invoice, Purchase Invoice, Sales Order, Purchase Order, payment processing, bank reconciliation, tax engine and other capabilities remain to be built and tested.

## Install into a workspace
Place `apps/velora_erp` in the workspace's `apps/` directory, register the app in the workspace app catalogue, then install it on the target company site using the Velora app installation workflow. Run the supported migration command after installation.

Do not install `velora_accounts` alongside `velora_erp` as a shortcut; the legacy app has overlapping accounting concepts and is not a dependency of this new product.
