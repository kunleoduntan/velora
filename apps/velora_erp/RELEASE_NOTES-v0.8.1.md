# VeloraERP v0.8.1 — Controlled Create From

- Added a controlled Create From service for follow-on business documents.
- Implemented Sales Invoice to Receipt conversion and Purchase Invoice to Payment conversion.
- Generated documents inherit the party, control account, currency, exchange rate, invoice reference and gross amount without re-keying.
- Optional partial settlement amount supported; it cannot exceed the source invoice total.
- Source document type and source document name are retained on the generated Receipt or Payment.
- Conversion requires a submitted source and a selected bank/cash account.
- Duplicate conversion from the same source to the same target type is rejected.
- Generated documents remain drafts and require normal independent approval and central posting.
- Other commercial and logistics conversions and true invoice outstanding allocation remain future work.
