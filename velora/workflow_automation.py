"""Advanced, company-local workflow configuration and governance extensions."""
from __future__ import annotations
import json, secrets, weakref
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, insert, select, update, UniqueConstraint, inspect
from fastapi import Body, Request
from . import db
from .exceptions import ValidationError, PermissionDenied, DoesNotExistError
from .permissions import get_session

md = MetaData()
_ensured_engines = weakref.WeakSet()
versions = Table('vl_workflow_version', md, Column('id', String(32), primary_key=True), Column('workflow', String(140), nullable=False, index=True), Column('version', Integer, nullable=False), Column('definition', JSON, nullable=False), Column('created_by', String(254)), Column('created_on', DateTime))
instance_versions = Table('vl_workflow_instance_version', md, Column('instance_id', String(32), primary_key=True), Column('version_id', String(32), nullable=False))
delegations = Table('vl_workflow_delegation', md, Column('id', String(32), primary_key=True), Column('delegator', String(254), nullable=False), Column('delegate', String(254), nullable=False), Column('workflow', String(140)), Column('doctype', String(140)), Column('valid_from', DateTime, nullable=False), Column('valid_until', DateTime, nullable=False), Column('active', Integer, nullable=False, default=1), Column('created_by', String(254)))
votes = Table('vl_workflow_vote', md, Column('id', String(32), primary_key=True), Column('instance_id', String(32), nullable=False, index=True), Column('action', String(80), nullable=False), Column('actor', String(254), nullable=False), Column('decision', String(20), nullable=False), Column('comment', Text), Column('created_on', DateTime), Column('round', Integer))
templates = Table('vl_workflow_template', md, Column('name', String(140), primary_key=True), Column('description', Text), Column('definition', JSON, nullable=False), Column('created_by', String(254)), Column('created_on', DateTime))
automations = Table('vl_workflow_automation', md, Column('name', String(140), primary_key=True), Column('event', String(100), nullable=False), Column('doctype', String(140), nullable=False), Column('conditions', JSON, nullable=False), Column('condition_logic', String(8), nullable=False, default='all'), Column('handler', String(255), nullable=False), Column('enabled', Integer, nullable=False, default=1), Column('created_by', String(254)), Column('created_on', DateTime))
sla = Table('vl_workflow_sla', md, Column('instance_id', String(32), primary_key=True), Column('due_on', DateTime), Column('escalation_level', Integer, nullable=False, default=0), Column('last_escalated', DateTime))
sla_policy = Table('vl_workflow_sla_policy', md, Column('instance_id', String(32), primary_key=True),
    Column('levels', JSON, nullable=False), Column('created_by', String(254)), Column('created_on', DateTime))
sla_events = Table('vl_workflow_sla_event', md, Column('id', String(32), primary_key=True),
    Column('instance_id', String(32), nullable=False, index=True), Column('level', Integer, nullable=False),
    Column('handler', String(255), nullable=False), Column('queued_on', DateTime, nullable=False),
    UniqueConstraint('instance_id', 'level', name='uq_workflow_sla_event_level'))


def ensure(engine=None):
    engine=engine or db.get_engine()
    if engine not in _ensured_engines:
        md.create_all(engine)
        _ensured_engines.add(engine)
def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def admin():
    s=get_session()
    if s.user != 'Administrator' and 'System Manager' not in s.roles: raise PermissionDenied('Only a System Manager can administer workflow configuration')
    return s

def snapshot(workflow: str, payload: dict):
    ensure(); s=get_session()
    with db.transaction() as c:
        n=(c.execute(select(versions.c.version).where(versions.c.workflow==workflow).order_by(versions.c.version.desc())).scalar() or 0)+1
        vid=secrets.token_hex(16)
        c.execute(insert(versions).values(id=vid,workflow=workflow,version=n,definition=payload,created_by=s.user,created_on=now()))
    return {'id':vid,'version':n}

def restore_version(workflow: str, version: int):
    """Publish an immutable historical definition as a new current version."""
    ensure(); admin()
    with db.transaction() as c:
        row=c.execute(select(versions.c.definition).where(
            versions.c.workflow==workflow, versions.c.version==int(version))).mappings().first()
    if not row:
        raise DoesNotExistError("Workflow version not found")
    payload=dict(row["definition"] or {})
    if payload.get("name") != workflow:
        raise ValidationError("Stored workflow version does not match its workflow")
    from .workflows import save_definition
    return save_definition(payload)


def attach_instance(instance_id: str, workflow: str):
    ensure()
    with db.transaction() as c:
        v=c.execute(select(versions.c.id).where(versions.c.workflow==workflow).order_by(versions.c.version.desc()).limit(1)).scalar()
        if v and not c.execute(select(instance_versions.c.instance_id).where(instance_versions.c.instance_id==instance_id)).first(): c.execute(insert(instance_versions).values(instance_id=instance_id,version_id=v))

