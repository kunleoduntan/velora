"""Tenant-local append-only activity event centre.

Events contain field names and safe summaries, never arbitrary document values. The active
site database is the tenant boundary; this module has no cross-tenant lookup or fan-out.
"""
from __future__ import annotations
import json, re, secrets
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, select, insert, update, and_, desc, func
from fastapi import Body, Query, Request
from . import db
from .exceptions import PermissionDenied, ValidationError, DoesNotExistError
from .permissions import get_session, _effective_roles

md = MetaData()
events = Table("vl_activity_event", md,
    Column("id", String(32), primary_key=True),
    Column("occurred_on", DateTime, nullable=False, index=True),
    Column("actor", String(254), nullable=False, index=True),
    Column("event_type", String(40), nullable=False, index=True),
    Column("title", String(240), nullable=False),
    Column("doctype", String(140), index=True),
    Column("document_name", String(180), index=True),
    Column("source", String(24), nullable=False, default="system"),
    Column("correlation_id", String(80)),
    Column("changed_fields", JSON, nullable=False, default=list),
    Column("summary", String(500)),
    Column("metadata", JSON, nullable=False, default=dict),
)
subscriptions = Table("vl_activity_subscription", md,
    Column("id", String(32), primary_key=True),
    Column("owner", String(254), nullable=False, index=True),
    Column("event_type", String(40), nullable=False),
    Column("doctype", String(140)),
    Column("enabled", Integer, nullable=False, default=1),
    Column("created_on", DateTime, nullable=False),
)
cases = Table("vl_audit_case", md,
    Column("id", String(32), primary_key=True), Column("title", String(240), nullable=False),
    Column("description", Text), Column("status", String(24), nullable=False, default="Open"),
    Column("priority", String(16), nullable=False, default="Normal"), Column("doctype", String(140)),
    Column("document_name", String(180)), Column("owner", String(254), nullable=False, index=True),
    Column("assigned_to", String(254)), Column("created_on", DateTime, nullable=False),
    Column("modified_on", DateTime, nullable=False))
case_notes = Table("vl_audit_case_note", md,
    Column("id", String(32), primary_key=True), Column("case_id", String(32), nullable=False, index=True),
    Column("actor", String(254), nullable=False), Column("body", Text, nullable=False),
    Column("created_on", DateTime, nullable=False))
EVENT_TYPES = {"created","updated","submitted","cancelled","deleted","workflow","approval","login","admin","automation","integration","comment"}
SENSITIVE = re.compile(r"(password|secret|token|api.?key|authorization|email|phone|mobile|address|nin|bvn|account.?number|tax.?id)", re.I)

def ensure():
    from .db import extra_tables
    extra_tables.ensure(md)

def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)

def record_event(event_type: str, title: str, *, doctype: str | None = None,
                 document_name: str | None = None, changed_fields=None, summary: str | None = None,
                 source: str = "system", correlation_id: str | None = None, metadata=None,
                 actor: str | None = None):
    """Append an event in the caller's active tenant transaction."""
    ensure()
    if event_type not in EVENT_TYPES: raise ValidationError("Unsupported activity event type")
    s=get_session()
    safe_fields=[]
    for f in (changed_fields or [])[:100]:
        name=str(f)[:140]
        if name and not SENSITIVE.search(name): safe_fields.append(name)
    safe_meta={}
    if isinstance(metadata,dict):
        for k,v in list(metadata.items())[:20]:
            if not SENSITIVE.search(str(k)):
                if isinstance(v,(str,int,float,bool)) or v is None: safe_meta[str(k)[:80]]=str(v)[:160] if isinstance(v,str) else v
    eid=secrets.token_hex(16)
    row={"id":eid,"occurred_on":_now(),"actor":str(actor or s.user)[:254],
         "event_type":event_type,"title":str(title)[:240],"doctype":str(doctype)[:140] if doctype else None,
         "document_name":str(document_name)[:180] if document_name else None,
         "source":source if source in {"ui","api","automation","system","integration"} else "system",
         "correlation_id":str(correlation_id)[:80] if correlation_id else None,
         "changed_fields":safe_fields,"summary":str(summary)[:500] if summary else None,"metadata":safe_meta}
    with db.transaction() as c: c.execute(insert(events).values(**row))
    return {"id":eid}

