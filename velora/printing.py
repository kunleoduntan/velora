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
 from . import printing_jinja; printing_jinja.validate(template)
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

STANDARD={"id":"standard","name":"Standard","builtin":True}
def _fmt(v):
 if v is None or v=="": return ""
 if isinstance(v,bool): return "Yes" if v else "No"
 if isinstance(v,float): return f"{v:,.2f}"
 try:
  from decimal import Decimal
  if isinstance(v,Decimal): return f"{v:,.2f}"
 except Exception: pass
 return str(v)
def _standard_body(doctype,name):
 """A readable page for ANY document: header fields, line tables and the approval trail. Used when no designed print format exists."""
 from .meta.registry import registry
 doc=get_doc(doctype,name); check_permission(doc.meta,"print"); values=doc.as_dict(); e=html.escape
 head="".join(f"<tr><th>{e(f.label or f.fieldname)}</th><td>{e(_fmt(values.get(f.fieldname)))}</td></tr>" for f in doc.meta.value_fields if not f.hidden and _fmt(values.get(f.fieldname))!="")
 out=f"<h1>{e(doctype)} {e(name)}</h1><table class='vp-head'><tbody>{head}</tbody></table>"
 for tf in doc.meta.table_fields:
  rows=values.get(tf.fieldname) or []
  if not rows: continue
  cm=registry.get(tf.options); cols=[f for f in cm.value_fields if not f.hidden and f.fieldname not in ("source_line","source_doctype","source_document")]
  shown=[f for f in cols if f.in_list_view] or cols[:8]; shown=[f for f in shown if any(_fmt(r.get(f.fieldname))!="" for r in rows)][:9]
  if not shown: continue
  out+=f"<h2>{e(tf.label or tf.fieldname)}</h2><table><thead><tr>"+"".join(f"<th>{e(f.label or f.fieldname)}</th>" for f in shown)+"</tr></thead><tbody>"+"".join("<tr>"+"".join(f"<td>{e(_fmt(r.get(f.fieldname)))}</td>" for f in shown)+"</tr>" for r in rows)+"</tbody></table>"
 from .signatures import trail
 sig=" · ".join(f"{t['signature']} ({t['action']}) {t['signed_on']}" for t in trail(doctype,name))
 if sig: out+=f"<p class='vp-sig'>{e(sig)}</p>"
 return out
def _body_for(rid,doctype,name):
 """The printable body of one document for a saved format id, or for the built-in standard page."""
 if rid=="standard": return _standard_body(doctype,name)
 return _render_saved(rid,doctype,name)
def choices_for(doctype):
 """Designed formats first (the one marked default leading), then the built-in Standard page, so every document can always be printed."""
 saved=sorted(formats_for(doctype),key=lambda f:0 if (f.get("settings") or {}).get("default") else 1)
 return saved+[dict(STANDARD,doctype=doctype)]
def _page(title,body,nonce=None,pdf_link=""):
 script=(f"<script nonce='{html.escape(nonce,quote=True)}'>document.getElementById('velora-print').addEventListener('click',function(){{window.print()}})</script>" if nonce else "")
 link=("<a href='"+html.escape(pdf_link,quote=True)+"'>Open PDF</a> · ") if pdf_link else ""
 actions="<div class='velora-print-actions'>"+link+"<button id='velora-print' type='button'>Print</button></div>"
 css="body{font:14px Arial;margin:28px}table{border-collapse:collapse;width:100%;margin-bottom:14px}td,th{border:1px solid #ddd;padding:7px;text-align:left}.vp-head th{width:28%;background:#f6f7f9}.vp-doc{page-break-after:always}.vp-doc:last-child{page-break-after:auto}.velora-print-actions{margin-bottom:18px}@media print{.velora-print-actions{display:none}}"
 return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{css}</style></head><body>{actions}{body}{script}</body></html>"
def render_many(rid,doctype,names,nonce=None,pdf_link=""):
 """Print several documents in one go, each starting on its own page; a document the user may not print is listed, not hidden."""
 names=[n for n in dict.fromkeys(str(x) for x in names) if n]
 if not names: raise ValidationError("Select at least one document to print")
 if len(names)>200: raise ValidationError("Print at most 200 documents at a time")
 ensure(); parts=[]; skipped=[]
 for n in names:
  try: parts.append(f"<section class='vp-doc'>{_body_for(rid,doctype,n)}</section>")
  except (PermissionDenied,DoesNotExistError,ValidationError) as ex: skipped.append(f"{n}: {ex}")
 if not parts: raise PermissionDenied("None of the selected documents can be printed: "+"; ".join(skipped[:3]))
 note=("<p style='color:#b3261e'>Not printed: "+html.escape("; ".join(skipped))+"</p>") if skipped else ""
 return _page(f"{doctype} ({len(parts)})",note+"".join(parts),nonce,pdf_link)