def create_delegation(payload):
    ensure(); s=admin(); delegator=str(payload.get('delegator') or '').strip().lower(); delegate=str(payload.get('delegate') or '').strip().lower()
    if not delegator or not delegate or delegator==delegate: raise ValidationError('Provide different delegator and delegate email addresses')
    start=payload.get('valid_from'); end=payload.get('valid_until')
    try: start=datetime.fromisoformat(start) if isinstance(start,str) else start; end=datetime.fromisoformat(end) if isinstance(end,str) else end
    except Exception: raise ValidationError('Delegation dates must be ISO date/time values') from None
    if not start or not end: raise ValidationError('Delegation requires a valid start and end date')
    if start.tzinfo is not None: start=start.astimezone(timezone.utc).replace(tzinfo=None)
    if end.tzinfo is not None: end=end.astimezone(timezone.utc).replace(tzinfo=None)
    if end<=start: raise ValidationError('Delegation requires a valid start and end date')
    rid=secrets.token_hex(16)
    with db.transaction() as c: c.execute(insert(delegations).values(id=rid,delegator=delegator,delegate=delegate,workflow=payload.get('workflow') or None,doctype=payload.get('doctype') or None,valid_from=start,valid_until=end,active=1,created_by=s.user))
    return {'id':rid,'delegator':delegator,'delegate':delegate,'valid_from':start,'valid_until':end,'active':True}

def list_delegations():
    ensure(); admin()
    with db.transaction() as c: return [dict(x) for x in c.execute(select(delegations).order_by(delegations.c.valid_from.desc())).mappings()]
def revoke_delegation(rid):
    ensure(); admin()
    with db.transaction() as c:
        n=c.execute(update(delegations).where(delegations.c.id==rid).values(active=0)).rowcount
        if not n: raise DoesNotExistError('Delegation not found')
    return {'id':rid,'active':False}

def save_template(payload):
    ensure(); s=admin(); name=str(payload.get('name') or '').strip(); definition=payload.get('definition')
    if not name or not isinstance(definition,dict): raise ValidationError('Template needs a name and workflow definition')
    row={'name':name,'description':str(payload.get('description') or ''),'definition':definition,'created_by':s.user,'created_on':now()}
    with db.transaction() as c:
        if c.execute(select(templates.c.name).where(templates.c.name==name)).first(): c.execute(update(templates).where(templates.c.name==name).values(description=row['description'],definition=definition))
        else: c.execute(insert(templates).values(**row))
    return row
def list_templates():
    ensure(); admin()
    with db.transaction() as c: return [dict(x) for x in c.execute(select(templates).order_by(templates.c.name)).mappings()]
def apply_template(name, workflow_name):
    ensure(); admin()
    with db.transaction() as c: row=c.execute(select(templates).where(templates.c.name==name)).mappings().first()
    if not row: raise DoesNotExistError('Workflow template not found')
    from .workflows import save_definition
    payload=dict(row['definition']); payload['name']=workflow_name
    return save_definition(payload)

def save_automation(payload):
    ensure(); s=admin(); name=str(payload.get('name') or '').strip(); event=str(payload.get('event') or '').strip(); doctype=str(payload.get('doctype') or '').strip(); handler=str(payload.get('handler') or '').strip()
    if not all((name,event,doctype,handler)): raise ValidationError('Automation requires name, event, DocType and registered handler')
    from .meta.registry import registry
    registry.get(doctype)
    if handler not in registry.job_handlers(): raise ValidationError('Automation handler must be declared by an installed app in job_handlers')
    conditions=payload.get('conditions') or []
    if not isinstance(conditions,list): raise ValidationError('Automation conditions must be a list')
    meta=registry.get(doctype); allowed={f.fieldname for f in meta.value_fields}
    for cond in conditions:
        if not isinstance(cond,dict) or cond.get('field') not in allowed or cond.get('operator') not in ('=','!=','>','<','>=','<=','in','not in') or 'value' not in cond:
            raise ValidationError('Each automation condition needs a valid DocType field, supported operator and value')
    if payload.get('condition_logic','all') not in ('all','any'): raise ValidationError('condition_logic must be all or any')
    row={'name':name,'event':event,'doctype':doctype,'conditions':conditions,'condition_logic':payload.get('condition_logic','all'),'handler':handler,'enabled':1,'created_by':s.user,'created_on':now()}
    with db.transaction() as c:
        if c.execute(select(automations.c.name).where(automations.c.name==name)).first(): c.execute(update(automations).where(automations.c.name==name).values(event=event,doctype=doctype,conditions=conditions,condition_logic=payload.get('condition_logic','all'),handler=handler,enabled=1))
        else: c.execute(insert(automations).values(**row))
    return row