def _can_read_document(doctype, name):
    from .meta.registry import registry
    from .permissions import check_permission
    meta=registry.get(doctype)
    check_permission(meta,"read")
    # Also verify the specific document exists through the normal document engine.
    from .document.document import get_doc
    get_doc(doctype,name)

def _serialise(row):
    r=dict(row)
    return {"id":r["id"],"at":r["occurred_on"].isoformat()+"Z","actor":r["actor"],
      "event_type":r["event_type"],"title":r["title"],"doctype":r["doctype"],
      "document_name":r["document_name"],"source":r["source"],
      "changed_fields":r["changed_fields"] or [],"summary":r["summary"],"metadata":r["metadata"] or {}}

def feed(limit=30, offset=0, doctype=None, event_type=None, actor_scope="company",
         actor=None, search=None, from_date=None, to_date=None):
    ensure(); session=get_session()
    limit=max(1,min(int(limit),200)); offset=max(0,min(int(offset),100000))
    cond=[]
    if actor_scope not in ("company","mine"): raise ValidationError("Activity scope must be company or mine")
    if doctype: cond.append(events.c.doctype==doctype)
    if event_type:
        if event_type not in EVENT_TYPES: raise ValidationError("Unknown event type")
        cond.append(events.c.event_type==event_type)
    if actor_scope=="mine": cond.append(events.c.actor==session.user)
    if actor and actor_scope=="company": cond.append(events.c.actor==actor)
    if search:
        term=str(search).strip()[:100]
        if term: cond.append(events.c.title.ilike(f"%{term}%") | events.c.document_name.ilike(f"%{term}%") | events.c.summary.ilike(f"%{term}%"))
    for value, op in ((from_date, ">="), (to_date, "<=")):
        if value:
            try: parsed=datetime.fromisoformat(str(value).replace("Z","+00:00")).replace(tzinfo=None)
            except ValueError: raise ValidationError("Date filters must be ISO dates or datetimes") from None
            cond.append((events.c.occurred_on>=parsed) if op==">=" else (events.c.occurred_on<=parsed))
    where=and_(*cond) if cond else True
    with db.transaction() as c:
        rows=c.execute(select(events).where(where).order_by(desc(events.c.occurred_on),desc(events.c.id)).limit(limit).offset(offset)).mappings().all()
        total=c.execute(select(func.count()).select_from(events).where(where)).scalar_one()
    return {"items":[_serialise(x) for x in rows],"total":int(total),"limit":limit,"offset":offset}

def export_feed(**filters):
    import csv, io
    result=feed(limit=200,offset=0,**filters)
    output=io.StringIO(newline=""); writer=csv.writer(output)
    writer.writerow(["Occurred On","Actor","Event Type","Title","DocType","Document","Source","Changed Fields","Summary"])
    for item in result["items"]:
        writer.writerow([item["at"],item["actor"],item["event_type"],item["title"],item["doctype"] or "",
          item["document_name"] or "",item["source"],", ".join(item["changed_fields"]),item["summary"] or ""])
    return {"filename":"velora_audit_export.csv","content":output.getvalue(),"exported":len(result["items"])}

def document_timeline(doctype,name,limit=50,offset=0):
    _can_read_document(doctype,name)
    ensure()
    limit=max(1,min(int(limit),100)); offset=max(0,min(int(offset),10000))
    with db.transaction() as c:
        rows=c.execute(select(events).where(and_(events.c.doctype==doctype,events.c.document_name==name))
          .order_by(desc(events.c.occurred_on),desc(events.c.id)).limit(limit).offset(offset)).mappings().all()
    return {"items":[_serialise(x) for x in rows],"limit":limit,"offset":offset}

