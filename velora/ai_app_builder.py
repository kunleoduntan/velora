"""AI Application Builder: validated, reviewable app blueprints.

Generated code remains a draft. Publishing is restricted to DocType metadata in an
already-installed app through the atomic DocType Creator; code is never executed.
"""
from __future__ import annotations

# Imported at MODULE level on purpose: with `from __future__ import annotations` FastAPI resolves the string annotation `Request`
# in this module's globals. Imported inside install_routes() it is unresolvable and `request` becomes a required query parameter (HTTP 422 on every route).
from fastapi import Body, Request
import ast, json, re, secrets
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, JSON, MetaData, String, Table, insert, select, update
from . import db
from .exceptions import PermissionDenied, ValidationError
from .permissions import get_session, _effective_roles
from .meta.registry import registry
from .meta.spec import DocType
md=MetaData()
builds=Table("vl_ai_app_build",md,Column("id",String(32),primary_key=True),Column("app_key",String(80),nullable=False,index=True),
 Column("title",String(160),nullable=False),Column("spec",JSON,nullable=False),Column("status",String(24),nullable=False),
 Column("created_by",String(254),nullable=False),Column("created_on",DateTime,nullable=False),Column("modified_on",DateTime,nullable=False))
def _ensure():
    from .db import extra_tables
    extra_tables.ensure(md)
def _dev():
    s=get_session(); roles=set(_effective_roles(s))
    if s.user!="Administrator" and not roles.intersection({"System Manager","AI Administrator","Developer","AI Developer"}):
        raise PermissionDenied("AI Application Builder requires Developer access")
def _ai(prompt):
    from .ai_developer import _ai_answer,_strip_fence
    try: return json.loads(_strip_fence(_ai_answer(prompt,50000)))
    except Exception as exc: raise ValidationError("AI did not return valid application JSON") from exc
def generate_blueprint(requirement,app_key,title,module):
    _dev(); _ensure()
    if not isinstance(requirement,str) or not requirement.strip() or len(requirement)>16000: raise ValidationError("Application requirement must be 1–16,000 characters")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,79}",app_key or ""): raise ValidationError("App key must be lowercase snake_case")
    if app_key not in registry.apps: raise ValidationError("Select an already-installed app; new app installation is a separate deployment operation")
    if not isinstance(title,str) or not title.strip() or not isinstance(module,str) or not module.strip(): raise ValidationError("Application title and module are required")
    prompt=("Design a complete Velora application blueprint. Return ONLY JSON with keys app,title,module,summary,doctypes,advisors,reports,workflows,dashboards,roles,test_plan,code_drafts. "
      f"App {app_key}; title {title}; module {module}. Requirement: {requirement}\n"
      "Each doctype must be valid Velora metadata with name,module,app,autoname,title_field,is_submittable,istable,track_changes,description,fields,permissions. "
      "Field types: Data,Text,Int,Float,Currency,Check,Date,Datetime,Select,Link,JSON,Section Break,Column Break,Tab Break,Table. "
      "Use snake_case fieldnames; Link/Table require options; Select options are arrays. Use least privilege. Do not generate executable hooks, SQL, shell or posting logic. "
      "code_drafts must be [{path,language,source}] and remain review-only.")
    spec=_ai(prompt)
    if not isinstance(spec,dict) or not isinstance(spec.get("doctypes"),list) or len(spec["doctypes"])>40: raise ValidationError("Blueprint must contain up to 40 DocType definitions")
    validated=[]; errors=[]
    for raw in spec["doctypes"]:
        if not isinstance(raw,dict): errors.append("Each DocType must be an object"); continue
        raw["app"]=app_key; raw["module"]=module
        try: validated.append(DocType.from_dict(raw,app=app_key,source="AI Application Builder").to_dict())
        except Exception as exc: errors.append(f"{raw.get('name','(unnamed)')}: {str(exc)[:400]}")
    if errors: raise ValidationError("Invalid generated DocTypes: "+"; ".join(errors[:10]))
    code=spec.get("code_drafts",[])
    if not isinstance(code,list) or len(code)>80: raise ValidationError("code_drafts must be a list of at most 80 files")
    safe=[]
    for item in code:
        if not isinstance(item,dict): raise ValidationError("Invalid code draft")
        path=str(item.get("path") or "")
        if not re.fullmatch(r"[A-Za-z0-9_./-]{1,180}",path) or path.startswith("/") or ".." in path.split("/"):
            raise ValidationError("Code draft contains an unsafe relative path")
        language=str(item.get("language") or "text"); source=str(item.get("source") or "")
        if len(source)>50000: raise ValidationError("Generated source exceeds 50,000 characters")
        if language=="python":
            try: ast.parse(source)
            except SyntaxError as exc: raise ValidationError(f"Python draft {path} has syntax error at line {exc.lineno}") from None
        safe.append({"path":path,"language":language,"source":source,"executed":False})
    spec.update({"app":app_key,"title":title,"module":module,"doctypes":validated,"code_drafts":safe,
        "validation":{"valid":True,"doctype_count":len(validated),"code_count":len(safe)}})
    rid=secrets.token_hex(16); now=datetime.now(timezone.utc).replace(tzinfo=None)
    with db.transaction() as c:
        c.execute(insert(builds).values(id=rid,app_key=app_key,title=title,spec=spec,status="draft",created_by=get_session().user,created_on=now,modified_on=now))
    return {"build_id":rid,"status":"draft","blueprint":spec,"code_executed":False}
