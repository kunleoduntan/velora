"""Recoverable deleted-draft inbox. Submitted and cancelled documents are never physically deleted."""
from __future__ import annotations
import secrets
from datetime import datetime, timezone, date
from decimal import Decimal
from sqlalchemy import Column, DateTime, JSON, MetaData, String, Table, select, insert, update, and_, desc, func
from fastapi import Query, Request
from .. import db
from ..exceptions import PermissionDenied, ValidationError, DoesNotExistError
from ..permissions import get_session, check_permission, _effective_roles
md=MetaData()
archive=Table("vl_deleted_document",md,Column("id",String(32),primary_key=True),Column("doctype",String(140),nullable=False,index=True),Column("document_name",String(180),nullable=False,index=True),Column("snapshot",JSON,nullable=False),Column("actor",String(254),nullable=False,index=True),Column("deleted_on",DateTime,nullable=False,index=True),Column("status",String(24),nullable=False,default="Deleted"),Column("restored_by",String(254)),Column("restored_on",DateTime),Column("reason",String(500)))
def ensure():
 from ..db import extra_tables
 extra_tables.ensure(md)
def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def _json(v):
 if isinstance(v,(datetime,date)): return v.isoformat()
 if isinstance(v,Decimal): return str(v)
 if isinstance(v,list): return [_json(x) for x in v]
 if isinstance(v,dict): return {str(k):_json(x) for k,x in v.items()}
 return v
def archive_document(doc, reason=None):
 ensure(); session=get_session(); snapshot=_json(doc.as_dict()); rid=secrets.token_hex(16)
 with db.transaction() as c:
  c.execute(insert(archive).values(id=rid,doctype=doc.doctype,document_name=doc.name,snapshot=snapshot,actor=session.user,deleted_on=_now(),status="Deleted",reason=str(reason or "No reason supplied")[:500]))
 return rid
def _require_audit():
 roles=set(_effective_roles(get_session()))
 if get_session().user!="Administrator" and not roles.intersection({"System Manager","Auditor","Compliance Manager","Internal Auditor"}): raise PermissionDenied("Deleted document inbox requires Auditor, Compliance Manager or System Manager role")
def listing(limit=50,offset=0,doctype=None,status=None,actor=None,search=None,from_date=None,to_date=None):
 ensure(); _require_audit(); cond=[]
 if doctype: cond.append(archive.c.doctype==doctype)
 if status: cond.append(archive.c.status==status)
 if actor: cond.append(archive.c.actor==actor)
 if search:
  term=f"%{str(search)[:120]}%"; cond.append(archive.c.document_name.ilike(term)|archive.c.doctype.ilike(term))
 for value,op in ((from_date,">="),(to_date,"<=")):
  if value:
   try: parsed=datetime.fromisoformat(str(value).replace("Z","+00:00")).replace(tzinfo=None)
   except ValueError: raise ValidationError("Date filters must be ISO dates or datetimes") from None
   cond.append(archive.c.deleted_on>=parsed if op==">=" else archive.c.deleted_on<=parsed)
 where=and_(*cond) if cond else True; limit=max(1,min(int(limit),200)); offset=max(0,int(offset))
 with db.transaction() as c:
  rows=c.execute(select(archive).where(where).order_by(desc(archive.c.deleted_on)).limit(limit).offset(offset)).mappings().all()
  total=c.execute(select(func.count()).select_from(archive).where(where)).scalar_one()
 return {"items":[{k:v for k,v in dict(r).items() if k!="snapshot"}|{"snapshot_available":True} for r in rows],"total":int(total),"limit":limit,"offset":offset}
def get_item(rid):
 ensure(); _require_audit()
 with db.transaction() as c: row=c.execute(select(archive).where(archive.c.id==rid)).mappings().first()
 if not row: raise DoesNotExistError("Deleted document record not found")
 return dict(row)
def restore(rid):
 ensure(); _require_audit(); item=get_item(rid)
 if item["status"]!="Deleted": raise ValidationError("Only a deleted draft can be recalled")
 from .document import new_doc
 snap=dict(item["snapshot"]); doctype=item["doctype"]; name=item["document_name"]
 # Recreate only a draft. System fields are generated afresh; original business values and child rows are preserved.
 for key in ("doctype","owner","creation","modified","modified_by","docstatus","amended_from"):
  snap.pop(key,None)
 snap["name"]=name
 doc=new_doc(doctype,**snap).insert()
 session=get_session(); now=_now()
 with db.transaction() as c:
  c.execute(update(archive).where(archive.c.id==rid).values(status="Restored",restored_by=session.user,restored_on=now))
 from ..activity import record_event
 record_event("admin",f"Deleted draft restored: {doctype} {name}",doctype=doctype,document_name=name,summary=f"Recycle bin item {rid} restored",source="system",metadata={"recycle_bin_id":rid})
 return {"restored":True,"doctype":doctype,"name":name,"id":rid}

def correction_inbox(limit=50,offset=0,doctype=None,event_type=None,actor=None,search=None,from_date=None,to_date=None):
 ensure(); _require_audit()
 from ..activity import feed
 # Cancellation/deletion lifecycle events remain in the append-only event stream.
 result=feed(limit=limit,offset=offset,doctype=doctype,event_type=event_type,actor_scope="company",actor=actor,search=search,from_date=from_date,to_date=to_date)
 result["items"]=[x for x in result["items"] if x["event_type"] in ("cancelled","deleted")]
 # Attach archive IDs so deleted drafts can be recalled directly from this inbox.
 with db.transaction() as c:
  rows=c.execute(select(archive.c.id,archive.c.doctype,archive.c.document_name,archive.c.status).order_by(desc(archive.c.deleted_on))).mappings().all()
 lookup={(r["doctype"],r["document_name"]):dict(r) for r in rows}
 for item in result["items"]:
  if item.get("event_type")=="deleted":
   archived=lookup.get((item.get("doctype"),item.get("document_name")))
   if archived: item["recycle_bin_id"]=archived["id"]; item["recycle_bin_status"]=archived["status"]
 return result

def install_routes(app,run_request):
 @app.get("/api/document-corrections/inbox")
 def corrections_inbox(request:Request,limit:int=Query(50),offset:int=0,doctype:str|None=None,event_type:str|None=None,actor:str|None=None,search:str|None=None,from_date:str|None=None,to_date:str|None=None):
  return run_request(request,lambda:correction_inbox(limit,offset,doctype,event_type,actor,search,from_date,to_date))
 @app.get("/api/document-corrections/deleted")
 def deleted_inbox(request:Request,limit:int=Query(50),offset:int=0,doctype:str|None=None,status:str|None=None,actor:str|None=None,search:str|None=None,from_date:str|None=None,to_date:str|None=None):
  return run_request(request,lambda:listing(limit,offset,doctype,status,actor,search,from_date,to_date))
 @app.get("/api/document-corrections/deleted/{rid}")
 def deleted_item(rid:str,request:Request): return run_request(request,lambda:get_item(rid))
 @app.post("/api/document-corrections/deleted/{rid}/restore")
 def deleted_restore(rid:str,request:Request): return run_request(request,lambda:restore(rid))
