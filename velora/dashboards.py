"""Company-local dashboard definitions and safe, permission-aware widget execution."""
from __future__ import annotations
from fastapi import Request
import secrets
import math
import ast
import operator
import re
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, JSON, MetaData, String, Table, insert, select, update, delete, func
from . import db
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import get_session
from .document.document import get_count, get_aggregate, get_group_by, get_table, _conditions
md=MetaData()
dashboard=Table("vl_dashboard",md,Column("id",String(32),primary_key=True),Column("name",String(140),nullable=False,unique=True),Column("description",String(500)),Column("layout",JSON,nullable=False),Column("widgets",JSON,nullable=False),Column("is_public",String(5),nullable=False,default="false"),Column("owner",String(254)),Column("created_on",DateTime),Column("modified_on",DateTime))
def ensure(): from .db import extra_tables; extra_tables.ensure(md)
MAX_WIDGETS=50
def _limit(value,default=12):
 """A widget's row limit, always a whole number from 1 to 100 (a dashboard saved by an older version may hold anything)."""
 try: n=int(value)
 except (TypeError,ValueError): return default
 return max(1,min(n,100))
def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def _admin():
 s=get_session()
 if s.user!="Administrator" and "System Manager" not in s.roles: raise PermissionDenied("Only a System Manager can manage dashboards")
_OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Pow:operator.pow,ast.USub:operator.neg,ast.UAdd:operator.pos}
def _formula(expression, values):
 """Evaluate a small arithmetic DSL; no eval, calls, attributes, or arbitrary Python."""
 try: tree=ast.parse(expression,mode="eval")
 except SyntaxError: raise ValidationError("Invalid metric formula") from None
 def visit(node):
  if isinstance(node,ast.Expression): return visit(node.body)
  if isinstance(node,ast.Name):
   if node.id not in values: raise ValidationError(f"Unknown metric alias {node.id!r}")
   return float(values[node.id] or 0)
  if isinstance(node,ast.Constant) and isinstance(node.value,(int,float)) and not isinstance(node.value,bool): return float(node.value)
  if isinstance(node,ast.BinOp) and type(node.op) in _OPS:
   a,b=visit(node.left),visit(node.right)
   if isinstance(node.op,ast.Pow) and abs(b)>8: raise ValidationError("Formula exponent is too large")
   if isinstance(node.op,ast.Div) and b==0: return 0.0
   result=_OPS[type(node.op)](a,b)
   if not math.isfinite(result): raise ValidationError("Formula produced a non-finite result")
   return result
  if isinstance(node,ast.UnaryOp) and type(node.op) in _OPS: return _OPS[type(node.op)](visit(node.operand))
  raise ValidationError("Formula supports only aliases, numbers and + - * / ** operators")
 return round(float(visit(tree)),6)

def _metric(source):
 dt=source["doctype"]; operation=source["operation"]; filters=source.get("filters")
 if operation=="count": return float(get_count(dt,filters))
 meta=registry.get(dt); field=source.get("field")
 from .permissions import check_permission, field_access
 check_permission(meta,"read")
 f=meta.get_field(field)
 if not f or f.fieldtype not in ("Int","Float","Currency"): raise ValidationError(f"{dt}.{field} must be a readable numeric field")
 if field_access(dt,field)=="hidden": raise PermissionDenied(f"Field {dt}.{field} is hidden")
 t=get_table(dt); col=t.c[field]
 expression={"sum":func.sum,"average":func.avg,"minimum":func.min,"maximum":func.max}[operation](col)
 stmt=select(expression)
 for cond in _conditions(dt,t,set(meta.column_names()),filters,meta): stmt=stmt.where(cond)
 from .permissions import row_policy_sql
 row_scope=row_policy_sql(dt,"read",t)
 if row_scope is not None: stmt=stmt.where(row_scope)
 with db.transaction() as c: value=c.execute(stmt).scalar()
 return float(value or 0)

def _combined_chart(sources, limit):
 combined={}
 for source in sources:
  rows=get_group_by(source["doctype"],source["field"],source.get("filters"),limit)
  key=source.get("key") or source["doctype"]
  for row in rows:
   label=str(row.get("value") if row.get("value") is not None else "(Not set)")
   combined.setdefault(label,{"label":label})[key]=int(row["count"])
 return list(combined.values())[:limit]

