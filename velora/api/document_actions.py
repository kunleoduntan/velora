from __future__ import annotations
from datetime import datetime, timezone
import importlib
from fastapi import Body, FastAPI, Request
from sqlalchemy import delete, insert, select
from .. import db
from ..db.system import doc_share
from ..document.document import get_doc
from ..exceptions import ValidationError
from ..meta.registry import registry
from ..permissions import check_permission, get_session

DEFAULT_EMAIL_LIMIT=100


def _document_flow_provider():
 """Resolve the single installed app that declares a document-flow provider."""
 providers=[]
 for app_name in registry._apps:
  try: hooks=importlib.import_module(f"{app_name}.hooks")
  except ModuleNotFoundError as exc:
   if exc.name == f"{app_name}.hooks": continue
   raise
  path=getattr(hooks,"document_flow_provider",None)
  if path:
   providers.append(importlib.import_module(path))
 if len(providers)>1: raise ValidationError("Multiple document-flow providers are installed; configure exactly one provider.")
 if not providers: raise ValidationError("No installed application provides document conversion workflows.")
 return providers[0]


def _document_pricing_provider():
 """Resolve the single installed application that supplies authoritative row pricing."""
 providers=[]
 for app_name in registry.apps:
  try: hooks=importlib.import_module(f"{app_name}.hooks")
  except ModuleNotFoundError as exc:
   if exc.name == f"{app_name}.hooks": continue
   raise
  path=getattr(hooks,"document_pricing_provider",None)
  if path:
   if not isinstance(path,str) or "." not in path:
    raise ValidationError(f"{app_name}.hooks.document_pricing_provider must be a dotted module path")
   providers.append((app_name,importlib.import_module(path)))
 if len(providers)>1:
  names=", ".join(name for name,_ in providers)
  raise ValidationError(f"Multiple document-pricing providers are installed ({names}). Configure exactly one provider.")
 if not providers:
  raise ValidationError("No installed application provides document pricing.")
 return providers[0][1]

def _email_limit():
 from velora_notify.channels import settings
 try: return max(1,int(((settings() or {}).get("email") or {}).get("user_hourly_limit") or DEFAULT_EMAIL_LIMIT))
 except (TypeError,ValueError): return DEFAULT_EMAIL_LIMIT
def _reserve_email_slot(doctype,name,to):
 """Count this send against the signed-in user's hourly allowance BEFORE sending (so parallel requests cannot all slip under the limit); a failed send gives it back."""
 import secrets
 from datetime import timedelta
 from sqlalchemy import func
 from ..db.system import export_log
 user=get_session().user; now=datetime.now(timezone.utc).replace(tzinfo=None); limit=_email_limit(); slot=secrets.token_hex(8)
 with db.transaction() as c:
  c.execute(insert(export_log).values(name=slot,ref_doctype=doctype,owner=user,creation=now,scope="email",row_count=1,detail={"to_domain":to.rsplit("@",1)[-1],"docname":name}))
  used=c.execute(select(func.count()).select_from(export_log).where(export_log.c.scope=="email",export_log.c.owner==user,export_log.c.creation>now-timedelta(hours=1))).scalar()
  if used>limit:
   c.execute(delete(export_log).where(export_log.c.name==slot))
   raise ValidationError(f"You have already sent {used-1} emails in the last hour: the limit is {limit}. Try again later, or ask an administrator to raise it (notify.settings: email.user_hourly_limit).")
 return slot
def _release_email_slot(slot):
 from ..db.system import export_log
 try:
  with db.transaction() as c: c.execute(delete(export_log).where(export_log.c.name==slot))
 except Exception: pass