def list_automations():
    ensure(); admin()
    with db.transaction() as c: return [dict(x) for x in c.execute(select(automations).order_by(automations.c.name)).mappings()]

def configure_sla(instance_id, minutes, escalation_levels=None):
    ensure(); s=admin()
    from .workflows import get_instance
    get_instance(instance_id)
    try: minutes=int(minutes)
    except Exception: raise ValidationError('SLA minutes must be an integer') from None
    if minutes<1 or minutes>525600: raise ValidationError('SLA must be between 1 minute and 365 days')
    due=now()+timedelta(minutes=minutes)
    levels = escalation_levels or []
    if not isinstance(levels, list): raise ValidationError('escalation_levels must be a list')
    from .jobs import _resolve
    clean=[]
    for item in levels:
        if not isinstance(item, dict): raise ValidationError('Each SLA escalation level must be an object')
        try: after=int(item.get('after_minutes', 0) or 0)
        except (TypeError, ValueError): raise ValidationError('SLA after_minutes must be an integer') from None
        handler=str(item.get('handler') or '').strip()
        if after < 0 or not handler or not isinstance(item.get('payload') or {}, dict):
            raise ValidationError('Each SLA level needs a non-negative after_minutes and an installed-app job handler')
        try: _resolve(handler)
        except Exception: raise ValidationError('SLA handler must be registered by an installed app') from None
        clean.append({'after_minutes':after,'handler':handler,'payload':item.get('payload') or {}})
    clean.sort(key=lambda x:x['after_minutes'])
    if len(clean) > 20: raise ValidationError('An SLA policy can contain at most 20 escalation levels')
    if len({x['after_minutes'] for x in clean}) != len(clean): raise ValidationError('SLA escalation thresholds must be unique')
    with db.transaction() as c:
        if c.execute(select(sla.c.instance_id).where(sla.c.instance_id==instance_id)).first(): c.execute(update(sla).where(sla.c.instance_id==instance_id).values(due_on=due,escalation_level=0,last_escalated=None))
        else: c.execute(insert(sla).values(instance_id=instance_id,due_on=due,escalation_level=0,last_escalated=None))
        if c.execute(select(sla_policy.c.instance_id).where(sla_policy.c.instance_id==instance_id)).first():
            c.execute(update(sla_policy).where(sla_policy.c.instance_id==instance_id).values(levels=clean,created_by=s.user,created_on=now()))
        else:
            c.execute(insert(sla_policy).values(instance_id=instance_id,levels=clean,created_by=s.user,created_on=now()))
    return {'instance_id':instance_id,'due_on':due,'escalation_levels':clean}
def get_sla(instance_id):
    ensure()
    from .workflows import get_instance
    get_instance(instance_id)                       # you must be able to read the document the workflow is about (this raises otherwise)
    with db.transaction() as c:
        r=c.execute(select(sla).where(sla.c.instance_id==instance_id)).mappings().first()
        return dict(r) if r else None

def process_due_slas(limit=100):
    """Queue each overdue escalation exactly once; called by the company-local worker."""
    ensure()
    from .workflows import instance, ensure as ensure_workflows
    from .jobs import enqueue_system_job as enqueue_job
    from sqlalchemy.exc import IntegrityError
    ensure_workflows()
    at=now(); queued=0
    with db.transaction() as c:
        rows=c.execute(select(*sla.c, sla_policy.c.levels).join(sla_policy, sla_policy.c.instance_id==sla.c.instance_id)
            .join(instance, instance.c.id==sla.c.instance_id).where(instance.c.status=='Active', sla.c.due_on<=at)
            .order_by(sla.c.due_on).limit(max(1,min(int(limit),500)))).mappings().all()
    for record in rows:
        for idx, level in enumerate(record['levels'] or []):
            threshold=record['due_on'] + timedelta(minutes=int(level['after_minutes']))
            if threshold > at: continue
            with db.transaction() as c:
                exists=c.execute(select(sla_events.c.id).where(sla_events.c.instance_id==record["instance_id"],
                    sla_events.c.level==idx)).first()
            if exists: continue
            # The durable queue has an idempotency key, so concurrent workers cannot
            # create duplicate escalation work even if both pass the existence check.
            enqueue_job(level['handler'], {'event':'workflow_sla_escalation','instance_id':record["instance_id"],
                'level':idx+1,'payload':level.get('payload') or {}},
                idempotency_key=f'workflow-sla:{record["instance_id"]}:{idx+1}')
            try:
                with db.transaction() as c:
                    exists=c.execute(select(sla_events.c.id).where(sla_events.c.instance_id==record["instance_id"],
                        sla_events.c.level==idx)).first()
                    if not exists:
                        c.execute(insert(sla_events).values(id=secrets.token_hex(16),instance_id=record["instance_id"],
                            level=idx,handler=level['handler'],queued_on=at))
                        c.execute(update(sla).where(sla.c.instance_id==record["instance_id"]).values(
                            escalation_level=idx+1,last_escalated=at))
                        queued += 1
            except IntegrityError:
                # A concurrent company worker already recorded this exact escalation.
                continue
    return {'queued':queued}