def save(payload):
 ensure(); name=str(payload.get("name") or "").strip(); widgets=payload.get("widgets") or []
 if not name or not isinstance(widgets,list): raise ValidationError("Dashboard name and widget list are required")
 if len(name)>140: raise ValidationError("Dashboard name is too long (140 characters at most)")
 if len(widgets)>MAX_WIDGETS: raise ValidationError(f"A dashboard may have at most {MAX_WIDGETS} widgets")
 layout=payload.get("layout") or []
 if not isinstance(layout,list) or len(layout)>MAX_WIDGETS: raise ValidationError("Dashboard layout must be a list of at most 50 positions")
 for item in layout:
  if not isinstance(item,dict) or item.get("span",1) not in (1,2,3,4) or item.get("order",0)<0: raise ValidationError("Invalid dashboard widget layout position")
 for w in widgets:
  if not isinstance(w,dict) or w.get("type") not in ("number","group_by","aggregate","formula"): raise ValidationError("Widget type must be number, group_by, aggregate or formula")
  if w.get("type")=="formula":
   sources=w.get("sources")
   if not isinstance(sources,list) or not sources or len(sources)>12: raise ValidationError("Formula widgets need 1 to 12 metric sources")
   aliases=set()
   for source in sources:
    if not isinstance(source,dict) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}",str(source.get("key") or "")): raise ValidationError("Each formula source needs a valid key")
    if source["key"] in aliases: raise ValidationError("Formula source keys must be unique")
    aliases.add(source["key"])
    if source.get("operation") not in ("count","sum","average","minimum","maximum"): raise ValidationError("Unsupported formula source operation")
    if source["operation"]!="count" and not source.get("field"): raise ValidationError("Numeric formula sources need a field")
    registry.get(source.get("doctype") or "")
   if not isinstance(w.get("formula"),str) or len(w["formula"])>500: raise ValidationError("A formula expression of at most 500 characters is required")
   _formula(w["formula"],{k:0 for k in aliases})
  if w.get("chart_type", "bar") not in ("bar", "line", "pie"): raise ValidationError("Chart type must be bar, line or pie")
  if w.get("type") not in ("formula","group_by") and not w.get("doctype"): raise ValidationError("Every widget needs a DocType")
  if w.get("type")=="group_by" and not w.get("sources") and not w.get("doctype"): raise ValidationError("Single-source charts need a DocType")
  if w["type"]=="group_by" and not w.get("field") and not w.get("sources"): raise ValidationError("Group-by widgets need a field or chart sources")
  if w["type"]=="group_by" and w.get("sources"):
   if not isinstance(w["sources"],list) or not 1<=len(w["sources"])<=8: raise ValidationError("Cross-app charts support 1 to 8 data sources")
   for source in w["sources"]:
    if not isinstance(source,dict) or not source.get("doctype") or not source.get("field"): raise ValidationError("Each chart source needs a DocType and grouping field")
    registry.get(source["doctype"])
  if w["type"]=="aggregate" and not w.get("fields"): raise ValidationError("Aggregate widgets need numeric fields")
  if "limit" in w and not (isinstance(w["limit"],int) and not isinstance(w["limit"],bool) and 1<=w["limit"]<=100): raise ValidationError("A widget's limit must be a whole number from 1 to 100")
  if w["type"]=="aggregate" and (not isinstance(w["fields"],list) or len(w["fields"])>20 or not all(isinstance(f,str) for f in w["fields"])): raise ValidationError("Aggregate fields must be a list of at most 20 field names")
  if w["type"]=="group_by" and not isinstance(w["field"],str): raise ValidationError("A group-by field must be a field name")
  if "target_value" in w and w["target_value"] is not None:
   if isinstance(w["target_value"], bool): raise ValidationError("KPI target must be numeric")
   try: target=float(w["target_value"])
   except (TypeError,ValueError): raise ValidationError("KPI target must be numeric") from None
   if not math.isfinite(target): raise ValidationError("KPI target must be a finite number")
   if w["type"]=="group_by": raise ValidationError("KPI targets are supported on number and aggregate widgets, not group-by charts")
   if w.get("target_direction","at_least") not in ("at_least","at_most"): raise ValidationError("target_direction must be at_least or at_most")
   if w["type"]=="aggregate" and w.get("target_field") not in w.get("fields",[]): raise ValidationError("Aggregate KPI target_field must be one of the widget's aggregate fields")
  if "unit" in w and (not isinstance(w["unit"],str) or len(w["unit"])>24): raise ValidationError("KPI unit must be text of at most 24 characters")
 rid=str(payload.get("id") or secrets.token_hex(16)); now=_now(); s=get_session()
 row=dict(id=rid,name=name,description=str(payload.get("description") or "")[:500],layout=payload.get("layout") or [],widgets=widgets,is_public="true" if payload.get("is_public") else "false",owner=s.user,created_on=now,modified_on=now)
 with db.transaction() as c:
  exists=c.execute(select(dashboard.c.id).where(dashboard.c.id==rid)).first()
  if exists:
   prior=c.execute(select(dashboard.c.owner).where(dashboard.c.id==rid)).scalar()
   if prior != s.user and s.user != "Administrator" and "System Manager" not in s.roles: raise PermissionDenied("Only the dashboard owner or a System Manager can edit this dashboard")
   c.execute(update(dashboard).where(dashboard.c.id==rid).values(**{k:v for k,v in row.items() if k not in ("created_on","owner")}))
  else: c.execute(insert(dashboard).values(**row))
 return row
