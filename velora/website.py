"""Company-local public website page engine. React renders the public experience; commerce
catalogue, pricing, checkout, tax and payments are deliberately supplied by installed apps.
"""
from __future__ import annotations
import json, re, secrets
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, insert, select, update, delete
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse
from . import db, site as site_mod
from .company import CompanyInfo, company_context
from .controlplane.directory import PlaneDirectory
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import get_session
md=MetaData(); page=Table("vl_web_page",md,Column("id",String(32),primary_key=True),Column("slug",String(160),nullable=False,unique=True),Column("title",String(240),nullable=False),Column("summary",String(500)),Column("body",Text,nullable=False),Column("blocks",JSON,nullable=False),Column("published",Integer,nullable=False,default=0),Column("seo",JSON),Column("owner",String(254)),Column("created_on",DateTime),Column("modified_on",DateTime))
def _link_ok(value):
 """A link a page may carry: http(s), mailto, or a path on THIS site. `//evil.example` and `/\\evil.example` start with a slash but browsers treat them as another site; control characters are never legitimate."""
 if any(ord(ch)<32 or ord(ch)==127 for ch in value): return False
 return value.startswith(("https://","http://","mailto:")) or (value.startswith("/") and not value.startswith(("//","/\\")))
def ensure(): from .db import extra_tables; extra_tables.ensure(md)
def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def _admin():
 s=get_session()
 if s.user!="Administrator" and "System Manager" not in s.roles: raise PermissionDenied("Only a System Manager can manage public website pages")
def save(payload):
 ensure(); _admin(); slug=str(payload.get("slug") or "").strip().lower()
 if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",slug): raise ValidationError("Page slug must use lowercase letters, numbers and hyphens")
 title=str(payload.get("title") or "").strip(); body=str(payload.get("body") or "")
 blocks=payload.get("blocks") or []
 if not title or len(body)>500000 or not isinstance(blocks,list): raise ValidationError("A title, valid content and a block list are required")
 for block in blocks:
  if not isinstance(block,dict) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}",str(block.get("type") or "text")):
   raise ValidationError("Website blocks must have a valid type")
  href=str(block.get("href") or "")
  image=str(block.get("image") or "")
  if href and not _link_ok(href):
   raise ValidationError("Website links must be relative, http, https or mailto URLs")
  if image and not (image.startswith("https://") or image.startswith("http://")):
   raise ValidationError("Website images must use http or https URLs")
  items=block.get("items",[])
  if items and (not isinstance(items,list) or len(items)>30):
   raise ValidationError("Website navigation supports at most 30 items")
  for item in items:
   if not isinstance(item,dict): raise ValidationError("Website navigation items must be objects")
   item_href=str(item.get("href") or "")
   if item_href and not _link_ok(item_href):
    raise ValidationError("Navigation links must be relative, http, https or mailto URLs")
  if len(json.dumps(block,ensure_ascii=False))>20000:
   raise ValidationError("A website block is too large")
 seo=payload.get("seo") or {}
 if not isinstance(seo,dict) or len(seo)>12:
  raise ValidationError("SEO settings must be an object with at most 12 fields")
 seo={str(k):str(v)[:500] for k,v in seo.items() if str(k) in ("title","description","keywords","canonical_url","og_image","robots")}
 for field in ("canonical_url","og_image"):
  value=seo.get(field,"")
  if value and not (value.startswith("https://") or value.startswith("http://")):
   raise ValidationError(f"SEO {field} must be an absolute HTTP or HTTPS URL")
 rid=str(payload.get("id") or secrets.token_hex(16)); now=_now(); s=get_session()
 row=dict(id=rid,slug=slug,title=title,summary=str(payload.get("summary") or "")[:500],body=body,blocks=blocks,published=1 if payload.get("published") else 0,seo=seo,owner=s.user,created_on=now,modified_on=now)
 with db.transaction() as c:
  clash=c.execute(select(page.c.id).where(page.c.slug==slug,page.c.id!=rid)).first()
  if clash: raise ValidationError(f"A page with the address /{slug} already exists. Edit that page (send its id) or choose another slug.")      # was a raw database error (HTTP 500)
  existing=c.execute(select(page.c.id).where(page.c.id==rid)).first()
  if existing: c.execute(update(page).where(page.c.id==rid).values(**{k:v for k,v in row.items() if k not in ("created_on","owner")}))
  else: c.execute(insert(page).values(**row))
 return row
def listing():
 ensure(); _admin()
 with db.transaction() as c: return [dict(r) for r in c.execute(select(page).order_by(page.c.title)).mappings()]
def delete_page(rid):
 ensure(); _admin()
 with db.transaction() as c: n=c.execute(delete(page).where(page.c.id==rid)).rowcount
 if not n: raise DoesNotExistError("Page not found")
 return {"deleted":rid}
def public_page(slug):
 ensure()
 with db.transaction() as c: r=c.execute(select(page.c.slug,page.c.title,page.c.summary,page.c.body,page.c.blocks,page.c.seo).where(page.c.slug==slug,page.c.published==1)).mappings().first()
 if not r: raise DoesNotExistError("Page not found")
 return dict(r)
def install_routes(app:FastAPI,scope,run_request,plane=None):
 @app.get("/api/website/pages")
 def pages(request:Request): return run_request(request,listing)
 @app.post("/api/website/pages")
 def page_save(request:Request,body:dict=Body(...)): return run_request(request,lambda:save(body))
 @app.delete("/api/website/pages/{rid}")
 def page_delete(rid:str,request:Request): return run_request(request,lambda:delete_page(rid))
 @app.get("/api/public/pages/{slug}")
 def public_get(slug:str,request:Request):
  try:
   if plane is not None:
    co=plane.registry.company_for_domain(request.headers.get("host"))
    if not co or co.get("status")!="active": raise DoesNotExistError("Public website is not configured for this domain")
    tenant=plane.registry.get_tenant(co["tenant_id"]) or {}
    site=plane.router.site_for(co)
    with site_mod.use(site), company_context(CompanyInfo(co["id"],co["name"],co["tenant_id"],tenant.get("name",""),PlaneDirectory(plane,co["id"]))):
     with db.transaction(): result=public_page(slug)
   else:
    with db.transaction(): result=public_page(slug)
   return {"data":result}
  except DoesNotExistError as e: return JSONResponse(status_code=404,content={"error":"NotFound","message":str(e)})
