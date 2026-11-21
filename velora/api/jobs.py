"""Administration endpoints for durable background jobs and schedules."""
from __future__ import annotations
from datetime import datetime
from fastapi import Body, FastAPI, Request
from .. import jobs
from ..exceptions import ValidationError

def install_job_routes(app: FastAPI, scope, run):
    @app.get("/api/jobs")
    def list_jobs(request: Request, status: str | None = None, limit: int = 100):
        return run(request, lambda: jobs.list_jobs(status, limit))

    @app.post("/api/jobs")
    def enqueue(request: Request, body: dict = Body(...)):
        def fn():
            jobs._manager()
            run_at = body.get("run_at")
            if run_at:
                try: run_at = datetime.fromisoformat(run_at)
                except (TypeError, ValueError): raise ValidationError("run_at must be an ISO datetime")
            return jobs.enqueue_job(body.get("handler"), body.get("payload") or {},
                priority=body.get("priority", 5), run_at=run_at, max_attempts=body.get("max_attempts", 5),
                idempotency_key=body.get("idempotency_key"), depends_on=body.get("depends_on") or [])
        return run(request, fn)

    @app.post("/api/jobs/{job_id}/retry")
    def retry(request: Request, job_id: str):
        def fn():
            if not jobs.retry_job(job_id): raise ValidationError("Only a dead or blocked job can be retried")
            return {"queued": True}
        return run(request, fn)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(request: Request, job_id: str):
        def fn():
            if not jobs.cancel_job(job_id): raise ValidationError("Job not found or cannot be cancelled")
            return {"cancelled": True}
        return run(request, fn)

    @app.get("/api/job-schedules")
    def schedules(request: Request):
        return run(request, jobs.list_schedules)

    @app.post("/api/job-schedules")
    def create_schedule(request: Request, body: dict = Body(...)):
        def fn():
            first = body.get("first_run")
            if first:
                try: first = datetime.fromisoformat(first)
                except (TypeError, ValueError): raise ValidationError("first_run must be an ISO datetime")
            return jobs.create_schedule(body.get("label"), body.get("handler"), body.get("payload") or {},
                body.get("interval_seconds"), first)
        return run(request, fn)

    @app.post("/api/job-schedules/{schedule_id}/active")
    def schedule_active(request: Request, schedule_id: str, body: dict = Body(...)):
        def fn():
            active = body.get("active")
            if not isinstance(active, bool): raise ValidationError("active must be true or false")
            if not jobs.set_schedule_active(schedule_id, active): raise ValidationError("Schedule not found")
            return {"active": active}
        return run(request, fn)