def listing():
 ensure(); s=get_session()
 with db.transaction() as c: rows=[dict(r) for r in c.execute(select(dashboard).order_by(dashboard.c.name)).mappings()]
 return [r for r in rows if r["owner"]==s.user or r["is_public"]=="true" or s.user=="Administrator" or "System Manager" in s.roles]
def get(rid):
 ensure(); s=get_session()
 with db.transaction() as c: r=c.execute(select(dashboard).where(dashboard.c.id==rid)).mappings().first()
 if not r: raise DoesNotExistError("Dashboard not found")
 r=dict(r)
 if r["owner"]!=s.user and r["is_public"]!="true" and s.user!="Administrator" and "System Manager" not in s.roles: raise PermissionDenied("Dashboard access denied")
 return r
def run(rid):
 from .meta.registry import registry
 d=get(rid); results=[]
 for w in d["widgets"]:
  # Every source resolves through the global metadata registry, so widgets can span installed apps.
  if w["type"]=="formula":
   values={source["key"]:_metric(source) for source in w["sources"]}
   value=_formula(w["formula"],values)
   item={**w,"value":value,"source_values":values}
   if w.get("target_value") is not None:
    actual=float(value); target=float(w["target_value"]); direction=w.get("target_direction","at_least")
    passed=actual>=target if direction=="at_least" else actual<=target
    attainment=(actual/target*100) if target>0 else (100.0 if passed else 0.0)
    item["kpi"]={"actual":actual,"target":target,"direction":direction,"passed":passed,"variance":actual-target,"attainment_percent":round(attainment,2)}
   results.append(item)
   continue
  if w["type"]=="number":
   registry.get(w["doctype"]); value=get_count(w["doctype"],w.get("filters"))
  elif w["type"]=="group_by":
   if w.get("sources"):
    value=_combined_chart(w["sources"],_limit(w.get("limit",12)))
   else:
    registry.get(w["doctype"]); value=get_group_by(w["doctype"],w["field"],w.get("filters"),_limit(w.get("limit",12)))
   results.append({**w,"value":value}); continue
  else:
   registry.get(w["doctype"]); value=get_aggregate(w["doctype"],w["fields"],w.get("filters"))
  item={**w,"value":value}
  if w.get("target_value") is not None:
   actual=float(value if w["type"]=="number" else (value.get(w["target_field"]) or 0))
   target=float(w["target_value"]); direction=w.get("target_direction","at_least")
   passed=actual>=target if direction=="at_least" else actual<=target
   attainment=(actual/target*100) if target>0 else (100.0 if passed else 0.0)
   variance=actual-target
   item["kpi"]={"actual":actual,"target":target,"direction":direction,"passed":passed,
                "variance":variance,"attainment_percent":round(attainment,2)}
  results.append(item)
 return {**d,"results":results}
def duplicate_one(rid, new_name):
 ensure(); source=get(rid)
 name=str(new_name or "").strip()
 if not name: raise ValidationError("A name is required for the duplicated dashboard")
 return save({"name":name,"description":source.get("description"),"layout":source.get("layout") or [],"widgets":source.get("widgets") or [],"is_public":False})
def delete_one(rid):
 ensure(); s=get_session()
 with db.transaction() as c:
  row=c.execute(select(dashboard.c.owner).where(dashboard.c.id==rid)).first()
  if not row: raise DoesNotExistError("Dashboard not found")
  if row[0] != s.user and s.user != "Administrator" and "System Manager" not in s.roles: raise PermissionDenied("Only the dashboard owner or a System Manager can delete this dashboard")
  c.execute(delete(dashboard).where(dashboard.c.id==rid))
 return {"deleted":rid}
def install_routes(app,scope,run_request):
 from fastapi import Body
 @app.get("/api/dashboards")
 def dashboards(request:Request): return run_request(request,listing)
 @app.post("/api/dashboards")
 def dashboard_save(request:Request,body:dict=Body(...)): return run_request(request,lambda:save(body))
 @app.get("/api/dashboards/{rid}")
 def dashboard_get(rid:str,request:Request): return run_request(request,lambda:get(rid))
 @app.get("/api/dashboards/{rid}/run")
 def dashboard_run(rid:str,request:Request): return run_request(request,lambda:run(rid))
 @app.post("/api/dashboards/{rid}/duplicate")
 def dashboard_duplicate(rid:str,request:Request,body:dict=Body(...)): return run_request(request,lambda:duplicate_one(rid,body.get("name")))
 @app.delete("/api/dashboards/{rid}")
 def dashboard_delete(rid:str,request:Request): return run_request(request,lambda:delete_one(rid))