def render(rid,doctype,name,nonce=None):
 if rid=="standard":
  ensure(); pdf_link=html.escape("/api/print/standard/"+quote(doctype,safe="")+"/"+quote(str(name),safe="")+"/pdf",quote=True)
  return _page(f"{doctype} {name}",_standard_body(doctype,name),nonce,pdf_link)
 return _render_saved_page(rid,doctype,name,nonce)
def _saved_parts(rid,doctype,name):
 ensure();
 with db.transaction() as c: fmt=c.execute(select(formats).where(formats.c.id==rid)).mappings().first()
 if not fmt: raise DoesNotExistError("Print format not found")
 if fmt["doctype"]!=doctype: raise ValidationError("Print format does not belong to this DocType")
 doc=get_doc(doctype,name); check_permission(doc.meta,"print")
 values=doc.as_dict()
 from .signatures import trail
 values["approval_signatures"]=" · ".join(f"{t['signature']} ({t['action']}) {t['signed_on']}" for t in trail(doctype,name))
 from . import printing_jinja
 party_title=""
 try:
  link=next((f for f in doc.meta.value_fields if f.fieldname=="party" and f.fieldtype=="Link"),None)
  if link and values.get("party"):
   target=get_doc(link.options,values["party"]); party_title=next((str(getattr(target,k)) for k in ("customer_name","supplier_name","full_name","title","name") if getattr(target,k,None)),"")
 except Exception: party_title=""
 return fmt["name"],printing_jinja.render_template(fmt["template"],values,doc.meta,party_title=party_title)
def _render_saved(rid,doctype,name): return _saved_parts(rid,doctype,name)[1]
def _render_saved_page(rid,doctype,name,nonce=None):
 title,body=_saved_parts(rid,doctype,name)
 pdf_link="/api/print/"+"/".join(quote(str(x),safe="") for x in (rid,doctype,name))+"/pdf"
 return _page(title,body,nonce,pdf_link)
def _pdf_blocks(html_doc):
 """Reduce print HTML to headings, paragraphs and tables (rows of cell text) so the PDF keeps the document's tabular layout."""
 from html.parser import HTMLParser
 class P(HTMLParser):
  def __init__(self): super().__init__(convert_charrefs=True); self.blocks=[]; self.text=[]; self.table=None; self.row=None; self.cell=None; self.skip=0; self.kind="p"
  def flush(self):
   t=re.sub(r"[ \t\r\f\v]+"," "," ".join(self.text)).strip(); self.text=[]
   if t: self.blocks.append((self.kind,t)); 
   self.kind="p"
  def handle_starttag(self,tag,a):
   if tag in ("style","script","title","head"): self.skip+=1
   elif tag=="table": self.flush(); self.table=[]
   elif tag=="tr" and self.table is not None: self.row=[]
   elif tag in ("td","th") and self.row is not None: self.cell=[]
   elif tag in ("p","div","section","br","li") and self.cell is None: self.flush()
   elif tag in ("h1","h2","h3","h4") and self.cell is None: self.flush(); self.kind=tag
  def handle_endtag(self,tag):
   if tag in ("style","script","title","head"): self.skip=max(0,self.skip-1)
   elif tag in ("td","th") and self.cell is not None and self.row is not None: self.row.append(re.sub(r"\s+"," "," ".join(self.cell)).strip()); self.cell=None
   elif tag=="tr" and self.row is not None and self.table is not None:
    if any(self.row): self.table.append(self.row)
    self.row=None
   elif tag=="table" and self.table is not None:
    if self.table: self.blocks.append(("table",self.table))
    self.table=None
   elif tag in ("h1","h2","h3","h4","p","div","section","li"): self.flush()
  def handle_data(self,d):
   if self.skip: return
   (self.cell if self.cell is not None else self.text).append(d)
 p=P(); p.feed(html_doc); p.flush(); return p.blocks
