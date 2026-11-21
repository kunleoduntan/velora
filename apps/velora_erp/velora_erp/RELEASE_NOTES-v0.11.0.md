# VeloraERP v0.11.0

- Added Sales Return and Purchase Return DocTypes, line schemas, approval and central-engine financial reversal adapters.
- Added Create From transitions from Sales Invoice to Sales Return and Purchase Invoice to Purchase Return.
- Enforced cumulative returned net amount against each original invoice line.
- Replaced proposed credit/debit note terminology with the unified Sales Return and Purchase Return model.
- Added Landed Cost Voucher, charge and allocation child DocTypes, with value/quantity/weight/volume/equal allocation calculations.
- Landed Cost Voucher posting remains disabled pending Inventory Valuation Engine integration.