def my_subscriptions():
    ensure(); s=get_session()
    with db.transaction() as c:
        rows=c.execute(select(subscriptions).where(subscriptions.c.owner==s.user).order_by(subscriptions.c.event_type)).mappings().all()
    return [{"id":r["id"],"event_type":r["event_type"],"doctype":r["doctype"],"enabled":bool(r["enabled"])} for r in rows]

def save_subscriptions(items):
    ensure(); s=get_session()
    if not isinstance(items,list) or len(items)>50: raise ValidationError("Provide at most 50 subscriptions")
    clean=[]
    for item in items:
        if not isinstance(item,dict) or item.get("event_type") not in EVENT_TYPES: raise ValidationError("Invalid subscription event type")
        doctype=item.get("doctype")
        if doctype is not None and (not isinstance(doctype,str) or len(doctype)>140): raise ValidationError("Invalid subscription DocType")
        clean.append((item["event_type"],doctype,bool(item.get("enabled",True))))
    with db.transaction() as c:
        c.execute(subscriptions.delete().where(subscriptions.c.owner==s.user))
        for et,dt,en in clean:
            c.execute(insert(subscriptions).values(id=secrets.token_hex(16),owner=s.user,event_type=et,doctype=dt,enabled=1 if en else 0,created_on=_now()))
    return {"saved":len(clean)}

def _require_audit_manager():
    roles=set(_effective_roles(get_session()))
    if get_session().user!="Administrator" and not roles.intersection({"System Manager","Auditor","Compliance Manager","Internal Auditor"}):
        raise PermissionDenied("Audit investigation management requires an Auditor, Compliance Manager or System Manager role")

def create_case(title, description="", priority="Normal", doctype=None, document_name=None, assigned_to=None):
    ensure(); _require_audit_manager(); session=get_session()
    title=str(title or "").strip()
    if not title or len(title)>240: raise ValidationError("Case title is required and must not exceed 240 characters")
    if priority not in {"Low","Normal","High","Critical"}: raise ValidationError("Invalid case priority")
    if bool(doctype)!=bool(document_name): raise ValidationError("Provide both DocType and document name, or neither")
    if doctype: _can_read_document(doctype,document_name)
    now=_now(); cid=secrets.token_hex(16)
    with db.transaction() as c:
        c.execute(insert(cases).values(id=cid,title=title,description=str(description or "")[:10000],
          status="Open",priority=priority,doctype=doctype,document_name=document_name,owner=session.user,
          assigned_to=str(assigned_to)[:254] if assigned_to else None,created_on=now,modified_on=now))
        c.execute(insert(case_notes).values(id=secrets.token_hex(16),case_id=cid,actor=session.user,
          body="Investigation case created",created_on=now))
    record_event("admin",f"Audit investigation opened: {title}",doctype=doctype,document_name=document_name,
      summary=f"Case {cid}",source="system",metadata={"case_id":cid,"priority":priority})
    return {"id":cid,"title":title,"status":"Open","priority":priority}

def list_cases(status=None, limit=50, offset=0):
    ensure(); _require_audit_manager()
    limit=max(1,min(int(limit),200)); offset=max(0,min(int(offset),100000))
    cond=[cases.c.status==status] if status else []
    with db.transaction() as c:
        rows=c.execute(select(cases).where(and_(*cond) if cond else True).order_by(desc(cases.c.modified_on)).limit(limit).offset(offset)).mappings().all()
        total=c.execute(select(func.count()).select_from(cases).where(and_(*cond) if cond else True)).scalar_one()
    return {"items":[dict(x) for x in rows],"total":int(total)}

def get_case(case_id):
    ensure(); _require_audit_manager()
    with db.transaction() as c:
        row=c.execute(select(cases).where(cases.c.id==case_id)).mappings().first()
        if not row: raise DoesNotExistError("Audit investigation case not found")
        notes=c.execute(select(case_notes).where(case_notes.c.case_id==case_id).order_by(case_notes.c.created_on)).mappings().all()
    return {"case":dict(row),"notes":[dict(n) for n in notes]}

