"""Company-local workflow tasks, child-process orchestration and event gateways.

All tables use the active company database. No workflow configuration, task, event,
parent/child link or execution state is shared between companies.
"""
from __future__ import annotations
import secrets
from datetime import datetime, timezone
from sqlalchemy import (Column, DateTime, Integer, JSON, MetaData, String, Table, Text,
                        insert, select, update)
from fastapi import Body, Request
from . import db
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import get_session

md = MetaData()
tasks = Table('vl_workflow_task', md,
    Column('id', String(32), primary_key=True), Column('instance_id', String(32), nullable=False, index=True),
    Column('title', String(255), nullable=False), Column('description', Text),
    Column('assignee', String(254), nullable=False, index=True), Column('status', String(24), nullable=False, default='Open'),
    Column('due_on', DateTime), Column('created_by', String(254)), Column('created_on', DateTime),
    Column('completed_by', String(254)), Column('completed_on', DateTime), Column('result', JSON))
children = Table('vl_workflow_child', md,
    Column('id', String(32), primary_key=True), Column('parent_instance_id', String(32), nullable=False, index=True),
    Column('child_instance_id', String(32), nullable=False, unique=True, index=True),
    Column('resume_state', String(80), nullable=False), Column('resume_status', String(30), nullable=False, default='Active'),
    Column('created_by', String(254)), Column('created_on', DateTime), Column('completed_on', DateTime))
event_subscriptions = Table('vl_workflow_event_subscription', md,
    Column('id', String(32), primary_key=True), Column('instance_id', String(32), nullable=False, index=True),
    Column('event_name', String(140), nullable=False, index=True), Column('filters', JSON, nullable=False, default=dict),
    Column('action', String(80), nullable=False), Column('active', Integer, nullable=False, default=1),
    Column('created_by', String(254)), Column('created_on', DateTime))
events = Table('vl_workflow_event', md,
    Column('id', String(32), primary_key=True), Column('event_name', String(140), nullable=False),
    Column('payload', JSON, nullable=False), Column('published_by', String(254)), Column('published_on', DateTime),
    Column('matched_count', Integer, nullable=False, default=0))


def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def ensure(): from .db import extra_tables; extra_tables.ensure(md)
def _admin():
    s=get_session()
    if s.user != 'Administrator' and 'System Manager' not in s.roles:
        raise PermissionDenied('Only a System Manager can administer workflow orchestration')
    return s


def create_task(instance_id: str, title: str, assignee: str, description: str = '', due_on=None):
    ensure(); s=get_session(); title=str(title or '').strip(); assignee=str(assignee or '').strip().lower()
    if not title or not assignee: raise ValidationError('Task title and assignee are required')
    from .workflows import get_instance
    inst=get_instance(instance_id)
    from .meta.registry import registry
    from .permissions import check_permission
    check_permission(registry.get(inst['doctype']), 'write')
    due = datetime.fromisoformat(due_on) if isinstance(due_on, str) and due_on else due_on
    rid=secrets.token_hex(16); at=_now()
    with db.transaction() as c:
        c.execute(insert(tasks).values(id=rid,instance_id=instance_id,title=title,description=str(description or ''),
            assignee=assignee,status='Open',due_on=due,created_by=s.user,created_on=at))
    return {'id':rid,'instance_id':instance_id,'title':title,'assignee':assignee,'status':'Open','due_on':due}


def list_tasks(status=None, limit=100):
    ensure(); s=get_session(); limit=max(1,min(int(limit),250))
    stmt=select(tasks).where(tasks.c.assignee==s.user.lower())
    if status: stmt=stmt.where(tasks.c.status==status)
    with db.transaction() as c: return [dict(x) for x in c.execute(stmt.order_by(tasks.c.created_on.desc()).limit(limit)).mappings()]


def complete_task(task_id, result=None):
    ensure(); s=get_session()
    with db.transaction() as c:
        row=c.execute(select(tasks).where(tasks.c.id==task_id)).mappings().first()
        if not row: raise DoesNotExistError('Workflow task not found')
        if row['assignee'] != s.user.lower() and s.user != 'Administrator' and 'System Manager' not in s.roles:
            raise PermissionDenied('Only the assigned user or a System Manager can complete this task')
        if row['status'] != 'Open': raise ValidationError('Task is no longer open')
        c.execute(update(tasks).where(tasks.c.id==task_id, tasks.c.status=='Open').values(
            status='Completed',completed_by=s.user,completed_on=_now(),result=result or {}))
    return {'id':task_id,'status':'Completed'}


