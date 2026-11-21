# VeloraERP v0.17.0 — Sales Quotation Lifecycle

## Delivered

1. **Sales Quotation** — native, non-posting customer quotation with dates, validity, currency, exchange rate, customer, line items, discounts, price basis, cost snapshot and quotation total.
2. **Independent approval** — uses the existing finance approval transition controls. The creator cannot approve their own quotation; approver identity and timestamp are system-recorded. Submission requires approval and an unexpired validity date.
3. **Inventory pricing integration** — quotations use Inventory Item pricing and the same server-side below-cost check as Sales Orders. Manual prices remain subject to policy.
4. **Partial conversion** — submitted approved quotations can be converted into one or more Sales Orders up to the remaining quantity per source line. Conversion is transactionally protected by the existing source-document lock and preserves rates, discounts, price basis, cost source and source-line identity.
5. **Quotation Register** — date, customer, approval and status filters; quotation value and quantity-conversion visibility.
6. **Sales workspace** — quotation and register shortcuts are added idempotently.

## Controls and boundaries

- Quotation conversion creates a draft Sales Order; it does not submit or post it.
- The source quotation is not modified by conversion.
- Prices inherited from the quotation are not automatically repriced on the Sales Order. The current cost floor is still rechecked when the Sales Order is validated. If costs have increased above the agreed price, the order is blocked for review.
- A quotation cannot be converted after its validity date create a revised quotation with a new validity period and obtain independent approval.
- Live row repricing and a quotation-specific Explain Pricing client action are not included; server-side pricing and validation are authoritative.

## Validation

- Python compilation: passed.
- DocType and report JSON parsing: passed.
- Sales quotation metadata and flow static tests: 3 passed.
- Full application tests and runtime integration tests could not be run in this build environment because the Velora framework runtime package is not installed.
- Browser, PostgreSQL and Oracle integration tests remain outstanding.
