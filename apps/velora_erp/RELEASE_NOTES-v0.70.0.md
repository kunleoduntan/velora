# VeloraERP v0.70.0 — Party reconciliation exceptions and master-data governance

- Detailed party control-account exception classification with source references.
- Explicit tolerance handling and unassigned-party exception identification.
- Reusable contact-set validation with duplicate and primary-contact controls.
- Reusable address-set validation with address-type and primary-address controls.
- No automatic balancing journals or silent party-ledger adjustments.

- Scope: contact/address validators are reusable domain validators, not native persistent contact/address DocTypes.
- Reconciliation exceptions are classified with source references but are not yet persisted, assigned or resolved through a workflow.