def approval_progress(instance_id):
    ensure()
    with db.transaction() as c:
        rows=c.execute(select(votes).where(votes.c.instance_id==instance_id).order_by(votes.c.created_on)).mappings().all()
    return [dict(x) for x in rows]

def dispatch_automations(doc, event: str):
    """Queue matching app-owned automation handlers in this company's durable job queue."""
    from .permissions import _remember
    def load():
        with db.transaction() as c:
            if not inspect(c).has_table('vl_workflow_automation'):
                return []
            return [dict(r) for r in c.execute(select(automations).where(automations.c.doctype==doc.doctype,automations.c.event==event,automations.c.enabled==1)).mappings().all()]
    rows=_remember(("automations",doc.doctype,event),load)            # read once per (DocType, event) inside a bulk import
    from .workflows import _condition_matches
    from .jobs import enqueue_system_job as enqueue_job
    for row in rows:
        checks=[_condition_matches(doc.get(x['field']),x['operator'],x['value']) for x in (row['conditions'] or [])]
        if checks and not (all(checks) if row['condition_logic']=='all' else any(checks)): continue
        stamp=str(doc.get('modified') or doc.get('creation') or '')
        key=f"wfauto:{row['name']}:{doc.doctype}:{doc.name}:{event}:{stamp}"[:180]
        enqueue_job(row['handler'],{'automation':row['name'],'doctype':doc.doctype,'document_name':doc.name,'event':event,'document':json.loads(json.dumps(doc.as_dict(),default=str))},idempotency_key=key)


def install_routes(app, scope, run):
    @app.get('/api/workflow-versions/{workflow}')
    def workflow_versions(workflow: str, request: Request):
        def fn():
            ensure(); admin()
            with db.transaction() as c: return [dict(x) for x in c.execute(select(versions).where(versions.c.workflow==workflow).order_by(versions.c.version.desc())).mappings()]
        return run(request,fn)
    @app.post('/api/workflow-versions/{workflow}/{version}/restore')
    def workflow_version_restore(workflow: str, version: int, request: Request):
        return run(request, lambda: restore_version(workflow, version))
    @app.post('/api/workflow-delegations')
    def delegation_create(request: Request, body: dict=Body(...)): return run(request,lambda:create_delegation(body))
    @app.get('/api/workflow-delegations')
    def delegation_list(request: Request): return run(request,list_delegations)
    @app.post('/api/workflow-delegations/{rid}/revoke')
    def delegation_revoke(rid: str, request: Request): return run(request,lambda:revoke_delegation(rid))
    @app.get('/api/workflow-templates')
    def template_list(request: Request): return run(request,list_templates)
    @app.post('/api/workflow-templates')
    def template_save(request: Request, body: dict=Body(...)): return run(request,lambda:save_template(body))
    @app.post('/api/workflow-templates/{name}/apply')
    def template_apply(name: str, request: Request, body: dict=Body(...)): return run(request,lambda:apply_template(name,str(body.get('workflow_name') or '')))
    @app.get('/api/workflow-automations')
    def automation_list(request: Request): return run(request,list_automations)
    @app.post('/api/workflow-automations')
    def automation_save(request: Request, body: dict=Body(...)): return run(request,lambda:save_automation(body))
    @app.post('/api/workflow-instances/{instance_id}/sla')
    def sla_set(instance_id: str, request: Request, body: dict=Body(...)): return run(request,lambda:configure_sla(instance_id,body.get('minutes'),body.get('escalation_levels')))
    @app.get('/api/workflow-instances/{instance_id}/sla')
    def sla_get(instance_id: str, request: Request):
        def fn():
            from .workflows import get_instance
            get_instance(instance_id)
            return get_sla(instance_id)
        return run(request,fn)
    @app.get('/api/workflow-instances/{instance_id}/approvals')
    def approval_list(instance_id: str, request: Request):
        def fn():
            from .workflows import get_instance
            get_instance(instance_id)
            return approval_progress(instance_id)
        return run(request,fn)