def install_routes(app:FastAPI,scope,run):
 @app.get("/api/document-flow/{doctype}/{name}/actions")
 def document_flow_actions(doctype:str,name:str,request:Request):
  def fn():
   get_doc(doctype,name)
   provider=_document_flow_provider()
   return provider.get_create_from_actions(doctype,name)
  return run(request,fn)

 @app.get("/api/linked-documents/{doctype}/{name}")
 def linked_documents(doctype:str,name:str,request:Request):
  def fn():
   from .. import linked
   get_doc(doctype,name)
   return linked.preview(doctype,name)
  return run(request,fn)

 @app.post("/api/cancel-all/{doctype}/{name}")
 def cancel_all_documents(doctype:str,name:str,request:Request,body:dict=Body(default={})):
  def fn():
   from .. import linked
   reason=(body or {}).get("reason") if isinstance(body,dict) else None
   return {"cancelled":linked.cancel_all(doctype,name,reason or "No reason supplied")}
  return run(request,fn)

 @app.get("/api/pull-items/{target}/sources")
 def pull_sources(target:str,request:Request):
  def fn():
   method=getattr(_document_flow_provider(),"pull_sources",None)
   return method(target) if callable(method) else []
  return run(request,fn)

 @app.post("/api/pull-items/candidates")
 def pull_candidates(request:Request,body:dict=Body(...)):
  def fn():
   if not isinstance(body,dict): raise ValidationError("Request must be an object")
   method=getattr(_document_flow_provider(),"pull_candidates",None)
   if not callable(method): raise ValidationError("The installed document-flow provider does not support Get Items From")
   return method(body)
  return run(request,fn)

 @app.post("/api/pull-items/lines")
 def pull_items(request:Request,body:dict=Body(...)):
  def fn():
   if not isinstance(body,dict): raise ValidationError("Request must be an object")
   method=getattr(_document_flow_provider(),"pull_items",None)
   if not callable(method): raise ValidationError("The installed document-flow provider does not support Get Items From")
   return method(body)
  return run(request,fn)

 @app.post("/api/settlement/outstanding")
 def settlement_outstanding(request:Request,body:dict=Body(...)):
  def fn():
   if not isinstance(body,dict): raise ValidationError("Request must be an object")
   return _document_flow_provider().settlement_outstanding(body)
  return run(request,fn)
 @app.post("/api/settlement/allocate")
 def settlement_allocate(request:Request,body:dict=Body(...)):
  def fn():
   if not isinstance(body,dict): raise ValidationError("Request must be an object")
   return _document_flow_provider().settlement_allocate(body)
  return run(request,fn)

 @app.post("/api/document-pricing/{doctype}")
 def document_pricing(doctype:str,request:Request,body:dict=Body(...)):
  def fn():
   if not isinstance(body,dict): raise ValidationError("Pricing request must be an object")
   provider=_document_pricing_provider()
   method=getattr(provider,"get_row_prices",None)
   if not callable(method): raise ValidationError("The installed document-pricing provider does not implement get_row_prices")
   return method(doctype,body)
  return run(request,fn)

 @app.post("/api/document-flow/{doctype}/{name}/create")
 def create_from_document(doctype:str,name:str,request:Request,body:dict=Body(...)):
  def fn():
   get_doc(doctype,name)
   target=str(body.get("target_doctype") or "").strip()
   if not target: raise ValidationError("target_doctype is required")
   overrides=body.get("overrides") or {}
   if not isinstance(overrides,dict): raise ValidationError("overrides must be an object")
   provider=_document_flow_provider()
   doc=provider.create_document_from(doctype,name,target,overrides)
   return {"doctype":doc.doctype,"name":doc.name,"docstatus":doc.docstatus,"source_doctype":getattr(doc,"source_doctype",None),"source_document":getattr(doc,"source_document",None)}
  return run(request,fn)
 @app.post("/api/share/{doctype}/{name}")
 def share(doctype:str,name:str,request:Request,body:dict=Body(...)):
  def fn():
   meta=registry.get(doctype); check_permission(meta,"share")
   get_doc(doctype,name)
   email=str(body.get("email") or "").strip().lower()
   if not email or "@" not in email: raise ValidationError("A valid user email is required")
   read=bool(body.get("read",True)); write=bool(body.get("write",False))
   if write: read=True
   now=datetime.now(timezone.utc).replace(tzinfo=None); s=get_session()
   with db.transaction() as c:
    c.execute(delete(doc_share).where(doc_share.c.doctype==doctype,doc_share.c.docname==name,doc_share.c.user_email==email))
    c.execute(insert(doc_share).values(doctype=doctype,docname=name,user_email=email,read=read,write=write,granted_by=s.user,granted_on=now))
   return {"doctype":doctype,"name":name,"email":email,"read":read,"write":write}
  return run(request,fn)
 @app.delete("/api/share/{doctype}/{name}/{email}")
 def unshare(doctype:str,name:str,email:str,request:Request):
  def fn():
   check_permission(registry.get(doctype),"share")
   with db.transaction() as c: c.execute(delete(doc_share).where(doc_share.c.doctype==doctype,doc_share.c.docname==name,doc_share.c.user_email==email.lower()))
   return {"unshared":email}
  return run(request,fn)
 @app.get("/api/share/{doctype}/{name}")
 def shares(doctype:str,name:str,request:Request):
  def fn():
   check_permission(registry.get(doctype),"share")
   with db.transaction() as c: return [dict(r) for r in c.execute(select(doc_share).where(doc_share.c.doctype==doctype,doc_share.c.docname==name)).mappings()]
  return run(request,fn)
 @app.post("/api/email/{doctype}/{name}")
 def email_doc(doctype:str,name:str,request:Request,body:dict=Body(...)):
  def fn():
   meta=registry.get(doctype); check_permission(meta,"email"); get_doc(doctype,name)      # raises unless the caller may also READ this document
   to=str(body.get("recipient") or "").strip(); subject=str(body.get("subject") or f"{doctype}: {name}")
   message=str(body.get("message") or "")
   if not message: message=f"Please find the {doctype} record reference {name}."
   from velora_notify.channels import PermanentError, send_email, valid_email
   if not valid_email(to): raise ValidationError(f"{to!r} is not a valid email address" if to else "Give the address to send to")
   if len(subject)>200 or len(message)>20000: raise ValidationError("The subject (200 characters) or message (20,000 characters) is too long")
   slot=_reserve_email_slot(doctype,name,to)              # anyone with the 'email' permission could otherwise send unlimited mail through the company's mail account
   try: send_email({"recipient":to,"subject":subject,"body":message,"payload":{"doctype":doctype,"name":name}})
   except PermanentError as exc: _release_email_slot(slot); raise ValidationError(str(exc)) from None        # was an opaque HTTP 500: say WHY it could not be sent (not set up, refused address ...)
   except (OSError, __import__("smtplib").SMTPException) as exc: _release_email_slot(slot); raise ValidationError(f"The mail server could not be reached or refused the message: {type(exc).__name__}: {exc}") from None
   except BaseException: _release_email_slot(slot); raise
   return {"sent":True,"recipient":to}
  return run(request,fn)