def to_pdf(html_doc: str) -> bytes:
 try:
  from reportlab.lib.pagesizes import A4
  from reportlab.lib.styles import getSampleStyleSheet
  from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
  from reportlab.lib import colors
  from reportlab.lib.units import mm
  import io
 except ImportError: raise ValidationError("Install the optional PDF dependencies with `pip install velora[pdf]`")
 buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,leftMargin=14*mm,rightMargin=14*mm,topMargin=14*mm,bottomMargin=14*mm); styles=getSampleStyleSheet(); story=[]
 cell=styles["BodyText"].clone("cell"); cell.fontSize=8; cell.leading=10
 head=styles["BodyText"].clone("head"); head.fontSize=8; head.leading=10; head.fontName="Helvetica-Bold"
 width=A4[0]-28*mm
 for kind,content in _pdf_blocks(html_doc):
  if kind=="table":
   cols=max(len(r) for r in content); rows=[[Paragraph(html.escape(c),head if i==0 else cell) for c in r+[""]*(cols-len(r))] for i,r in enumerate(content)]
   t=Table(rows,colWidths=[width/cols]*cols,repeatRows=1)
   t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#c9ced6")),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eef0f4")),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4)]))
   story.append(t); story.append(Spacer(1,8))
  else:
   style=styles["Heading1"] if kind=="h1" else styles["Heading2"] if kind in ("h2","h3","h4") else styles["BodyText"]
   story.append(Paragraph(html.escape(content),style)); story.append(Spacer(1,4))
 if not story: story.append(Paragraph("(empty document)",styles["BodyText"]))
 doc.build(story); return buf.getvalue()
def install_routes(app,scope,run_request):
 from fastapi import Body
 from fastapi.responses import HTMLResponse,Response
 @app.get("/api/print-formats/for/{doctype}")
 def print_formats_for(doctype:str,request:Request): return run_request(request,lambda:formats_for(doctype))
 @app.get("/api/print-formats/choices/{doctype}")
 def print_choices(doctype:str,request:Request): return run_request(request,lambda:choices_for(doctype))
 @app.get("/api/print-batch/{rid}/{doctype}")
 def print_batch(rid:str,doctype:str,request:Request,names:str=""):
  nonce=secrets.token_urlsafe(16); lst=[n for n in names.split("\n") if n.strip()] if "\n" in names else [n for n in names.split(",") if n.strip()]
  link="/api/print-batch/"+quote(rid,safe="")+"/"+quote(doctype,safe="")+"/pdf?names="+quote(names,safe="")
  page=run_request(request,lambda:render_many(rid,doctype,lst,nonce,link))["data"]
  csp=f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; img-src data: https:; font-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
  return HTMLResponse(page,headers={"Content-Security-Policy":csp,"X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"})
 @app.get("/api/print-batch/{rid}/{doctype}/pdf")
 def print_batch_pdf(rid:str,doctype:str,request:Request,names:str=""):
  lst=[n for n in names.split(",") if n.strip()]
  with scope(request),db.transaction(): data=to_pdf(render_many(rid,doctype,lst))
  return Response(data,media_type="application/pdf",headers={"Content-Disposition":f'inline; filename="{re.sub(r"[^A-Za-z0-9_.-]+","_",doctype)[:60]}-batch.pdf"'})
 @app.get("/api/print-formats")
 def print_list(request:Request): return run_request(request,listing)
 @app.post("/api/print-formats")
 def print_save(request:Request,body:dict=Body(...)): return run_request(request,lambda:save(body))
 @app.get("/api/print/{rid}/{doctype}/{name}")
 def print_preview(rid:str,doctype:str,name:str,request:Request):
  nonce=secrets.token_urlsafe(16)
  page=run_request(request,lambda:render(rid,doctype,name,nonce))["data"]
  co=request.query_params.get("company")
  if co: page=page.replace("/pdf'","/pdf?company="+html.escape(quote(co,safe=""),quote=True)+"'",1)
  # A print format is HTML written by an administrator and opened by OTHER people: the browser must not run any script in it. Only Velora's own Print button carries the nonce.
  csp=f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; img-src data: https:; font-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
  return HTMLResponse(page,headers={"Content-Security-Policy":csp,"X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"})
 @app.get("/api/print/{rid}/{doctype}/{name}/pdf")
 def print_pdf(rid:str,doctype:str,name:str,request:Request):
  with scope(request),db.transaction(): data=to_pdf(render(rid,doctype,name))
  safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:100] or "document"
  return Response(data,media_type="application/pdf",headers={"Content-Disposition":f'inline; filename="{safe_name}.pdf"'})
