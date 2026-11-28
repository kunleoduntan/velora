# Velora Governance v6.1.0–v6.5.0 Runtime-First Batch

## Direction
This batch implements operational automation in the Governance application source rather than adding abstract-only contracts. The implementation remains subject to live Velora runtime qualification.

## v6.1.0 — Automation Generation and Persistence
- Reads due governance records from an explicit allow-list of DocTypes.
- Evaluates reminder/escalation timing through the existing governance automation evaluator.
- Creates persistent `Governance Automation Execution` records through the native Document API repository.
- Generates SHA-256 idempotency keys from source item, action, due date and timing window.
- Suppresses duplicate records through the repository's unique idempotency field.
- Skips actions without a responsible recipient and reports `missing_owner`.

## v6.2.0 — Scheduled In-App Notification Execution
- Registers daily action generation and hourly queued execution in scheduler hooks.
- Dispatches only in-app notifications through native `Notification Log`.
- Validates recipient against User; resolves Employee user IDs when an owner is an Employee record.
- Rejects disabled users and invalid recipients.
- Uses a deterministic notification subject token to suppress duplicate Notification Log records after retries.
- Does not send email/SMS or execute workflow approvals.

## v6.3.0 — Persistent Retry Handling
- Records attempts, status, error and next retry time.
- Exponential backoff: 5, 10, 20, 40 minutes, capped at 24 hours.
- Maximum attempts default to 5; exhausted executions become Failed.
- Retry-pending items are skipped until the retry timestamp.
- Manual retry is limited to Failed/Retry Pending records with fewer than 5 attempts.

## v6.4.0 — Permission-Secured Execution History and Monitor UI
- Adds a native Desk Page `governance-automation-monitor`.
- Shows status KPIs, filtered execution history, error information and retry controls.
- Uses a whitelisted API endpoint with native read permission checks and permission-aware `get_list`.
- Retry API validates write permission and lifecycle status.
- Adds a Governance workspace shortcut to the monitor.

## v6.5.0 — Integration and Qualification Pass
- Adds tests for generation, idempotency, Notification Log dispatch, recipient validation, lifecycle execution, retry backoff, permission checks, API retry controls and scheduler hooks.
- Documents runtime qualification boundaries.

## Validation
- Automated test suite: 102 passed.
- Python compilation: passed.
- JSON DocType/page validation: passed (125 DocTypes and monitor Page JSON).
- Package/archive integrity: passed after release build.

## Qualification boundary
The implementation uses the framework API surface in source but has not been executed against a live Velora server in this session. Native Notification Log schema compatibility, scheduler invocation, database uniqueness/concurrency, transaction behavior, permissions, browser behavior and migration/rollback require in-host verification.