def list_builds(limit=100):
    _dev(); _ensure(); limit=max(1,min(int(limit),300)); s=get_session()
    with db.transaction() as c: rows=c.execute(select(builds).order_by(builds.c.created_on.desc()).limit(limit)).mappings().all()
    return [{"id":r["id"],"app_key":r["app_key"],"title":r["title"],"status":r["status"],"created_by":r["created_by"],"created_on":r["created_on"]} for r in rows if s.user=="Administrator" or r["created_by"]==s.user]
def publish_doctypes(build_id,confirm=False):
    _dev(); _ensure()
    if confirm is not True: raise PermissionDenied("Explicit confirmation is required")
    with db.transaction() as c: row=c.execute(select(builds).where(builds.c.id==build_id)).mappings().first()
    if not row: raise ValidationError("Application build not found")
    if row["created_by"]!=get_session().user and get_session().user!="Administrator": raise PermissionDenied("Only the build owner or Administrator may publish")
    if row["status"]!="draft": raise ValidationError("Only draft builds can be published")
    from . import site as site_mod
    if not site_mod.current().developer_mode: raise PermissionDenied("Publishing requires developer mode")
    from .devtools import creator
    plan=creator.plan({"doctypes":row["spec"]["doctypes"]},app=row["app_key"],module=row["spec"]["module"],on_conflict="error")
    report=plan.report()
    if not report["ok"]: return {"published":False,"preview":report}
    result=creator.create(plan); site_mod.current().load()
    with db.transaction() as c: c.execute(update(builds).where(builds.c.id==build_id).values(status="metadata_published",modified_on=datetime.now(timezone.utc).replace(tzinfo=None)))
    return {"published":True,"created":result.get("created",[]),"files":result.get("files",[]),"code_drafts_published":False,
      "note":"Generated source code remains review-only. Database schema changes require the standard migration workflow."}
def install_routes(app,run):
    @app.post("/api/ai/app-builder/generate")
    def generate(request:Request,body:dict=Body(...)):
        return run(request,lambda:generate_blueprint(body.get("requirement",""),body.get("app_key",""),body.get("title",""),body.get("module","")))
    @app.get("/api/ai/app-builder/builds")
    def builds_list(request:Request,limit:int=100): return run(request,lambda:list_builds(limit))
    @app.post("/api/ai/app-builder/{build_id}/publish-doctypes")
    def builds_publish(build_id:str,request:Request,body:dict=Body(...)):
        return run(request,lambda:publish_doctypes(build_id,body.get("confirm") is True))
