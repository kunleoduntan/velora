"""Company-local print formats with escaped field interpolation and optional PDF output."""
from __future__ import annotations
from fastapi import Request
import html, re, secrets
from urllib.parse import quote
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, JSON, MetaData, String, Table, insert, select, update
from . import db
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import get_session, check_permission
from .document.document import get_doc
md=MetaData(); formats=Table("vl_print_format",md,Column("id",String(32),primary_key=True),Column("name",String(140),nullable=False),Column("doctype",String(140),nullable=False),Column("template",String,nullable=False),Column("settings",JSON,nullable=False),Column("owner",String(254)),Column("created_on",DateTime),Column("modified_on",DateTime))
def ensure(): from .db import extra_tables; extra_tables.ensure(md)
def _admin():
 s=get_session()
 if s.user!="Administrator" and "System Manager" not in s.roles: raise PermissionDenied("Only a System Manager can manage print formats")
def save(payload):
 ensure(); _admin(); name=str(payload.get("name") or "").strip(); doctype=str(payload.get("doctype") or "").strip(); template=str(payload.get("template") or "")
 if not name or not doctype or not template: raise ValidationError("Print format requires name, DocType and template")
 from .meta.registry import registry
 registry.get(doctype)
 if len(template)>200000: raise ValidationError("Print template is too large")
 rid=str(payload.get("id") or secrets.token_hex(16)); now=datetime.now(timezone.utc).replace(tzinfo=None); s=get_session()
 row=dict(id=rid,name=name,doctype=doctype,template=template,settings=payload.get("settings") or {},owner=s.user,created_on=now,modified_on=now)
 with db.transaction() as c:
  if c.execute(select(formats.c.id).where(formats.c.id==rid)).first(): c.execute(update(formats).where(formats.c.id==rid).values(name=name,doctype=doctype,template=template,settings=row["settings"],modified_on=now))
  else: c.execute(insert(formats).values(**row))
 return row
def listing():
 ensure()
 with db.transaction() as c: return [dict(r) for r in c.execute(select(formats).order_by(formats.c.doctype,formats.c.name)).mappings()]
def formats_for(doctype):
 ensure()
 from .meta.registry import registry
 registry.get(doctype)
 with db.transaction() as c:
  rows=c.execute(select(formats).where(formats.c.doctype==doctype).order_by(formats.c.name)).mappings().all()
 return [dict(r) for r in rows]
def render(rid,doctype,name,nonce=None):
 ensure();
 with db.transaction() as c: fmt=c.execute(select(formats).where(formats.c.id==rid)).mappings().first()
 if not fmt: raise DoesNotExistError("Print format not found")
 if fmt["doctype"]!=doctype: raise ValidationError("Print format does not belong to this DocType")
 doc=get_doc(doctype,name); check_permission(doc.meta,"print")
 values=doc.as_dict()
 def repl(m):
  key=m.group(1).strip()
  if key=="name": val=values.get("name","")
  else: val=values.get(key,"")
  return html.escape("" if val is None else str(val))
 body=re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}",repl,fmt["template"])
 title=html.escape(fmt["name"])
 pdf_link = "/api/print/" + "/".join(quote(str(x), safe="") for x in (rid, doctype, name)) + "/pdf"
 pdf_link = html.escape(pdf_link, quote=True)
 script=(f"<script nonce='{html.escape(nonce,quote=True)}'>document.getElementById('velora-print').addEventListener('click',function(){{window.print()}})</script>" if nonce else "")
 return f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title><style>body{{font:14px Arial;margin:28px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:7px}}.velora-print-actions{{margin-bottom:18px}}@media print{{.velora-print-actions{{display:none}}}}</style></head><body><div class='velora-print-actions'><a href='{pdf_link}'>Open PDF</a> · <button id='velora-print' type='button'>Print</button></div>{body}{script}</body></html>"
def to_pdf(html_doc: str) -> bytes:
 try:
  from reportlab.lib.pagesizes import A4
  from reportlab.lib.styles import getSampleStyleSheet
  from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
  from reportlab.lib.utils import simpleSplit  # noqa: F401  (an availability probe: fail here, early, if reportlab is not installed)
  from reportlab.lib import colors  # noqa: F401
  import io
  # Safe, intentionally simple text PDF fallback: strip markup, preserve paragraphs. HTML preview remains the rich print path.
  text=re.sub(r"<br\s*/?>","\n",html_doc,flags=re.I); text=re.sub(r"</(p|div|h[1-6]|tr)>","\n",text,flags=re.I); text=re.sub(r"<[^>]+>"," ",text); text=html.unescape(text)
  buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4); styles=getSampleStyleSheet(); story=[]
  for line in [x.strip() for x in text.splitlines() if x.strip()]: story.append(Paragraph(html.escape(line),styles["BodyText"])); story.append(Spacer(1,6))
  doc.build(story); return buf.getvalue()
 except ImportError: raise ValidationError("Install the optional PDF dependencies with `pip install velora[pdf]`")
def install_routes(app,scope,run_request):
 from fastapi import Body
 from fastapi.responses import HTMLResponse,Response
 @app.get("/api/print-formats/for/{doctype}")
 def print_formats_for(doctype:str,request:Request): return run_request(request,lambda:formats_for(doctype))
 @app.get("/api/print-formats")
 def print_list(request:Request): return run_request(request,listing)
 @app.post("/api/print-formats")
 def print_save(request:Request,body:dict=Body(...)): return run_request(request,lambda:save(body))
 @app.get("/api/print/{rid}/{doctype}/{name}")
 def print_preview(rid:str,doctype:str,name:str,request:Request):
  nonce=secrets.token_urlsafe(16)
  page=run_request(request,lambda:render(rid,doctype,name,nonce))["data"]
  # A print format is HTML written by an administrator and opened by OTHER people: the browser must not run any script in it. Only Velora's own Print button carries the nonce.
  csp=f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; img-src data: https:; font-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
  return HTMLResponse(page,headers={"Content-Security-Policy":csp,"X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"})
 @app.get("/api/print/{rid}/{doctype}/{name}/pdf")
 def print_pdf(rid:str,doctype:str,name:str,request:Request):
  with scope(request),db.transaction(): data=to_pdf(render(rid,doctype,name))
  safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:100] or "document"
  return Response(data,media_type="application/pdf",headers={"Content-Disposition":f'inline; filename="{safe_name}.pdf"'})
