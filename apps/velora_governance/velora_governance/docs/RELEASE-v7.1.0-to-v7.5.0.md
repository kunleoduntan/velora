# Velora Governance v7.5.0 — Automation Operations UX, Monitor Paging & Qualification

## Batch releases
- **v7.1.0:** Configuration form UX grouping and field guidance for automation control, execution limits, retry policy and recipient routing.
- **v7.2.0:** Recipient-routing foundation retained as safe direct-owner and explicit per-source fallback routing. Role fan-out was intentionally not enabled in this batch to avoid broad unintended notifications before live permission/recipient validation.
- **v7.3.0:** Execution Monitor now uses server-side pagination with totals, status filtering, previous/next controls, and bounded page size.
- **v7.4.0:** Configuration change history uses the native DocType `track_changes` capability; manual retry remains native permission checked and status restricted.
- **v7.5.0:** Stabilisation, tests, JSON checks, compile checks and release packaging.

## Validation
- Automated tests: 113 passed.
- Python compileall: passed.
- DocType JSON parsing: passed.
- Monitor paging tests cover total count, status filter, next-page flag, limit clamping and offset clamping.

## Qualification boundary
The changes are validated locally only. Live migration, runtime Document API behavior, actual role/permission checks, scheduler dispatch, Notification Log integration, browser UX, concurrent idempotency, rollback and UAT remain pending in the Velora environment.