def start_child(parent_instance_id: str, child_workflow: str, resume_state: str, document_name=None):
    """Start a child workflow on the same company-local document and suspend its parent. Administrators only: when the child completes, the parent JUMPS to `resume_state` without any
    of its own approvals, so anyone who could choose that state could approve a request by launching a one-step child they finish themselves."""
    ensure(); s=_admin()
    from .workflows import instance, definition, start
    parent = None
    with db.transaction() as c:
        parent=c.execute(select(instance).where(instance.c.id==parent_instance_id)).mappings().first()
        if not parent: raise DoesNotExistError('Parent workflow instance not found')
        if parent['status'] != 'Active': raise ValidationError('Parent workflow must be active before starting a child')
        parent_def=c.execute(select(definition).where(definition.c.name==parent['workflow'])).mappings().first()
        try:
            from .workflow_automation import instance_versions, versions
            version_id=c.execute(select(instance_versions.c.version_id).where(instance_versions.c.instance_id==parent_instance_id)).scalar()
            frozen=c.execute(select(versions.c.definition).where(versions.c.id==version_id)).scalar() if version_id else None
            if frozen: parent_def={**dict(parent_def), **frozen}
        except Exception:
            pass
        if not parent_def or resume_state not in {x.get('name') for x in (parent_def.get('states') or [])}:
            raise ValidationError('resume_state must be a state defined by the parent workflow')
        resume_status='Completed' if any(x.get('name')==resume_state and x.get('is_final') for x in (parent_def.get('states') or [])) else 'Active'
        child_def=c.execute(select(definition).where(definition.c.name==child_workflow,definition.c.enabled==1)).mappings().first()
        if not child_def: raise DoesNotExistError('Enabled child workflow not found')
        if child_def['doctype'] != parent['doctype']:
            raise ValidationError('Child workflow must target the same DocType as its parent in this release')
        if c.execute(select(children.c.id).where(children.c.parent_instance_id==parent_instance_id,
                children.c.completed_on.is_(None))).first():
            raise ValidationError('Parent already has an unfinished child workflow')
    child_id = start(child_workflow, parent['doctype'], document_name or parent['document_name'])['id']
    at=_now(); link_id=secrets.token_hex(16)
    with db.transaction() as c:
        c.execute(insert(children).values(id=link_id,parent_instance_id=parent_instance_id,child_instance_id=child_id,
            resume_state=resume_state,resume_status=resume_status,created_by=s.user,created_on=at))
        c.execute(update(instance).where(instance.c.id==parent_instance_id,instance.c.status=='Active').values(
            status='Waiting',modified_on=at,version=parent['version']+1))
    return {'parent_instance_id':parent_instance_id,'child_instance_id':child_id,'parent_status':'Waiting'}


def complete_child_links(child_instance_id: str):
    """Resume waiting parents after a child reaches Completed; safe to call repeatedly."""
    ensure(); resumed=[]
    from .workflows import instance
    with db.transaction() as c:
        child=c.execute(select(instance.c.status).where(instance.c.id==child_instance_id)).scalar()
        if child != 'Completed': return resumed
        links=c.execute(select(children).where(children.c.child_instance_id==child_instance_id,
            children.c.completed_on.is_(None))).mappings().all()
        for link in links:
            parent=c.execute(select(instance).where(instance.c.id==link['parent_instance_id'])).mappings().first()
            if not parent or parent['status']!='Waiting': continue
            at=_now(); from .workflows import log
            c.execute(update(instance).where(instance.c.id==parent['id'],instance.c.status=='Waiting').values(
                state=link['resume_state'],status=link['resume_status'],modified_on=at,version=parent['version']+1))
            c.execute(update(children).where(children.c.id==link['id'],children.c.completed_on.is_(None)).values(completed_on=at))
            c.execute(insert(log).values(id=secrets.token_hex(16),instance_id=parent['id'],from_state=parent['state'],
                to_state=link['resume_state'],action='ChildWorkflowCompleted',actor='Workflow Engine',
                comment=f'Child workflow {child_instance_id} completed; parent resumed',created_on=at))
            resumed.append(parent['id'])
    for parent_id in resumed:
        try:
            from .workflows import definition, instance
            with db.transaction() as c:
                parent=c.execute(select(instance).where(instance.c.id==parent_id)).mappings().first()
                wf=c.execute(select(definition).where(definition.c.name==parent['workflow'])).mappings().first() if parent else None
                if parent and wf:
                    try:
                        from .workflow_automation import instance_versions, versions
                        version_id=c.execute(select(instance_versions.c.version_id).where(instance_versions.c.instance_id==parent_id)).scalar()
                        frozen=c.execute(select(versions.c.definition).where(versions.c.id==version_id)).scalar() if version_id else None
                        if frozen: wf={**dict(wf), **frozen}
                    except Exception:
                        pass
            if parent and wf and wf.get('state_field'):
                from .document.document import get_doc
                doc=get_doc(parent['doctype'],parent['document_name']); doc.set(wf['state_field'],parent['state'])
                from .workflows import engine_write
                with engine_write(): doc.save(ignore_permissions=True)
        except Exception:
            pass
    return resumed


