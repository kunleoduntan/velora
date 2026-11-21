"""Unified, company-local policy governance overlay.

The engine is deliberately additive: existing RBAC, field permissions and row
policies remain the baseline. Published policy bindings can only further
restrict access; they never grant privileges that the underlying permission
engine has not granted.
"""
from __future__ import annotations
from datetime import datetime, timezone
import secrets
from fastapi import Body, Request
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, select, insert, update, delete
from . import db
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import get_session

md = MetaData()
bindings = Table(
    "vl_policy_binding", md,
    Column("name", String(140), primary_key=True),
    Column("title", String(180), nullable=False),
    Column("target_type", String(20), nullable=False),  # action, field, record
    Column("doctype", String(140), nullable=False),
    Column("target", String(140), nullable=False),      # action/field name; "*" for record
    Column("rule_name", String(140), nullable=False),
    Column("effect", String(10), nullable=False, default="deny"),
    Column("status", String(20), nullable=False, default="draft"),
    Column("version", Integer, nullable=False, default=1),
    Column("created_by", String(254)), Column("created_on", DateTime),
    Column("modified_by", String(254)), Column("modified_on", DateTime),
)
audit = Table(
    "vl_policy_audit", md,
    Column("id", String(36), primary_key=True),
    Column("policy_name", String(140), nullable=False, index=True),
    Column("event", String(40), nullable=False),
    Column("actor", String(254), nullable=False),
    Column("details", JSON, nullable=False, default=dict),
    Column("created_on", DateTime, nullable=False),
)
versions = Table(
    "vl_rule_version", md,
    Column("id", String(36), primary_key=True),
    Column("rule_name", String(140), nullable=False, index=True),
    Column("version", Integer, nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("actor", String(254), nullable=False),
    Column("created_on", DateTime, nullable=False),
)

def ensure():
    from .db.extra_tables import ensure as ensure_tables
    ensure_tables(md)

def _admin():
    s = get_session()
    if s.user != "Administrator" and "System Manager" not in s.roles:
        raise PermissionDenied("Only a System Manager can govern enterprise policies")
    return s

def _audit(conn, name, event, actor, details=None):
    conn.execute(insert(audit).values(id=secrets.token_hex(16), policy_name=name, event=event,
        actor=actor, details=details or {}, created_on=datetime.now(timezone.utc).replace(tzinfo=None)))

def save_binding(payload):
    ensure(); s = _admin()
    if not isinstance(payload, dict): raise ValidationError("Policy must be an object")
    name = str(payload.get("name") or "").strip()
    title = str(payload.get("title") or name).strip()
    target_type = payload.get("target_type")
    doctype = str(payload.get("doctype") or "").strip()
    target = str(payload.get("target") or "*").strip()
    rule_name = str(payload.get("rule_name") or "").strip()
    effect = payload.get("effect", "deny")
    if not name or len(name)>140 or not title or len(title)>180: raise ValidationError("Policy name and title are required")
    if target_type not in ("action", "field", "record"): raise ValidationError("Policy target_type must be action, field or record")
    if not doctype or len(doctype)>140: raise ValidationError("Policy requires a DocType")
    if effect != "deny": raise ValidationError("Governance policies currently support restrictive deny effects only")
    from .meta.registry import registry
    meta = registry.get(doctype)
    if target_type == "field" and target not in {f.fieldname for f in meta.value_fields}:
        raise ValidationError(f"Unknown field {doctype}.{target}")
    if target_type == "action" and target not in {"read","write","create","delete","submit","cancel","share","export","print","email"}:
        raise ValidationError("Unsupported action policy target")
    from .rules import get_rule
    rule = get_rule(rule_name)
    if not rule["enabled"]: raise ValidationError("Policy rule must be enabled")
    if rule["scope"] == "doctype" and rule["doctype"] != doctype: raise ValidationError("Rule DocType scope does not match policy")
    status = payload.get("status", "draft")
    if status not in ("draft","pending_approval","approved","published","rejected","retired"):
        raise ValidationError("Invalid policy lifecycle status")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with db.transaction() as conn:
        old = conn.execute(select(bindings).where(bindings.c.name==name)).mappings().first()
        if old:
            if old["status"] == "published" and status == "published":
                status = "draft"  # edits are never live without a new approval
            version = int(old["version"])+1
            conn.execute(update(bindings).where(bindings.c.name==name).values(
                title=title,target_type=target_type,doctype=doctype,target=target,rule_name=rule_name,
                effect=effect,status=status,version=version,modified_by=s.user,modified_on=now))
            event="updated"
        else:
            version=1
            conn.execute(insert(bindings).values(name=name,title=title,target_type=target_type,doctype=doctype,
                target=target,rule_name=rule_name,effect=effect,status=status,version=version,
                created_by=s.user,created_on=now,modified_by=s.user,modified_on=now))
            event="created"
        _audit(conn,name,event,s.user,{"version":version,"status":status})
    return get_binding(name)

def get_binding(name):
    ensure()
    with db.transaction() as conn: row=conn.execute(select(bindings).where(bindings.c.name==name)).mappings().first()
    if not row: raise DoesNotExistError(f"Policy {name!r} does not exist")
    return dict(row)

def list_bindings(doctype=None):
    ensure(); stmt=select(bindings).order_by(bindings.c.name)
    if doctype: stmt=stmt.where(bindings.c.doctype==doctype)
    with db.transaction() as conn: return [dict(x) for x in conn.execute(stmt).mappings()]

def transition(name, action):
    ensure(); s=_admin()
    allowed={"submit":("draft","pending_approval"),"approve":("pending_approval","approved"),
             "publish":("approved","published"),"reject":("pending_approval","rejected"),
             "retire":("published","retired")}
    if action not in allowed: raise ValidationError("Unsupported lifecycle action")
    current=get_binding(name); before,after=allowed[action]
    if current["status"] != before: raise ValidationError(f"Cannot {action} a policy in {current['status']} state")
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with db.transaction() as conn:
        conn.execute(update(bindings).where(bindings.c.name==name).values(status=after,modified_by=s.user,modified_on=now))
        _audit(conn,name,action,s.user,{"from":before,"to":after,"version":current["version"]})
    return get_binding(name)

def delete_binding(name):
    ensure(); s=_admin(); current=get_binding(name)
    if current["status"]=="published": raise ValidationError("Retire a published policy before deleting it")
    with db.transaction() as conn:
        conn.execute(delete(bindings).where(bindings.c.name==name)); _audit(conn,name,"deleted",s.user,{})
    return {"deleted":name}

def evaluate(doctype, target_type, target, document, context=None):
    """Return True when a published deny policy matches. Errors fail closed."""
    ensure()
    s=get_session()
    if s.user=="Administrator": return False
    stmt=select(bindings).where(bindings.c.doctype==doctype,bindings.c.target_type==target_type,
        bindings.c.status=="published")
    if target_type=="record": stmt=stmt.where(bindings.c.target.in_(["*","read","write","create","delete"]))
    else: stmt=stmt.where(bindings.c.target==target)
    with db.transaction() as conn: rows=[dict(r) for r in conn.execute(stmt).mappings()]
    from .rules import evaluate_saved_rule
    ctx={"user":s.user,"roles":list(s.roles),"doctype":doctype,**(context or {})}
    for row in rows:
        try:
            result=evaluate_saved_rule(row["rule_name"],document or {},ctx)
            if result["matched"]:
                with db.transaction() as conn: _audit(conn,row["name"],"decision_denied",s.user,{"target_type":target_type,"target":target})
                return True
        except Exception as exc:
            # A published but invalid/missing rule must not silently permit the action.
            with db.transaction() as conn: _audit(conn,row["name"],"evaluation_error",s.user,{"error":type(exc).__name__})
            return True
    return False

def simulate(payload):
    _admin()
    if not isinstance(payload,dict): raise ValidationError("Simulation payload must be an object")
    doctype=str(payload.get("doctype") or "")
    from .meta.registry import registry
    registry.get(doctype)
    target_type=payload.get("target_type"); target=str(payload.get("target") or "*")
    if target_type not in ("action","field","record"): raise ValidationError("Invalid target_type")
    # Simulation evaluates definitions without writing policy decisions or document data.
    rows=[r for r in list_bindings(doctype) if r["target_type"]==target_type and r["target"] in (target,"*") and r["status"]=="published"]
    from .rules import evaluate_saved_rule
    doc=payload.get("document") or {}; ctx=payload.get("context") or {}
    outcomes=[]
    for row in rows:
        try: matched=evaluate_saved_rule(row["rule_name"],doc,ctx)["matched"]; error=None
        except Exception as exc: matched=True; error=type(exc).__name__
        outcomes.append({"policy":row["name"],"rule":row["rule_name"],"matched":bool(matched),"would_deny":bool(matched),"error":error})
    return {"doctype":doctype,"target_type":target_type,"target":target,"denied":any(x["would_deny"] for x in outcomes),"outcomes":outcomes}

def audit_history(name, limit=100):
    _admin(); ensure()
    with db.transaction() as conn:
        rows=conn.execute(select(audit).where(audit.c.policy_name==name).order_by(audit.c.created_on.desc()).limit(max(1,min(int(limit),500)))).mappings()
        return [dict(x) for x in rows]

def snapshot_rule(conn, rule_row, actor):
    """Append immutable version snapshot; callers pass a complete current rule row."""
    ensure()
    import json
    snapshot = json.loads(json.dumps(dict(rule_row), default=lambda value: value.isoformat() if hasattr(value, "isoformat") else str(value)))
    conn.execute(insert(versions).values(id=secrets.token_hex(16),rule_name=rule_row["name"],
        version=rule_row["version"],snapshot=snapshot,actor=actor,
        created_on=datetime.now(timezone.utc).replace(tzinfo=None)))

def rule_versions(name):
    _admin(); ensure()
    with db.transaction() as conn:
        return [dict(x) for x in conn.execute(select(versions).where(versions.c.rule_name==name).order_by(versions.c.version.desc())).mappings()]

def restore_rule(name, version):
    s=_admin()
    from .rules import save_rule
    ensure()
    with db.transaction() as conn:
        row=conn.execute(select(versions).where(versions.c.rule_name==name,versions.c.version==int(version))).mappings().first()
    if not row: raise DoesNotExistError(f"Rule version {name} v{version} does not exist")
    snapshot=dict(row["snapshot"])
    payload={k:snapshot[k] for k in ("name","title","description","scope","doctype","definition","enabled")}
    payload["enabled"] = bool(payload["enabled"])
    restored=save_rule(payload)
    with db.transaction() as conn: _audit(conn,name,"rule_restored",s.user,{"source_version":int(version),"new_version":restored["version"]})
    return restored

def install_routes(app, scope, run):
    @app.get("/api/policies")
    def policies(request: Request, doctype: str|None=None):
        return run(request, lambda: (_admin() and list_bindings(doctype)))
    @app.post("/api/policies")
    def policy_save(request: Request, body: dict=Body(...)):
        return run(request, lambda: save_binding(body))
    @app.get("/api/policies/{name}")
    def policy_get(name: str, request: Request):
        return run(request, lambda: (_admin() and get_binding(name)))
    @app.post("/api/policies/{name}/{action}")
    def policy_transition(name: str, action: str, request: Request):
        return run(request, lambda: transition(name,action))
    @app.delete("/api/policies/{name}")
    def policy_delete(name: str, request: Request):
        return run(request, lambda: delete_binding(name))
    @app.post("/api/policies/simulate")
    def policy_simulate(request: Request, body: dict=Body(...)):
        return run(request, lambda: simulate(body))
    @app.get("/api/policies/{name}/audit")
    def policy_audit(name: str, request: Request):
        return run(request, lambda: (_admin() and audit_history(name)))
    @app.get("/api/rules/{name}/versions")
    def rule_history(name: str, request: Request):
        return run(request, lambda: rule_versions(name))
    @app.post("/api/rules/{name}/restore/{version}")
    def rule_restore(name: str, version: int, request: Request):
        return run(request, lambda: restore_rule(name,version))
