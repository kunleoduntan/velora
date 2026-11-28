"""Configurable company and personal application workspaces.

Workspace definitions are JSON configuration, not executable code. Business data remains in
its owning DocType engines and every data widget executes through permission-aware document APIs.
"""
from __future__ import annotations
import re, secrets
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, JSON, MetaData, String, Table, select, insert, update, delete
from fastapi import Request, Body
from . import db
from .exceptions import PermissionDenied, ValidationError, DoesNotExistError
from .permissions import get_session, _effective_roles
from .document.document import get_count, get_aggregate, get_group_by

md=MetaData()
workspaces=Table("vl_application_workspace",md,
    Column("id",String(32),primary_key=True), Column("scope",String(16),nullable=False),
    Column("name",String(140),nullable=False), Column("description",String(500)),
    Column("visibility",String(16),nullable=False), Column("roles",JSON,nullable=False),
    Column("owner",String(254)), Column("layout",JSON,nullable=False), Column("is_default",Boolean,nullable=False,default=False,server_default="false"),
    Column("created_on",DateTime), Column("modified_on",DateTime))
def ensure():
    from .db import extra_tables
    extra_tables.ensure(md)
def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def _admin():
    s=get_session()
    if s.user!="Administrator" and "System Manager" not in s.roles:
        raise PermissionDenied("Only a System Manager can publish company workspaces")
def _clean_widget(w):
    if not isinstance(w,dict): raise ValidationError("Every workspace widget must be an object")
    kind=w.get("type")
    width=w.get("width",2)
    if isinstance(width,bool) or not isinstance(width,int) or width not in (1,2,3,4): raise ValidationError("Widget width must be 1, 2, 3 or 4 columns")
    if kind=="shortcut":
        route=w.get("route","")
        if not isinstance(route,str) or not re.fullmatch(r"#/(?:app/[A-Za-z0-9 _.-]+|hr/(?:employee(?:/[A-Za-z0-9 _.-]+)?|leave|governance|performance|team-performance|training|me)|report/[A-Za-z0-9 &'()-]+|applications|dashboards|financial-centre|financial-reports|rules|welcome|settings/company-setup|investments|tax-centre|treasury-centre|people|support|shortcuts|gl-review|budgets|bank-reconciliation|controls-check|portal-access|broadcasts|operational-centre|recruitment|governance(?:/(?:reports|exceptions|automation|sustainability|manual))?)",route):
            raise ValidationError("Shortcut route must be a supported internal Velora route")
        label=str(w.get("title") or "").strip()
        if not label or len(label)>100: raise ValidationError("Shortcut title is required (100 characters maximum)")
        return {"type":"shortcut","title":label,"route":route,"description":str(w.get("description") or "")[:180],"width":width}
    if kind not in ("number","group_by","aggregate","activity"):
        raise ValidationError("Supported workspace widgets are number, group_by, aggregate, activity and shortcut")
    if kind=="activity":
        return {"type":"activity","title":str(w.get("title") or "Recent activity")[:100],"width":width}
    from .meta.registry import registry
    doctype=w.get("doctype")
    if not isinstance(doctype,str) or not doctype: raise ValidationError("Data widgets require a DocType")
    meta=registry.get(doctype)
    if meta.istable: raise ValidationError("Child-table DocTypes cannot be workspace data sources")
    filters=w.get("filters") or {}
    if not isinstance(filters,(dict,list)):
        raise ValidationError("Workspace widget filters must be an object or a list of field filters")
    valid_fields={f.fieldname for f in meta.fields} | {"name","owner","creation","modified","docstatus"}
    filter_rows=([[k,"=",v] for k,v in filters.items()] if isinstance(filters,dict) else filters)
    for flt in filter_rows:
        if not isinstance(flt,(list,tuple)) or len(flt)!=3:
            raise ValidationError("Each workspace filter must contain field, operator and value")
        if not isinstance(flt[0],str) or flt[0] not in valid_fields:
            raise ValidationError(f"Workspace filter field {flt[0]!r} does not exist on {doctype}")
    out={"type":kind,"title":str(w.get("title") or doctype)[:100],"doctype":doctype,"filters":filters,"width":width}
    if kind=="group_by":
        field=w.get("field")
        if not isinstance(field,str) or field not in {f.fieldname for f in meta.fields}: raise ValidationError("Group-by field must exist on the selected DocType")
        raw_limit=w.get("limit",10)
        if isinstance(raw_limit,bool) or not isinstance(raw_limit,int):
            raise ValidationError("Chart widget limit must be a whole number")
        out.update(field=field,limit=max(1,min(raw_limit,30)))
    if kind=="aggregate":
        fields=w.get("fields")
        if not isinstance(fields,list) or not fields or len(fields)>10 or not all(isinstance(f,str) and f in {x.fieldname for x in meta.fields} for f in fields):
            raise ValidationError("Aggregate fields must be existing DocType fields (maximum 10)")
        out["fields"]=fields
    return out
