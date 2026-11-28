"""AI migration assistant using the canonical Velora schema migrator in dry-run mode.

It never invents or executes DDL. Applying changes remains the responsibility of the
standard upgrade orchestrator, which handles locks, backups, patches and health checks.
"""
from __future__ import annotations

# Imported at MODULE level on purpose: with `from __future__ import annotations` FastAPI resolves the string annotation `Request`
# in this module's globals. Imported inside install_routes() it is unresolvable and `request` becomes a required query parameter (HTTP 422 on every route).
from fastapi import Body, Request
import hashlib,json,secrets
from datetime import datetime,timezone
from sqlalchemy import Column,DateTime,JSON,MetaData,String,Table,insert,select,update
from . import db
from .exceptions import PermissionDenied,ValidationError
from .permissions import get_session,_effective_roles
md=MetaData()
plans=Table("vl_ai_migration_plan",md,Column("id",String(32),primary_key=True),Column("fingerprint",String(64),nullable=False),
 Column("plan",JSON,nullable=False),Column("status",String(24),nullable=False),Column("created_by",String(254),nullable=False),Column("created_on",DateTime,nullable=False))
def _ensure():
    from .db import extra_tables
    extra_tables.ensure(md)
def _admin():
    s=get_session(); roles=set(_effective_roles(s))
    if s.user!="Administrator" and not roles.intersection({"System Manager","AI Administrator"}): raise PermissionDenied("Migration planning requires System Manager or AI Administrator")
def preview_schema_migration():
    _admin()
    from .db import schema
    operations=schema.migrate(dry_run=True)
    warnings=[x for x in operations if x.startswith("WARNING:")]
    payload={"operations":operations}
    fp=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
    return {"fingerprint":fp,"operations":operations,"safe_operation_count":len(operations)-len(warnings),"warnings":warnings,
      "live_database_changed":False,"apply_via":"velora upgrade --dry-run, then velora upgrade after backup and approval","automatic_drop_or_shrink":False}
def save_plan():
    _admin(); _ensure(); preview=preview_schema_migration(); rid=secrets.token_hex(16); now=datetime.now(timezone.utc).replace(tzinfo=None)
    with db.transaction() as c: c.execute(insert(plans).values(id=rid,fingerprint=preview["fingerprint"],plan=preview,status="review_required",created_by=get_session().user,created_on=now))
    return {"plan_id":rid,**preview,"status":"review_required"}
def approve_plan(plan_id,confirm=False):
    _admin(); _ensure()
    if confirm is not True: raise PermissionDenied("Explicit migration plan approval is required")
    with db.transaction() as c: row=c.execute(select(plans).where(plans.c.id==plan_id)).mappings().first()
    if not row: raise ValidationError("Migration plan not found")
    if row["status"]!="review_required": raise ValidationError("Migration plan is no longer awaiting review")
    current=preview_schema_migration()
    if current["fingerprint"]!=row["fingerprint"]: raise ValidationError("Live schema changed since preview; create and review a new plan")
    with db.transaction() as c: c.execute(update(plans).where(plans.c.id==plan_id).values(status="approved_for_upgrade"))
    return {"approved":True,"status":"approved_for_upgrade","execution":"not_run","next_step":"Run the standard Velora upgrade workflow; approval does not bypass backup, locking, maintenance or health checks."}
def install_routes(app,run):
    @app.post("/api/ai/migrations/preview")
    def migration_preview(request:Request): return run(request,preview_schema_migration)
    @app.post("/api/ai/migrations/plans")
    def migration_save(request:Request): return run(request,save_plan)
    @app.post("/api/ai/migrations/plans/{plan_id}/approve")
    def migration_approve(plan_id:str,request:Request,body:dict=Body(...)):
        return run(request,lambda:approve_plan(plan_id,body.get("confirm") is True))
