# VeloraERP v0.9.0 — Document Flow Registry

## Delivered

- Declarative document-flow registry with explicit active, planned and disabled status semantics.
- Read API for native Velora Desk Create From menus, including submitted-source validation.
- Full catalogue API for administration and workflow design.
- Existing Sales Invoice → Receipt and Purchase Invoice → Payment transitions registered as executable flows.
- Planned sales and purchasing transitions documented without falsely exposing unimplemented target documents as executable.
- Conversion cardinality made explicit; invoice-to-cash remains one-to-one pending invoice-level allocation controls.
- Conversion service now rejects planned or disabled transitions.

## Not delivered

- Native React Desk button/menu integration.
- Sales Order, Purchase Order, Credit Note, Debit Note, Delivery Note, Purchase Receipt or Waybill DocTypes.
- Partial quantity fulfilment and cumulative over-delivery/over-receipt checks.
- Invoice-level allocation and outstanding-balance enforcement.
- Inventory movement and valuation posting.

## Compatibility

- Requires Velora `>=0.83,<0.84`.
- Existing v0.8.1 conversion function remains available.