def _normalise(payload,scope):
    if not isinstance(payload,dict): raise ValidationError("Workspace payload must be an object")
    allowed={"id","name","description","visibility","roles","widgets"}
    if set(payload)-allowed: raise ValidationError("Workspace contains unsupported properties")
    name=str(payload.get("name") or "").strip()
    if not name or len(name)>140: raise ValidationError("Workspace name is required (140 characters maximum)")
    visibility=payload.get("visibility","personal" if scope=="personal" else "company")
    if scope=="personal":
        if visibility!="personal": raise ValidationError("Personal workspaces must use personal visibility")
        roles=[]
    else:
        if visibility not in ("company","roles"): raise ValidationError("Company workspace visibility must be company or roles")
        roles=payload.get("roles") or []
        if not isinstance(roles,list) or len(roles)>30 or not all(isinstance(r,str) and 0<len(r)<=80 for r in roles):
            raise ValidationError("Workspace roles must be a list of role names")
        if visibility=="roles" and not roles: raise ValidationError("Select at least one role for a role-visible workspace")
    widgets=payload.get("widgets") or []
    if not isinstance(widgets,list) or len(widgets)>30: raise ValidationError("A workspace may contain at most 30 widgets")
    return {"name":name,"description":str(payload.get("description") or "")[:500],"visibility":visibility,
            "roles":sorted(set(roles)),"layout":[_clean_widget(w) for w in widgets]}
def listing():
    ensure(); s=get_session(); effective_roles=_effective_roles(s)
    with db.transaction() as c: rows=[dict(x) for x in c.execute(select(workspaces).order_by(workspaces.c.name)).mappings()]
    visible=[]
    for r in rows:
        if r["scope"]=="personal" and r["owner"]==s.user: visible.append(r)
        elif r["scope"]=="company" and (r["visibility"]=="company" or
             (r["visibility"]=="roles" and bool(set(r["roles"]) & effective_roles)) or
             s.user=="Administrator" or "System Manager" in s.roles): visible.append(r)
    return visible
def save(payload,scope):
    ensure(); s=get_session()
    if scope not in ("personal","company"): raise ValidationError("Unknown workspace scope")
    if scope=="company": _admin()
    data=_normalise(payload,scope); rid=str(payload.get("id") or secrets.token_hex(16)); now=_now()
    with db.transaction() as c:
        old=c.execute(select(workspaces).where(workspaces.c.id==rid)).mappings().first()
        if old:
            old=dict(old)
            if old["scope"]!=scope or (scope=="personal" and old["owner"]!=s.user):
                raise PermissionDenied("You cannot modify this workspace")
            c.execute(update(workspaces).where(workspaces.c.id==rid).values(**data,modified_on=now))
        else:
            c.execute(insert(workspaces).values(id=rid,scope=scope,owner=s.user if scope=="personal" else None,
                created_on=now,modified_on=now,**data))
    return get(rid)
