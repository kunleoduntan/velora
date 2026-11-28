"""Enterprise settings governance engine.

Settings are typed data, not executable code. All records are company-database
local; a legal entity is isolated by the framework's database-per-entity model.
Published values are immutable snapshots with effective dates and maker-checker
approval. Scope fallback is explicit per catalogue definition.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import secrets
from sqlalchemy import (Column, Date, DateTime, Integer, JSON, MetaData, String,
                        Table, Text, insert, select, update)
from fastapi import Body, Request

from . import db
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import get_session

md = MetaData()
catalogue = Table(
    "vl_setting_catalogue", md,
    Column("name", String(140), primary_key=True),
    Column("title", String(180), nullable=False),
    Column("description", Text),
    Column("domain", String(80), nullable=False, index=True),
    Column("value_type", String(24), nullable=False),
    Column("allowed_scopes", JSON, nullable=False),
    Column("fallback_scopes", JSON, nullable=False, default=list),
    Column("default_value", JSON),
    Column("required", Integer, nullable=False, default=0),
    Column("risk", String(20), nullable=False, default="normal"),
    Column("secret", Integer, nullable=False, default=0),
    Column("active", Integer, nullable=False, default=1),
    Column("created_by", String(254)), Column("created_on", DateTime),
)
changes = Table(
    "vl_setting_change", md,
    Column("name", String(36), primary_key=True),
    Column("setting", String(140), nullable=False, index=True),
    Column("scope_type", String(24), nullable=False),
    Column("scope_key", String(180), nullable=False, default=""),
    Column("value", JSON),
    Column("reason", Text, nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("status", String(24), nullable=False, default="draft", index=True),
    Column("version", Integer, nullable=False, default=1),
    Column("maker", String(254), nullable=False),
    Column("approver", String(254)),
    Column("secondary_approver", String(254)),
    Column("created_on", DateTime, nullable=False),
    Column("approved_on", DateTime), Column("published_on", DateTime),
)
versions = Table(
    "vl_setting_version", md,
    Column("id", String(36), primary_key=True),
    Column("setting", String(140), nullable=False, index=True),
    Column("scope_type", String(24), nullable=False),
    Column("scope_key", String(180), nullable=False, default=""),
    Column("version", Integer, nullable=False),
    Column("value", JSON),
    Column("effective_from", Date, nullable=False),
    Column("change_request", String(36), nullable=False),
    Column("actor", String(254), nullable=False),
    Column("published_on", DateTime, nullable=False),
)
audit = Table(
    "vl_setting_audit", md,
    Column("id", String(36), primary_key=True),
    Column("setting", String(140), nullable=False, index=True),
    Column("change_request", String(36)),
    Column("event", String(40), nullable=False),
    Column("actor", String(254), nullable=False),
    Column("details", JSON, nullable=False),
    Column("created_on", DateTime, nullable=False),
)

_SCOPES = {"legal_entity", "branch", "module", "role", "user"}
_TYPES = {"string", "integer", "decimal", "boolean", "date", "json", "secret_ref"}
_RISKS = {"normal", "elevated", "high", "critical"}
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{1,139}$")


def ensure():
    from .db.extra_tables import ensure as ensure_tables
    ensure_tables(md)


def _admin():
    s = get_session()
    if s.user != "Administrator" and "System Manager" not in s.roles:
        raise PermissionDenied("Only a System Manager can administer enterprise settings")
    return s


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(conn, setting, request_id, event, actor, details=None):
    conn.execute(insert(audit).values(id=secrets.token_hex(16), setting=setting,
        change_request=request_id, event=event, actor=actor,
        details=details or {}, created_on=_now()))


def _fingerprint(value):
    encoded=json.dumps(value,sort_keys=True,default=lambda x:x.isoformat() if hasattr(x,"isoformat") else str(x),separators=(",",":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _json_safe(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        raise ValidationError("Setting values must be valid JSON data")


def _validate_value(definition, value):
    typ = definition["value_type"]
    if definition["secret"] or typ == "secret_ref":
        if not isinstance(value, str) or not value.startswith("secret://"):
            raise ValidationError("Secret settings must contain a secret:// reference, never a credential")
        if len(value) > 500:
            raise ValidationError("Secret reference is too long")
        return value
    if value is None:
        if definition["required"]:
            raise ValidationError(f"{definition['title']} is required")
        return None
    if typ == "string" and not isinstance(value, str):
        raise ValidationError("Setting value must be text")
    if typ == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValidationError("Setting value must be an integer")
    if typ == "decimal":
        if isinstance(value, bool): raise ValidationError("Setting value must be numeric")
        try: value = str(Decimal(str(value)))
        except (InvalidOperation, ValueError): raise ValidationError("Setting value must be a valid decimal")
    if typ == "boolean" and not isinstance(value, bool):
        raise ValidationError("Setting value must be true or false")
    if typ == "date":
        try: value = date.fromisoformat(value).isoformat()
        except (TypeError, ValueError): raise ValidationError("Setting value must be an ISO date (YYYY-MM-DD)")
    if typ == "json": value = _json_safe(value)
    return value


def register_definition(payload):
    """Register/update a setting contract. Published values are unaffected."""
    s = _admin(); ensure()
    if not isinstance(payload, dict): raise ValidationError("Setting definition must be an object")
    name = str(payload.get("name") or "").strip()
    title = str(payload.get("title") or "").strip()
    domain = str(payload.get("domain") or "").strip()
    typ = payload.get("value_type")
    scopes = payload.get("allowed_scopes")
    fallback = payload.get("fallback_scopes", [])
    risk = payload.get("risk", "normal")
    if not _NAME.fullmatch(name) or not title or len(title)>180: raise ValidationError("A valid setting name and title are required")
    if not domain or len(domain)>80: raise ValidationError("Setting domain is required")
    if typ not in _TYPES: raise ValidationError("Unsupported setting value_type")
    if not isinstance(scopes, list) or not scopes or any(x not in _SCOPES for x in scopes): raise ValidationError("allowed_scopes must contain supported scopes")
    if not isinstance(fallback, list) or any(x not in scopes or x != "legal_entity" for x in fallback): raise ValidationError("Only explicit legal_entity fallback is currently supported")
    if risk not in _RISKS: raise ValidationError("Invalid setting risk classification")
    secret = bool(payload.get("secret", False)) or typ == "secret_ref"
    if secret and typ not in ("secret_ref", "string"): raise ValidationError("Secret settings must use secret_ref or string type")
    default = payload.get("default_value")
    definition = {"value_type":typ,"required":bool(payload.get("required",False)),"secret":secret,"title":title}
    if "default_value" in payload: default = _validate_value(definition, default)
    now = _now()
    values = dict(name=name,title=title,description=str(payload.get("description") or ""),domain=domain,
        value_type=typ,allowed_scopes=scopes,fallback_scopes=fallback,default_value=default,
        required=int(bool(payload.get("required",False))),risk=risk,secret=int(secret),
        active=int(bool(payload.get("active",True))))
    with db.transaction() as conn:
        old=conn.execute(select(catalogue).where(catalogue.c.name==name)).mappings().first()
        if old:
            structural=(old["value_type"]!=typ or old["secret"]!=int(secret) or
                list(old["allowed_scopes"] or [])!=list(scopes) or list(old["fallback_scopes"] or [])!=list(fallback))
            has_history=conn.execute(select(versions.c.id).where(versions.c.setting==name).limit(1)).first()
            if structural and has_history:
                raise ValidationError("A setting with published history cannot change its type, secret mode or scope contract; create a new setting key and migrate explicitly")
            risk_rank={"normal":0,"elevated":1,"high":2,"critical":3}
            if has_history and risk_rank[risk] < risk_rank[old["risk"]]:
                raise ValidationError("A setting with published history cannot have its risk classification downgraded")
            conn.execute(update(catalogue).where(catalogue.c.name==name).values(**values))
            event="definition_updated"
        else:
            values.update(created_by=s.user,created_on=now)
            conn.execute(insert(catalogue).values(**values)); event="definition_created"
        _audit(conn,name,None,event,s.user,{"domain":domain,"risk":risk,"allowed_scopes":scopes})
    return get_definition(name)


def get_definition(name):
    ensure()
    with db.transaction() as conn: row=conn.execute(select(catalogue).where(catalogue.c.name==name)).mappings().first()
    if not row: raise DoesNotExistError(f"Setting definition {name!r} does not exist")
    return dict(row)


def list_definitions(domain=None):
    _admin(); ensure(); stmt=select(catalogue).where(catalogue.c.active==1).order_by(catalogue.c.domain,catalogue.c.name)
    if domain: stmt=stmt.where(catalogue.c.domain==domain)
    with db.transaction() as conn: return [dict(x) for x in conn.execute(stmt).mappings()]


def create_change(payload):
    s=_admin(); ensure()
    if not isinstance(payload,dict): raise ValidationError("Change request must be an object")
    setting=str(payload.get("setting") or "").strip(); scope_type=payload.get("scope_type")
    scope_key=str(payload.get("scope_key") or "").strip(); reason=str(payload.get("reason") or "").strip()
    try: effective=date.fromisoformat(str(payload.get("effective_from") or date.today().isoformat()))
    except ValueError: raise ValidationError("effective_from must be YYYY-MM-DD")
    definition=get_definition(setting)
    if not definition["active"]: raise ValidationError("Inactive settings cannot be changed")
    if scope_type not in definition["allowed_scopes"]: raise ValidationError(f"Scope {scope_type!r} is not permitted for {setting}")
    if scope_type == "legal_entity" and scope_key not in ("", "current"):
        raise ValidationError("A legal-entity setting is stored in the active entity database; scope_key must be empty")
    if scope_type != "legal_entity" and not scope_key: raise ValidationError("A scope key is required for branch, module, role or user settings")
    if not reason: raise ValidationError("A business reason is mandatory for every settings change")
    value=_validate_value(definition,payload.get("value"))
    if definition["risk"] in ("high","critical") and effective < date.today():
        raise ValidationError("High-risk settings cannot be backdated; choose today or a future effective date")
    request_id=secrets.token_hex(18); now=_now()
    with db.transaction() as conn:
        conn.execute(insert(changes).values(name=request_id,setting=setting,scope_type=scope_type,
            scope_key=scope_key,value=value,reason=reason,effective_from=effective,status="draft",version=1,
            maker=s.user,created_on=now))
        _audit(conn,setting,request_id,"change_created",s.user,{"scope_type":scope_type,"scope_key":scope_key,"effective_from":effective.isoformat()})
    return get_change(request_id)


def get_change(name):
    ensure()
    with db.transaction() as conn: row=conn.execute(select(changes).where(changes.c.name==name)).mappings().first()
    if not row: raise DoesNotExistError(f"Settings change {name!r} does not exist")
    return dict(row)


def list_changes(status=None, setting=None, limit=100):
    _admin(); ensure(); stmt=select(changes).order_by(changes.c.created_on.desc()).limit(max(1,min(int(limit),500)))
    if status: stmt=stmt.where(changes.c.status==status)
    if setting: stmt=stmt.where(changes.c.setting==setting)
    with db.transaction() as conn: return [dict(x) for x in conn.execute(stmt).mappings()]


def transition_change(name, action):
    s=_admin(); ensure(); row=get_change(name)
    transitions={"submit":("draft","pending_approval"),"approve":("pending_approval","approved"),
                 "reject":("pending_approval","rejected"),"publish":("approved","published"),"withdraw":("draft","withdrawn")}
    if action not in transitions: raise ValidationError("Unsupported settings change action")
    before,after=transitions[action]
    if row["status"]!=before: raise ValidationError(f"Cannot {action} a change in {row['status']} state")
    definition=get_definition(row["setting"])
    if action=="approve" and row["approver"]==s.user:
        raise PermissionDenied("An approver cannot approve the same change twice")
    # Critical settings require two independent approvers in addition to the maker.
    critical_first = action=="approve" and definition["risk"]=="critical" and not row["approver"]
    now=_now()
    with db.transaction() as conn:
        conn.execute(update(changes).where(changes.c.name==name).values(
            status="pending_approval" if critical_first else after,
            approver=s.user if action=="approve" and not row["approver"] else row["approver"],
            secondary_approver=s.user if action=="approve" and row["approver"] else row.get("secondary_approver"),
            approved_on=now if action=="approve" and not critical_first else row["approved_on"],
            published_on=now if action=="publish" else row["published_on"]))
        audit_details={"from":before,"to":"pending_approval" if critical_first else after,"reason":row["reason"]}
        if action=="publish":
            # Version numbers are monotonic within a setting + scope. Published history is append-only.
            latest=conn.execute(select(versions).where(versions.c.setting==row["setting"],
                versions.c.scope_type==row["scope_type"],versions.c.scope_key==row["scope_key"])
                .order_by(versions.c.version.desc()).limit(1)).mappings().first()
            version=(int(latest["version"])+1) if latest else 1
            definition=get_definition(row["setting"])
            audit_details.update({"published_version":version,"previous_fingerprint":_fingerprint(latest["value"] if latest else None),
                "new_fingerprint":_fingerprint(row["value"]),"effective_from":row["effective_from"].isoformat(),
                "risk":definition["risk"]})
            if not definition["secret"]:
                audit_details.update({"previous_value":latest["value"] if latest else None,"new_value":row["value"]})
            conn.execute(insert(versions).values(id=secrets.token_hex(18),setting=row["setting"],
                scope_type=row["scope_type"],scope_key=row["scope_key"],version=version,value=row["value"],
                effective_from=row["effective_from"],change_request=name,actor=s.user,published_on=now))
        audit_event="approval_recorded" if critical_first else action
        _audit(conn,row["setting"],name,audit_event,s.user,audit_details)
    return get_change(name)


def get_effective(setting, scope_type="legal_entity", scope_key="", on_date=None):
    """Resolve only exact scope plus explicitly declared fallback scopes."""
    ensure(); definition=get_definition(setting)
    if scope_type not in definition["allowed_scopes"]: raise ValidationError("Requested scope is not permitted")
    as_of=date.fromisoformat(on_date) if isinstance(on_date,str) else (on_date or date.today())
    scopes=[(scope_type,scope_key)]
    for fallback in definition["fallback_scopes"]:
        scopes.append((fallback,"" if fallback=="legal_entity" else scope_key))
    with db.transaction() as conn:
        for st,sk in scopes:
            row=conn.execute(select(versions).where(versions.c.setting==setting,
                versions.c.scope_type==st,versions.c.scope_key==sk,versions.c.effective_from<=as_of)
                .order_by(versions.c.effective_from.desc(),versions.c.version.desc()).limit(1)).mappings().first()
            if row:
                return {"setting":setting,"value":row["value"],"scope_type":st,"scope_key":sk,
                    "version":row["version"],"effective_from":row["effective_from"].isoformat(),
                    "change_request":row["change_request"],"source":"published"}
    if definition["default_value"] is not None:
        return {"setting":setting,"value":definition["default_value"],"scope_type":"package",
            "scope_key":"","version":0,"effective_from":None,"change_request":None,"source":"catalogue_default"}
    if definition["required"]: raise ValidationError(f"Required setting {setting!r} has no effective published value")
    return {"setting":setting,"value":None,"scope_type":None,"scope_key":None,"version":None,
            "effective_from":None,"change_request":None,"source":"unset"}


def versions_for(setting, scope_type=None, scope_key=None):
    _admin(); ensure(); stmt=select(versions).where(versions.c.setting==setting).order_by(versions.c.version.desc())
    if scope_type: stmt=stmt.where(versions.c.scope_type==scope_type)
    if scope_key is not None: stmt=stmt.where(versions.c.scope_key==scope_key)
    with db.transaction() as conn: return [dict(x) for x in conn.execute(stmt).mappings()]


def audit_history(setting, limit=100):
    _admin(); ensure()
    with db.transaction() as conn:
        return [dict(x) for x in conn.execute(select(audit).where(audit.c.setting==setting)
            .order_by(audit.c.created_on.desc()).limit(max(1,min(int(limit),500)))).mappings()]


def export_package(settings=None):
    """Export effective-date schedules for controlled promotion; secrets are references only."""
    _admin(); ensure(); selected=set(settings or [])
    stmt=select(versions).order_by(versions.c.setting,versions.c.scope_type,versions.c.version)
    if selected: stmt=stmt.where(versions.c.setting.in_(selected))
    with db.transaction() as conn: all_rows=[dict(x) for x in conn.execute(stmt).mappings()]
    # Preserve the latest published value for every effective-date boundary,
    # while excluding superseded versions at the same boundary.
    selected_rows={}
    for row in all_rows:
        key=(row["setting"],row["scope_type"],row["scope_key"],row["effective_from"])
        if key not in selected_rows or int(row["version"])>int(selected_rows[key]["version"]):
            selected_rows[key]=row
    rows=list(selected_rows.values())
    payload={"format":"velora-settings-package-v1","created_on":_now().isoformat(),"settings":rows}
    canonical=json.dumps(payload,sort_keys=True,default=lambda x:x.isoformat() if hasattr(x,"isoformat") else str(x),separators=(",",":"))
    return {"package":payload,"sha256":hashlib.sha256(canonical.encode()).hexdigest()}



def import_package(payload):
    """Verify a settings package and stage its latest values per effective date.

    Import never approves or publishes configuration. Each target entity must
    independently validate, approve and publish its own changes.
    """
    s=_admin(); ensure()
    if not isinstance(payload,dict) or not isinstance(payload.get("package"),dict):
        raise ValidationError("A settings package and SHA-256 checksum are required")
    package=payload["package"]
    if package.get("format")!="velora-settings-package-v1" or not isinstance(package.get("settings"),list):
        raise ValidationError("Unsupported settings package format")
    canonical=json.dumps(package,sort_keys=True,default=lambda x:x.isoformat() if hasattr(x,"isoformat") else str(x),separators=(",",":"))
    actual=hashlib.sha256(canonical.encode()).hexdigest()
    if not secrets.compare_digest(actual,str(payload.get("sha256") or "")):
        raise ValidationError("Settings package checksum mismatch; package may have been altered")
    latest={}
    for row in package["settings"]:
        if not isinstance(row,dict): raise ValidationError("Invalid settings package entry")
        key=(row.get("setting"),row.get("scope_type"),row.get("scope_key",""),row.get("effective_from"))
        if key not in latest or int(row.get("version",0))>int(latest[key].get("version",0)):
            latest[key]=row
    staged=[]
    for (setting,scope_type,scope_key,_effective_date),row in latest.items():
        staged.append(create_change({"setting":setting,"scope_type":scope_type,"scope_key":scope_key,
            "value":row.get("value"),"reason":f"Imported from verified settings package {package.get('created_on','')}",
            "effective_from":row["effective_from"].isoformat() if hasattr(row.get("effective_from"),"isoformat") else str(row.get("effective_from"))}))
    return {"verified":True,"staged_count":len(staged),"change_requests":staged}

def install_routes(app, scope, run):
    @app.get("/api/settings/catalogue")
    def setting_catalogue(request: Request, domain: str|None=None):
        return run(request, lambda: list_definitions(domain))
    @app.post("/api/settings/catalogue")
    def setting_register(request: Request, body: dict=Body(...)):
        return run(request, lambda: register_definition(body))
    @app.post("/api/settings/changes")
    def setting_change_create(request: Request, body: dict=Body(...)):
        return run(request, lambda: create_change(body))
    @app.get("/api/settings/changes")
    def setting_change_list(request: Request, status: str|None=None, setting: str|None=None, limit: int=100):
        return run(request, lambda: list_changes(status,setting,limit))
    @app.post("/api/settings/changes/{name}/{action}")
    def setting_change_transition(name: str, action: str, request: Request):
        return run(request, lambda: transition_change(name,action))
    @app.get("/api/settings/{setting}/effective")
    def setting_effective(setting: str, request: Request, scope_type: str="legal_entity", scope_key: str="", on_date: str|None=None):
        return run(request, lambda: (_admin() and get_effective(setting,scope_type,scope_key,on_date)))
    @app.get("/api/settings/{setting}/versions")
    def setting_versions(setting: str, request: Request, scope_type: str|None=None, scope_key: str|None=None):
        return run(request, lambda: versions_for(setting,scope_type,scope_key))
    @app.get("/api/settings/{setting}/audit")
    def setting_audit(setting: str, request: Request, limit: int=100):
        return run(request, lambda: audit_history(setting,limit))
    @app.get("/api/settings/package/export")
    def setting_package_export(request: Request, setting: list[str]|None=None):
        return run(request, lambda: (_admin() and export_package(setting)))
    @app.post("/api/settings/package/import")
    def setting_package_import(request: Request, body: dict=Body(...)):
        return run(request, lambda: import_package(body))