def subscribe_event(instance_id: str, event_name: str, action: str, filters=None):
    ensure(); s=get_session(); event_name=str(event_name or '').strip(); action=str(action or '').strip()
    if not event_name or not action: raise ValidationError('Event name and workflow action are required')
    from .workflows import get_instance
    inst=get_instance(instance_id)
    if inst['status']!='Active': raise ValidationError('Only active workflow instances can subscribe to events')
    if not any(x['action']==action for x in inst.get('available_actions',[])):
        raise ValidationError('The event action is not available from the current workflow state')
    rid=secrets.token_hex(16)
    with db.transaction() as c: c.execute(insert(event_subscriptions).values(id=rid,instance_id=instance_id,
        event_name=event_name,filters=filters or {},action=action,active=1,created_by=s.user,created_on=_now()))
    return {'id':rid,'instance_id':instance_id,'event_name':event_name,'action':action,'active':True}


def publish_event(event_name: str, payload=None):
    """Record an external event and return eligible subscriptions for explicit processing.

    Approval actions are not executed as a privileged system user. The matching subscriptions
    are surfaced for a trusted app handler or an assigned user to process under normal ACLs.
    """
    ensure(); s=get_session(); name=str(event_name or '').strip()
    if not name: raise ValidationError('Event name is required')
    data=payload or {}
    if not isinstance(data,dict): raise ValidationError('Event payload must be an object')
    rid=secrets.token_hex(16); at=_now(); matches=[]
    with db.transaction() as c:
        c.execute(insert(events).values(id=rid,event_name=name,payload=data,published_by=s.user,published_on=at,matched_count=0))
        subs=c.execute(select(event_subscriptions).where(event_subscriptions.c.event_name==name,event_subscriptions.c.active==1)).mappings().all()
        for sub in subs:
            filters=sub['filters'] or {}
            if all(data.get(k)==v for k,v in filters.items()):
                matches.append({'subscription_id':sub['id'],'instance_id':sub['instance_id'],'action':sub['action']})
        c.execute(update(events).where(events.c.id==rid).values(matched_count=len(matches)))
    processed=[]
    from .workflows import act
    for match in matches:
        try:
            result=act(match['instance_id'],match['action'],comment=f'External event: {name}')
            processed.append({'subscription_id':match['subscription_id'],'status':'processed','workflow_status':result.get('status')})
        except (PermissionDenied, ValidationError) as exc:
            processed.append({'subscription_id':match['subscription_id'],'status':'pending','reason':str(exc)})
        except Exception:
            processed.append({'subscription_id':match['subscription_id'],'status':'pending','reason':'The workflow action could not be processed'})
    return {'event_id':rid,'event_name':name,'matched_subscriptions':matches,'matched_count':len(matches),'processed':processed}


def install_routes(app, run):
    @app.post('/api/workflow-instances/{instance_id}/children')
    def child_start(instance_id: str, request: Request, body: dict=Body(...)):
        return run(request,lambda:start_child(instance_id,str(body.get('workflow') or ''),str(body.get('resume_state') or ''),body.get('document_name')))
    @app.get('/api/workflow-tasks')
    def task_list(request: Request, status: str|None=None, limit: int=100): return run(request,lambda:list_tasks(status,limit))
    @app.post('/api/workflow-instances/{instance_id}/tasks')
    def task_create(instance_id: str, request: Request, body: dict=Body(...)):
        return run(request,lambda:create_task(instance_id,body.get('title'),body.get('assignee'),body.get('description',''),body.get('due_on')))
    @app.post('/api/workflow-tasks/{task_id}/complete')
    def task_done(task_id: str, request: Request, body: dict=Body(default={})): return run(request,lambda:complete_task(task_id,body.get('result')))
    @app.post('/api/workflow-instances/{instance_id}/event-subscriptions')
    def event_subscribe(instance_id: str, request: Request, body: dict=Body(...)):
        return run(request,lambda:subscribe_event(instance_id,body.get('event_name'),body.get('action'),body.get('filters')))
    @app.post('/api/workflow-events/{event_name}/publish')
    def event_publish(event_name: str, request: Request, body: dict=Body(default={})): return run(request,lambda:publish_event(event_name,body.get('payload') or {}))