def set_default(rid):
    ensure(); s=get_session(); row=get(rid)
    if row["scope"]=="company": _admin()
    elif row["owner"]!=s.user: raise PermissionDenied("You cannot set another user's default workspace")
    with db.transaction() as c:
        if row["scope"]=="personal":
            c.execute(update(workspaces).where(workspaces.c.scope=="personal",workspaces.c.owner==s.user).values(is_default=False))
        else:
            c.execute(update(workspaces).where(workspaces.c.scope=="company").values(is_default=False))
        c.execute(update(workspaces).where(workspaces.c.id==rid).values(is_default=True,modified_on=_now()))
    return get(rid)
def landing():
    """Resolve personal default first, then role-visible company default, then company-wide default."""
    s=get_session(); effective_roles=_effective_roles(s); rows=listing()
    personal=next((r for r in rows if r["scope"]=="personal" and r.get("is_default")),None)
    if personal: return execute(personal["id"])
    company=[r for r in rows if r["scope"]=="company" and r.get("is_default")]
    role_match=next((r for r in company if r["visibility"]=="roles" and set(r["roles"]) & effective_roles),None)
    chosen=role_match or next((r for r in company if r["visibility"]=="company"),None)
    return execute(chosen["id"]) if chosen else None
def get(rid):
    rows=listing()
    for r in rows:
        if r["id"]==rid: return r
    # Distinguish forbidden from missing without leaking record contents.
    ensure(); s=get_session()
    with db.transaction() as c: exists=c.execute(select(workspaces.c.id).where(workspaces.c.id==rid)).first()
    if exists: raise PermissionDenied("Workspace access denied")
    raise DoesNotExistError("Workspace not found")
def remove(rid):
    ensure(); s=get_session()
    with db.transaction() as c:
        r=c.execute(select(workspaces).where(workspaces.c.id==rid)).mappings().first()
        if not r: raise DoesNotExistError("Workspace not found")
        r=dict(r)
        if r["scope"]=="company": _admin()
        elif r["owner"]!=s.user: raise PermissionDenied("You cannot delete this workspace")
        c.execute(delete(workspaces).where(workspaces.c.id==rid))
    return {"deleted":rid}
def execute(rid):
    from .meta.registry import registry
    row=get(rid); results=[]
    for w in row["layout"]:
        try:
            if w["type"]=="shortcut": results.append({**w,"value":None})
            elif w["type"]=="activity":
                from .activity import feed
                activity=feed(limit=10,offset=0)
                results.append({**w,"value":activity["items"]})
            elif w["type"]=="number": results.append({**w,"value":get_count(w["doctype"],w.get("filters"))})
            elif w["type"]=="aggregate": results.append({**w,"value":get_aggregate(w["doctype"],w["fields"],w.get("filters"))})
            else: results.append({**w,"value":get_group_by(w["doctype"],w["field"],w.get("filters"),w.get("limit",10))})
        except (PermissionDenied, DoesNotExistError):
            # Keep the shared workspace usable without exposing restricted data or metadata.
            results.append({**w,"value":None,"status":"unavailable","message":"This widget is not available to your role."})
    return {**row,"results":results}
def install_routes(app,run_request):
    @app.get("/api/workspaces")
    def workspace_list(request:Request): return run_request(request,listing)
    @app.post("/api/workspaces/{scope}",status_code=201)
    def workspace_save(scope:str,request:Request,body:dict=Body(...)): return run_request(request,lambda:save(body,scope))
    @app.get("/api/workspaces/landing")
    def workspace_landing(request:Request): return run_request(request,landing)
    @app.post("/api/workspaces/{wid}/default")
    def workspace_default(wid:str,request:Request): return run_request(request,lambda:set_default(wid))
    @app.get("/api/workspaces/{wid}")
    def workspace_get(wid:str,request:Request): return run_request(request,lambda:get(wid))
    @app.get("/api/workspaces/{wid}/run")
    def workspace_run(wid:str,request:Request): return run_request(request,lambda:execute(wid))
    @app.delete("/api/workspaces/{wid}")
    def workspace_delete(wid:str,request:Request): return run_request(request,lambda:remove(wid))
