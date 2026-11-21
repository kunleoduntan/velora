# Background Jobs and Automation (v0.13)

All jobs, recurring schedules and execution results are stored in the **active company's database**. They are not visible or executable from another company database.

## Register an app-owned handler

Installable apps expose named Python callables. Do not accept arbitrary code or arbitrary user-provided Python expressions as job handlers.

```python
# my_app/jobs.py
def rebuild_customer_balance(payload):
    customer = payload["customer"]
    # perform app-specific work
    return {"customer": customer, "rebuilt": True}
```

Declare the callable in the app's `hooks.py` so only installed-app handlers can be queued:

```python
job_handlers = ["my_app.jobs.rebuild_customer_balance"]
```

Enqueue a job from application code:

```python
from velora.jobs import enqueue_job

job = enqueue_job(
    "my_app.jobs.rebuild_customer_balance",
    {"customer": "CUST-0001"},
    priority=2,
    max_attempts=5,
    idempotency_key="rebuild:CUST-0001:2027-01",
)
```

Priority is 1 (highest) through 10 (lowest). An idempotency key prevents duplicate queue entries for the same business operation. `depends_on` accepts existing job IDs; dependent jobs wait until every prerequisite is completed. If a prerequisite fails permanently or is cancelled, the dependent job enters `Blocked`.

## Recurring schedules

System Managers can create recurring schedules through `/api/job-schedules`. Intervals are between 60 seconds and 365 days. The scheduler creates one job for each due schedule and advances `next_run`. If the worker was offline, it skips missed intervals instead of flooding the queue.

## Management API

- `GET /api/jobs?status=Queued&limit=100`
- `POST /api/jobs` with handler, payload, priority, optional `run_at`, `max_attempts`, `idempotency_key`, and `depends_on`
- `POST /api/jobs/{id}/retry` retries Dead or Blocked jobs
- `POST /api/jobs/{id}/cancel` cancels Queued or Retry jobs
- `GET /api/job-schedules`
- `POST /api/job-schedules` with label, handler, payload, interval_seconds and optional first_run
- `POST /api/job-schedules/{id}/active` with `{"active":false}` to pause or resume

Management endpoints require System Manager. Internal application code can enqueue jobs without granting users job-administration privileges.

## Execution, retries and recovery

The company worker drains up to 20 due jobs per pass. Handlers execute in their own database transaction unless the callable sets `manages_transactions = True`. Exceptions are captured, then jobs retry using bounded backoff. Jobs that exhaust `max_attempts` enter the Dead state (the dead-letter queue). Jobs whose worker lease is older than 15 minutes are recovered into Retry, or Dead if their attempt limit is exhausted.

The queue uses atomic status updates and database indexes to coordinate multiple workers. Job handlers should be idempotent because a worker can crash after the business action commits but before the job is marked Completed. External side effects should use provider idempotency keys where supported.

## Isolation and operational boundaries

- Each company has independent job tables, schedules, queues and execution history.
- Tenant/group membership does not create a shared queue.
- Cross-company work must be explicitly orchestrated by an authorised control-plane process; a company job cannot read another company's database.
- Recurring schedules use fixed intervals, not a full cron expression editor.
- A graphical Desk monitoring page, per-handler concurrency caps and distributed queue broker are future enhancements.