def update_case(case_id, status=None, assigned_to=None, note=None):
    ensure(); _require_audit_manager(); session=get_session(); now=_now()
    if status is not None and status not in {"Open","In Review","On Hold","Closed"}: raise ValidationError("Invalid investigation status")
    if note is not None and (not str(note).strip() or len(str(note))>10000): raise ValidationError("Investigation note is required and must not exceed 10,000 characters")
    with db.transaction() as c:
        row=c.execute(select(cases).where(cases.c.id==case_id)).mappings().first()
        if not row: raise DoesNotExistError("Audit investigation case not found")
        values={"modified_on":now}
        if status is not None: values["status"]=status
        if assigned_to is not None: values["assigned_to"]=str(assigned_to)[:254] or None
        c.execute(update(cases).where(cases.c.id==case_id).values(**values))
        if note is not None:
            c.execute(insert(case_notes).values(id=secrets.token_hex(16),case_id=case_id,actor=session.user,body=str(note),created_on=now))
    record_event("admin",f"Audit investigation updated: {row['title']}",doctype=row["doctype"],document_name=row["document_name"],
      summary=f"Case {case_id} updated",source="system",metadata={"case_id":case_id,"status":status or row["status"]})
    return get_case(case_id)

def _allowed(fn, body):
    """Only the keyword arguments `fn` accepts, from a request body: a missing or unknown key is a validation matter, not a TypeError (500)."""
    import inspect
    if not isinstance(body, dict): raise ValidationError("The request body must be a JSON object")
    return {k: v for k, v in body.items() if k in inspect.signature(fn).parameters}


def install_routes(app, run_request):
    @app.get("/api/activity")
    def activity_feed(request:Request, limit:int=Query(30), offset:int=Query(0), doctype:str|None=None,
        event_type:str|None=None, scope:str="company", actor:str|None=None, search:str|None=None,
        from_date:str|None=None, to_date:str|None=None):
        return run_request(request,lambda:feed(limit,offset,doctype,event_type,scope,actor,search,from_date,to_date))
    @app.get("/api/activity/export")
    def activity_export(request:Request, doctype:str|None=None,event_type:str|None=None,scope:str="company",
        actor:str|None=None,search:str|None=None,from_date:str|None=None,to_date:str|None=None):
        return run_request(request,lambda:export_feed(doctype=doctype,event_type=event_type,actor_scope=scope,
          actor=actor,search=search,from_date=from_date,to_date=to_date))
    @app.get("/api/activity/document/{doctype}/{name}")
    def activity_document(doctype:str,name:str,request:Request,limit:int=Query(50),offset:int=0):
        return run_request(request,lambda:document_timeline(doctype,name,limit,offset))
    @app.get("/api/activity/subscriptions")
    def activity_subscriptions(request:Request):
        return run_request(request,my_subscriptions)
    @app.put("/api/activity/subscriptions")
    def activity_subscriptions_save(request:Request,body:dict=Body(...)):
        return run_request(request,lambda:save_subscriptions(body.get("items",[])))
    @app.get("/api/audit/cases")
    def audit_cases(request:Request,status:str|None=None,limit:int=Query(50),offset:int=Query(0)):
        return run_request(request,lambda:list_cases(status,limit,offset))
    @app.post("/api/audit/cases")
    def audit_case_create(request:Request,body:dict=Body(...)):
        return run_request(request,lambda:create_case(**{"title":None,**_allowed(create_case,body)}))
    @app.get("/api/audit/cases/{case_id}")
    def audit_case_read(case_id:str,request:Request):
        return run_request(request,lambda:get_case(case_id))
    @app.put("/api/audit/cases/{case_id}")
    def audit_case_update(case_id:str,request:Request,body:dict=Body(...)):
        return run_request(request,lambda:update_case(case_id,**{k:v for k,v in _allowed(update_case,body).items() if k!="case_id"}))
