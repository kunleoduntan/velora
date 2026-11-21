"""Company-local configurable approval workflows.

Definitions, running instances and approval history live in the active company database.
A workflow is deliberately separate from document submit/cancel: applications define the
states and role-gated transitions, while this engine enforces them consistently.
"""
from __future__ import annotations
from fastapi import Body, Request

import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, insert, select, update, func

from . import db
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import get_session

md = MetaData()
definition = Table("vl_workflow_definition", md,
    Column("name", String(140), primary_key=True), Column("doctype", String(140), nullable=False, index=True),
    Column("initial_state", String(80), nullable=False), Column("states", JSON, nullable=False),
    Column("transitions", JSON, nullable=False), Column("state_field", String(140)),
    Column("enabled", Integer, nullable=False, default=1), Column("created_by", String(254)), Column("created_on", DateTime))
instance = Table("vl_workflow_instance", md,
    Column("id", String(32), primary_key=True), Column("workflow", String(140), nullable=False),
    Column("doctype", String(140), nullable=False), Column("document_name", String(255), nullable=False),
    Column("state", String(80), nullable=False), Column("status", String(30), nullable=False, default="Active"),
    Column("started_by", String(254)), Column("started_on", DateTime), Column("modified_on", DateTime),
    Column("version", Integer, nullable=False, default=1))
log = Table("vl_workflow_log", md,
    Column("id", String(32), primary_key=True), Column("instance_id", String(32), nullable=False, index=True),
    Column("from_state", String(80)), Column("to_state", String(80), nullable=False),
    Column("action", String(80), nullable=False), Column("actor", String(254)), Column("comment", Text), Column("created_on", DateTime))


def ensure():
    from .db import extra_tables; extra_tables.ensure(md)


# Fields that an enabled workflow owns can only be changed by the engine itself. Without this a
# user with plain write access could type "Approved" into the form and bypass every approval step.
_engine_write: ContextVar[bool] = ContextVar("velora_workflow_engine_write", default=False)


@contextmanager
def engine_write():
    token = _engine_write.set(True)
    try: yield
    finally: _engine_write.reset(token)


def managed_state_fields(doctype: str) -> set[str]:
    """State fields owned by an enabled workflow for this DocType (empty when none is configured or settings do not require approval)."""
    if policy(doctype) is False: return set()
    try:
        ensure()
        with db.transaction() as c:
            rows = c.execute(select(definition.c.state_field).where(
                definition.c.doctype == doctype, definition.c.enabled == 1, definition.c.state_field.isnot(None))).all()
        return {r[0] for r in rows if r[0]}
    except Exception:
        return set()


def guard_submit(doc) -> None:
    """Block submission until the document reaches a workflow state flagged `allows_submit` (no flagged state = no gate)."""
    wanted = policy(doc.doctype)
    if wanted is False: return
    try:
        ensure()
        with db.transaction() as c:
            rows = c.execute(select(definition.c.state_field, definition.c.states).where(
                definition.c.doctype == doc.doctype, definition.c.enabled == 1, definition.c.state_field.isnot(None))).all()
    except Exception:
        return
    # A document type with no active workflow has no approval step: nothing waits, nothing blocks.
    for field, states in rows:
        allowed = {x.get("name") for x in (states or []) if isinstance(x, dict) and x.get("allows_submit")}
        if allowed and str(getattr(doc, field, None) or "") not in allowed:
            raise ValidationError(f"{doc.doctype} cannot be submitted until its approval workflow reaches {' or '.join(sorted(allowed))}.")


def guard_state_change(doc) -> None:
    """Reject a direct edit of a workflow-managed field; the engine and system code are exempt."""
    if _engine_write.get() or getattr(doc, "_old", None) is None:
        return
    fields = managed_state_fields(doc.doctype)
    for f in fields:
        if str(doc._old.get(f) or "") != str(getattr(doc, f, None) or ""):
            raise ValidationError(f"{f.replace('_', ' ').title()} is controlled by this document's approval workflow and cannot be edited directly. Use the workflow actions.")


def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)


def save_definition(payload: dict, *, system: bool = False) -> dict:
    """Create or replace a workflow definition. `system=True` is for app code acting on a settings change (the caller has its own permission)."""
    ensure()
    name = str(payload.get("name") or "").strip()
    doctype = str(payload.get("doctype") or "").strip()
    states = payload.get("states") or []
    transitions = payload.get("transitions") or []
    initial = str(payload.get("initial_state") or "").strip()
    if not name or not doctype or not isinstance(states, list) or not states or not isinstance(transitions, list):
        raise ValidationError("Workflow needs a name, DocType, states and transitions")
    s = get_session()
    if not system and s.user != "Administrator" and "System Manager" not in s.roles:
        raise PermissionDenied("Only a System Manager can configure workflows")
    from .meta.registry import registry
    meta = registry.get(doctype)
    if not all(isinstance(x, dict) for x in states):
        raise ValidationError("Every workflow state must be an object")
    state_names = {str(x.get("name", "")).strip() for x in states}
    if "" in state_names or len(state_names) != len(states) or initial not in state_names:
        raise ValidationError("Workflow state names must be non-empty, unique, and include the initial state")
    for state in states:
        for coord in ("x", "y"):
            if coord in state:
                try: value = int(state[coord])
                except (TypeError, ValueError): raise ValidationError(f"State layout {coord} must be an integer") from None
                if value < 0 or value > 10000:
                    raise ValidationError(f"State layout {coord} must be between 0 and 10000")
        if "is_final" in state and not isinstance(state["is_final"], bool):
            raise ValidationError("State is_final must be a boolean")
        if "allows_submit" in state and not isinstance(state["allows_submit"], bool):
            raise ValidationError("State allows_submit must be a boolean")
        if "locks_content" in state and not isinstance(state["locks_content"], bool):
            raise ValidationError("State locks_content must be a boolean")
    for tr in transitions:
        if not isinstance(tr, dict) or not tr.get("action") or tr.get("from_state") not in state_names or tr.get("to_state") not in state_names:
            raise ValidationError("Every transition needs an action and valid from/to states")
        roles = tr.get("roles", [])
        users = tr.get("users", [])
        if not isinstance(roles, list) or not all(isinstance(x, str) and x.strip() for x in roles):
            raise ValidationError("Transition roles must be a list of role names")
        if not isinstance(users, list) or not all(isinstance(x, str) and x.strip() for x in users):
            raise ValidationError("Transition users must be a list of email addresses")
        for flag in ("anyone", "prevent_self_approval"):
            if flag in tr and not isinstance(tr[flag], bool): raise ValidationError(f"Transition {flag} must be true or false")
        if not roles and not users and not tr.get("parallel_steps") and not tr.get("anyone"):
            raise ValidationError(f"Transition {tr.get('action')!r} must say who may perform it: give roles or users (or set \"anyone\": true to allow every user who can read the document)")
        rule_name = str(tr.get("rule") or "").strip()
        if rule_name:
            from .rules import get_rule
            saved_rule = get_rule(rule_name)
            if not saved_rule["enabled"]:
                raise ValidationError(f"Workflow rule {rule_name!r} is disabled")
            if saved_rule["scope"] == "doctype" and saved_rule["doctype"] != doctype:
                raise ValidationError(f"Workflow rule {rule_name!r} is scoped to another DocType")
        condition = tr.get("condition")
        conditions = tr.get("conditions") or ([condition] if condition else [])
        if not isinstance(conditions, list): raise ValidationError("Transition conditions must be a list")
        if tr.get("condition_logic", "all") not in ("all", "any"): raise ValidationError("condition_logic must be all or any")
        for cond in conditions:
            if not isinstance(cond, dict) or cond.get("field") not in {f.fieldname for f in meta.value_fields}:
                raise ValidationError("Transition condition must reference a DocType field")
            if cond.get("operator") not in ("=", "!=", ">", "<", ">=", "<=", "in", "not in"):
                raise ValidationError("Unsupported workflow condition operator")
            if "value" not in cond: raise ValidationError("Workflow condition requires a value")
        if tr.get("approval_mode", "single") not in ("single", "all", "any", "quorum"):
            raise ValidationError("approval_mode must be single, all, any or quorum")
        _validate_transition_jobs(tr.get("activities"))
        parallel = tr.get("parallel_steps") or []
        if not isinstance(parallel, list):
            raise ValidationError("parallel_steps must be a list")
        keys = set()
        for branch in parallel:
            if not isinstance(branch, dict) or not str(branch.get("key") or "").strip() or not str(branch.get("label") or "").strip():
                raise ValidationError("Each parallel branch needs a key and label")
            if branch["key"] in keys:
                raise ValidationError("Parallel branch keys must be unique")
            keys.add(branch["key"])
            if branch.get("approval_mode", "single") not in ("single", "any", "all", "quorum"):
                raise ValidationError("Invalid parallel branch approval mode")
            if not isinstance(branch.get("roles", []), list) or not all(isinstance(x, str) and x.strip() for x in branch.get("roles", [])):
                raise ValidationError("Parallel branch roles must be a list of role names")
            if not isinstance(branch.get("users", []), list) or not all(isinstance(x, str) and x.strip() for x in branch.get("users", [])):
                raise ValidationError("Parallel branch users must be a list of email addresses")
            if branch.get("approval_mode") == "all" and not branch.get("users"):
                raise ValidationError("An all-approvers branch requires named users")
            if not branch.get("roles") and not branch.get("users") and not branch.get("anyone"):
                raise ValidationError(f"Parallel branch {branch['key']!r} must say who may approve it: roles or users (or \"anyone\": true)")
            required_branch = int(branch.get("required_approvals", 1) or 1)
            if required_branch < 1 or required_branch > 100:
                raise ValidationError("Parallel branch quorum must be between 1 and 100")
        try: required = int(tr.get("required_approvals", 1) or 1)
        except (TypeError, ValueError): raise ValidationError("required_approvals must be an integer") from None
        if required < 1 or required > 100: raise ValidationError("required_approvals must be between 1 and 100")
    state_field = payload.get("state_field") or None
    if state_field and (meta.get_field(state_field) is None or meta.get_field(state_field).fieldtype not in ("Data", "Select")):
        raise ValidationError(f"{doctype}.{state_field} must be a Data or Select field to hold workflow state")
    with db.transaction() as c:
        existing = c.execute(select(definition.c.enabled).where(definition.c.name == name)).first()
    enabled = payload.get("enabled")
    enabled = (1 if existing is None or existing[0] else 0) if enabled is None else (1 if enabled else 0)
    if enabled and not state_field and any(x.get("allows_submit") or x.get("locks_content") for x in states):
        raise ValidationError("States that allow submit or lock the content need a state field to hold the state")
    row = dict(name=name, doctype=doctype, initial_state=initial, states=states, transitions=transitions,
               state_field=state_field, enabled=enabled, created_by=s.user, created_on=_now())
    with db.transaction() as c:
        if existing is not None:
            c.execute(update(definition).where(definition.c.name == name).values(**{k:v for k,v in row.items() if k != "created_on"}))
        else: c.execute(insert(definition).values(**row))
    # Every saved definition is immutable-versioned; active instances retain the version they started with.
    from .workflow_automation import snapshot
    snapshot(name, {"name": name, "doctype": doctype, "initial_state": initial, "states": states,
                    "transitions": transitions, "state_field": state_field})
    if existing is None and enabled or existing is not None and bool(existing[0]) != bool(enabled):
        _tell_policy(doctype)
    return row


def list_definitions():
    ensure()
    with db.transaction() as c: return [dict(r) for r in c.execute(select(definition).order_by(definition.c.name)).mappings()]


def start(workflow_name: str, doctype: str, document_name: str) -> dict:
    ensure()
    from .meta.registry import registry
    from .permissions import check_permission
    meta = registry.get(doctype); check_permission(meta, "write")
    from .document.document import get_doc
    doc = get_doc(doctype, document_name)
    from .permissions import check_row_policy
    check_row_policy(doctype, "write", doc.as_dict())                  # starting a workflow changes the document's state field: a record you may read but not write is not yours to start
    s = get_session()
    with db.transaction() as c:
        wf = c.execute(select(definition).where(definition.c.name == workflow_name, definition.c.doctype == doctype, definition.c.enabled == 1)).mappings().first()
        if not wf: raise DoesNotExistError(f"No active workflow {workflow_name!r} for {doctype}")
        active = c.execute(select(instance.c.id).where(instance.c.workflow == workflow_name, instance.c.doctype == doctype,
            instance.c.document_name == document_name, instance.c.status == "Active")).first()
        if active: raise ValidationError("This document already has an active workflow")
        rid = secrets.token_hex(16); now = _now()
        c.execute(insert(instance).values(id=rid, workflow=workflow_name, doctype=doctype, document_name=document_name,
            state=wf["initial_state"], status="Active", started_by=s.user, started_on=now, modified_on=now, version=1))
        c.execute(insert(log).values(id=secrets.token_hex(16), instance_id=rid, from_state=None, to_state=wf["initial_state"],
            action="Start", actor=s.user, comment="", created_on=now))
        from .activity import record_event
        record_event("workflow", f"Workflow {workflow_name} started",
            doctype=doctype, document_name=document_name, summary=f"Initial state: {wf['initial_state']}",
            source="automation", metadata={"workflow":workflow_name,"state":wf["initial_state"]})
        if wf["state_field"]:
            doc.set(wf["state_field"], wf["initial_state"])
            with engine_write(): doc.save(ignore_permissions=True)
        from .workflow_automation import attach_instance
        attach_instance(rid, workflow_name)
        _fire_notification(doc, f"workflow:{workflow_name}:started")
    return get_instance(rid)


def get_instance(instance_id: str) -> dict:
    ensure()
    with db.transaction() as c:
        r = c.execute(select(instance).where(instance.c.id == instance_id)).mappings().first()
        if not r: raise DoesNotExistError("Workflow instance not found")
        from .document.document import get_doc
        get_doc(r["doctype"], r["document_name"])
        wf = c.execute(select(definition).where(definition.c.name == r["workflow"])).mappings().first()
        # Running instances use the immutable definition version captured at start time.
        try:
            from .workflow_automation import instance_versions, versions
            vid = c.execute(select(instance_versions.c.version_id).where(instance_versions.c.instance_id == instance_id)).scalar()
            frozen = c.execute(select(versions.c.definition).where(versions.c.id == vid)).scalar() if vid else None
            if frozen: wf = {**dict(wf), **frozen}
        except Exception:
            pass
        out = dict(r)
        out["available_actions"] = [{"action": t.get("action"), "to_state": t.get("to_state"), "roles": t.get("roles") or [],
                                      "approval_mode": t.get("approval_mode", "single"), "required_approvals": int(t.get("required_approvals", 1)), "parallel_steps": t.get("parallel_steps") or []}
                                     for t in (wf["transitions"] or []) if t.get("from_state") == r["state"]]
        try:
            from .workflow_automation import instance_versions, versions, approval_progress
            with db.transaction() as vc:
                vr=vc.execute(select(instance_versions.c.version_id).where(instance_versions.c.instance_id==instance_id)).scalar()
                vrow=vc.execute(select(versions.c.version).where(versions.c.id==vr)).scalar() if vr else None
            out["definition_version"] = vrow
            out["approval_votes"] = approval_progress(instance_id)
        except Exception:
            out["definition_version"] = None; out["approval_votes"] = []
        out["history"] = [dict(x) for x in c.execute(select(log).where(log.c.instance_id == instance_id).order_by(log.c.created_on)).mappings()]
    return out


def _validate_transition_jobs(activities):
    if activities is None: return
    if not isinstance(activities, list) or len(activities) > 20:
        raise ValidationError("Transition activities must be a list of at most 20 items")
    from .jobs import _resolve
    for activity in activities:
        if not isinstance(activity, dict):
            raise ValidationError("Each transition activity must be an object")
        handler = str(activity.get("handler") or "").strip()
        kind = activity.get("type", "custom")
        if kind not in ("notification", "task", "timer", "subprocess", "custom"):
            raise ValidationError("Unsupported transition activity type")
        try:
            delay = int(activity.get("delay_minutes", 0) or 0)
            attempts = int(activity.get("max_attempts", 5) or 5)
        except (TypeError, ValueError):
            raise ValidationError("Activity delay and retry count must be integers") from None
        if not handler or delay < 0 or delay > 525600 or attempts < 1 or attempts > 20:
            raise ValidationError("Transition activity needs a handler, valid delay and retry count")
        if not isinstance(activity.get("payload") or {}, dict):
            raise ValidationError("Transition activity payload must be an object")
        try: _resolve(handler)
        except Exception: raise ValidationError(f"Transition activity handler is not registered: {handler}") from None


def _enqueue_transition_jobs(transition, row, action):
    activities = transition.get("activities") or []
    if not activities: return
    from datetime import timedelta
    from .jobs import enqueue_system_job as enqueue_job
    for i, activity in enumerate(activities):
        enqueue_job(activity["handler"], {
            "event": "workflow_transition_activity",
            "activity_type": activity.get("type", "custom"),
            "label": activity.get("label") or activity.get("type") or "Workflow activity",
            "workflow": row["workflow"], "instance_id": row["id"],
            "doctype": row["doctype"], "document_name": row["document_name"],
            "from_state": row["state"], "to_state": transition["to_state"],
            "action": action, "payload": activity.get("payload") or {}
        }, max_attempts=int(activity.get("max_attempts", 5) or 5),
            run_at=_now() + timedelta(minutes=int(activity.get("delay_minutes", 0) or 0)),
            idempotency_key=f"wf-activity:{row['id']}:{row.get('version', 1)}:{action}:{i}"[:180])


def act(instance_id: str, action: str, comment: str = "", step: str | None = None) -> dict:
    ensure(); s = get_session()
    with db.transaction() as c:
        row = c.execute(select(instance).where(instance.c.id == instance_id)).mappings().first()
        if not row: raise DoesNotExistError("Workflow instance not found")
        if row["status"] != "Active": raise ValidationError("This workflow is no longer active")
        wf = c.execute(select(definition).where(definition.c.name == row["workflow"])).mappings().first()
        # Freeze transition rules for this instance even after administrators publish a new version.
        try:
            from .workflow_automation import instance_versions, versions
            vid = c.execute(select(instance_versions.c.version_id).where(instance_versions.c.instance_id == instance_id)).scalar()
            frozen = c.execute(select(versions.c.definition).where(versions.c.id == vid)).scalar() if vid else None
            if frozen: wf = {**dict(wf), **frozen}
        except Exception:
            pass
        # The workflow transition role is the authorization to approve. Approvers do not
        # need general-purpose write access to every business field on the document.
        from .document.document import get_doc
        doc = get_doc(row["doctype"], row["document_name"], ignore_permissions=True)
        transition = next((t for t in wf["transitions"] if t.get("from_state") == row["state"] and t.get("action") == action), None)
        if not transition: raise ValidationError(f"Action {action!r} is not available from {row['state']}")
        if not _transition_conditions_match(transition, doc.as_dict(), row["doctype"], s):
            raise ValidationError("This approval action is not available because its conditions or linked rule are not satisfied")
        if transition.get("parallel_steps"):
            return _act_parallel(c, row, wf, doc, transition, instance_id, action, comment, step, s)
        roles = set(transition.get("roles") or [])
        users = {str(x).lower() for x in (transition.get("users") or [])}
        delegated_for = set()
        try:
            from .workflow_automation import delegations
            with db.transaction() as dc:
                delegated_for = {r[0] for r in dc.execute(select(delegations.c.delegator).where(
                    delegations.c.delegate == s.user.lower(), delegations.c.active == 1,
                    delegations.c.valid_from <= _now(), delegations.c.valid_until >= _now(),
                    (delegations.c.workflow.is_(None) | (delegations.c.workflow == row["workflow"])),
                    (delegations.c.doctype.is_(None) | (delegations.c.doctype == row["doctype"])))).all()}
        except Exception:
            delegated_for = set()
        mode = transition.get("approval_mode", "single")
        if mode not in ("single", "all", "any", "quorum"): raise ValidationError("approval_mode must be single, all, any or quorum")
        if mode == "all" and not users:
            raise ValidationError("The 'all' approval policy requires specific named approver users")
        if mode == "all":
            authorized = s.user.lower() in users or bool(users & delegated_for)
        else:
            authorized = (not roles and not users) or bool(roles & set(s.roles)) or s.user.lower() in users or bool(users & delegated_for)
        if s.user != "Administrator" and not authorized:
            raise PermissionDenied("You are not an assigned user or role permitted to perform this approval action")
        _check_separation(transition, row, doc, s)
        quorum = int(transition.get("required_approvals", 1) or 1)
        if quorum < 1 or quorum > 100: raise ValidationError("required_approvals must be between 1 and 100")
        if mode in ("single", "any"): quorum = 1
        elif mode == "all": quorum = len(users)
        if quorum > 1:
            from .workflow_automation import votes
            prior = c.execute(select(votes.c.id).where(votes.c.instance_id == instance_id, _round(votes, row["version"]), votes.c.action == action, votes.c.actor == s.user)).first()
            if prior: raise ValidationError("You have already voted on this approval step")
            c.execute(insert(votes).values(id=secrets.token_hex(16), instance_id=instance_id, round=row["version"], action=action, actor=s.user, decision=action, comment=(comment or "")[:2000], created_on=_now()))
            count = c.execute(select(votes.c.id).where(votes.c.instance_id == instance_id, _round(votes, row["version"]), votes.c.action == action, votes.c.decision == action)).all()
            if len(count) < quorum:
                c.execute(insert(log).values(id=secrets.token_hex(16), instance_id=instance_id, from_state=row["state"], to_state=row["state"], action=f"Vote:{action}", actor=s.user, comment=f"Approval vote recorded ({len(count)}/{quorum})", created_on=_now()))
                from .activity import record_event
                record_event("approval", f"Approval vote recorded: {action}",
                    doctype=row["doctype"], document_name=row["document_name"],
                    summary=f"Approval vote recorded ({len(count)}/{quorum})",
                    source="automation", metadata={"workflow":row["workflow"],"action":action})
                return get_instance(instance_id)
        target = transition["to_state"]; final = bool(transition.get("final")) or target in {x.get("name") for x in wf["states"] if x.get("is_final")}
        now = _now()
        changed = c.execute(update(instance).where(instance.c.id == instance_id, instance.c.version == row["version"]).values(
            state=target, status="Completed" if final else "Active", modified_on=now, version=row["version"] + 1)).rowcount
        if not changed: raise ValidationError("Workflow changed concurrently. Refresh and try again.")
        c.execute(insert(log).values(id=secrets.token_hex(16), instance_id=instance_id, from_state=row["state"], to_state=target,
            action=action, actor=s.user, comment=(comment or "")[:2000], created_on=now))
        from .activity import record_event
        event_type = "approval" if action.lower() in {"approve","approved","reject","rejected"} else "workflow"
        record_event(event_type, f"Workflow {row['workflow']} action: {action}",
            doctype=row["doctype"], document_name=row["document_name"],
            summary=f"State changed from {row['state']} to {target}",
            source="automation", metadata={"workflow":row["workflow"],"action":action,"from_state":row["state"],"to_state":target})
        if wf["state_field"]:
            doc.set(wf["state_field"], target)
            with engine_write(): doc.save(ignore_permissions=True)
        _enqueue_transition_jobs(transition, row, action)
        _fire_notification(doc, f"workflow:{row['workflow']}:{action}")
    try:
        from .workflow_orchestration import complete_child_links
        complete_child_links(instance_id)
    except Exception:
        pass
    return get_instance(instance_id)


def _check_separation(transition, row, doc, session):
    """Maker-checker: when a transition says `prevent_self_approval`, the person who started the workflow and the owner of the document cannot approve it (Administrator excepted)."""
    if not transition.get("prevent_self_approval") or session.user == "Administrator":
        return
    me = session.user.lower()
    subject = set()
    try:                                    # the person the request is ABOUT may not approve it either
        emp = doc.get("employee")
        if emp:
            from .document.document import get_doc
            u = get_doc("Employee", emp, ignore_permissions=True).get("user_account")
            if u: subject.add(str(u).lower())
    except Exception:
        pass
    if me in {str(row.get("started_by") or "").lower(), str(doc.get("owner") or "").lower()} | subject:
        raise PermissionDenied("The person who created or started this request cannot approve it (separation of duties)")


def _round(votes, version):
    """Votes belong to ONE round of approvals (the instance's version when they were cast). Every vote stays on record as evidence, but only the current round counts toward a quorum or
    blocks a second vote: otherwise an earlier round's approvals would carry over after a rejection and resubmission, and nobody could vote again. Votes from before this column
    existed (round is empty) count as the current round, so approvals already in flight are not lost by an upgrade."""
    return votes.c.round.is_(None) | (votes.c.round == version)


def _act_parallel(c, row, wf, doc, transition, instance_id, action, comment, step, session):
    from .workflow_automation import votes, delegations
    branches = transition.get("parallel_steps") or []
    branch = next((x for x in branches if x.get("key") == step), None)
    if branch is None:
        raise ValidationError("Select a valid parallel approval branch")
    roles = set(branch.get("roles") or [])
    users = {str(x).lower() for x in branch.get("users") or []}
    delegated = {r[0] for r in c.execute(select(delegations.c.delegator).where(
        delegations.c.delegate == session.user.lower(), delegations.c.active == 1,
        delegations.c.valid_from <= _now(), delegations.c.valid_until >= _now(),
        (delegations.c.workflow.is_(None) | (delegations.c.workflow == row["workflow"])),
        (delegations.c.doctype.is_(None) | (delegations.c.doctype == row["doctype"])))).all()}
    if session.user != "Administrator" and not ((not roles and not users) or roles.intersection(session.roles)
            or session.user.lower() in users or users.intersection(delegated)):
        raise PermissionDenied("You are not assigned to this parallel approval branch")
    _check_separation(transition, row, doc, session)
    if session.user != "Administrator" and c.execute(select(votes.c.id).where(votes.c.instance_id == instance_id, _round(votes, row["version"]), votes.c.actor == session.user,
            votes.c.action.like(f"{action}::%"))).first():
        raise ValidationError("You have already approved a branch of this step: each branch needs a different approver")      # one person could otherwise satisfy every parallel branch alone
    vote_key = f"{action}::{step}"
    if c.execute(select(votes.c.id).where(votes.c.instance_id == instance_id, _round(votes, row["version"]),
            votes.c.action == vote_key, votes.c.actor == session.user)).first():
        raise ValidationError("You have already voted on this approval branch")
    mode = branch.get("approval_mode", "single")
    required = len(users) if mode == "all" else (1 if mode in ("single", "any") else int(branch.get("required_approvals", 1) or 1))
    if required < 1:
        raise ValidationError("Parallel approval branch has no approvers")
    existing_votes = len(c.execute(select(votes.c.id).where(votes.c.instance_id == instance_id, _round(votes, row["version"]),
        votes.c.action == vote_key, votes.c.decision == "Approve")).all())
    if existing_votes >= required:
        raise ValidationError("This parallel approval branch has already met its approval threshold")
    c.execute(insert(votes).values(id=secrets.token_hex(16), instance_id=instance_id, round=row["version"], action=vote_key,
        actor=session.user, decision="Approve", comment=(comment or "")[:2000], created_on=_now()))
    got = len(c.execute(select(votes.c.id).where(votes.c.instance_id == instance_id, _round(votes, row["version"]),
        votes.c.action == vote_key, votes.c.decision == "Approve")).all())
    c.execute(insert(log).values(id=secrets.token_hex(16), instance_id=instance_id,
        from_state=row["state"], to_state=row["state"], action=f"Parallel:{step}", actor=session.user,
        comment=f"{branch.get('label', step)}: {min(got, required)}/{required} approvals", created_on=_now()))
    from .activity import record_event
    record_event("approval", f"Approval vote recorded: {branch.get('label', step)}",
        doctype=row["doctype"], document_name=row["document_name"],
        summary=f"Approval branch vote recorded ({min(got, required)}/{required})",
        source="automation", metadata={"workflow":row["workflow"],"branch":step})
    all_done = True
    for candidate in branches:
        cmode = candidate.get("approval_mode", "single")
        cusers = {str(x).lower() for x in candidate.get("users") or []}
        need = len(cusers) if cmode == "all" else (1 if cmode in ("single", "any") else int(candidate.get("required_approvals", 1) or 1))
        key = f"{action}::{candidate['key']}"
        count = len(c.execute(select(votes.c.id).where(votes.c.instance_id == instance_id, _round(votes, row["version"]),
            votes.c.action == key, votes.c.decision == "Approve")).all())
        if count < need: all_done = False
    if all_done:
        target = transition["to_state"]
        final = bool(transition.get("final")) or target in {x.get("name") for x in wf["states"] if x.get("is_final")}
        at = _now()
        changed = c.execute(update(instance).where(instance.c.id == instance_id, instance.c.version == row["version"]).values(
            state=target, status="Completed" if final else "Active", modified_on=at, version=row["version"] + 1)).rowcount
        if not changed: raise ValidationError("Workflow changed concurrently. Refresh and try again.")
        c.execute(insert(log).values(id=secrets.token_hex(16), instance_id=instance_id,
            from_state=row["state"], to_state=target, action=action, actor=session.user,
            comment="All parallel approval branches completed", created_on=at))
        record_event("workflow", f"Workflow {row['workflow']} transitioned",
            doctype=row["doctype"], document_name=row["document_name"],
            summary=f"State changed from {row['state']} to {target}",
            source="automation", metadata={"workflow":row["workflow"],"action":action,"from_state":row["state"],"to_state":target})
        if wf.get("state_field"):
            doc.set(wf["state_field"], target)
            with engine_write(): doc.save(ignore_permissions=True)
        _enqueue_transition_jobs(transition, row, action)
        _fire_notification(doc, f"workflow:{row['workflow']}:{action}")
    try:
        from .workflow_orchestration import complete_child_links
        complete_child_links(instance_id)
    except Exception:
        pass
    return get_instance(instance_id)


def _condition_matches(actual, operator: str, expected) -> bool:
    if operator in ("in", "not in"):
        if not isinstance(expected, (list, tuple, set)):
            raise ValidationError("Workflow 'in' conditions require a list of values")
        result = actual in expected
        return result if operator == "in" else not result
    try:
        if isinstance(actual, (int, float, Decimal)) and not isinstance(actual, bool):
            actual, expected = Decimal(str(actual)), Decimal(str(expected))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Workflow condition values are not comparable") from None
    try:
        return {"=": lambda: actual == expected, "!=": lambda: actual != expected, ">": lambda: actual > expected,
                "<": lambda: actual < expected, ">=": lambda: actual >= expected, "<=": lambda: actual <= expected}[operator]()
    except (TypeError, KeyError):
        raise ValidationError("Workflow condition values are not comparable") from None

def _rule_transition_matches(transition: dict, document_data: dict, doctype: str, session=None) -> bool:
    """Evaluate a shared named rule alongside legacy transition predicates."""
    rule_name = str(transition.get("rule") or "").strip()
    if not rule_name:
        return True
    from .rules import evaluate_saved_rule
    from .permissions import get_session
    actor = session or get_session()
    payload = dict(document_data or {})
    payload["doctype"] = doctype
    result = evaluate_saved_rule(rule_name, payload, {
        "user": actor.user,
        "roles": sorted(actor.roles),
        "doctype": doctype,
    })
    return bool(result["matched"])


def _transition_conditions_match(transition: dict, document_data: dict, doctype: str, session=None) -> bool:
    if not _rule_transition_matches(transition, document_data, doctype, session):
        return False
    conditions = transition.get("conditions") or ([transition["condition"]] if transition.get("condition") else [])
    checks = [_condition_matches((document_data or {}).get(x["field"]), x["operator"], x["value"]) for x in conditions]
    return (all(checks) if transition.get("condition_logic", "all") == "all" else any(checks)) if checks else True


def _fire_notification(doc, event_name: str):
    """Optional integration with velora_notify; a notification failure never blocks approval."""
    try:
        from velora_notify.engine import fire
        fire(doc, "Custom", custom=event_name)
    except Exception:
        return


def simulate(workflow_name: str, document_data: dict, state: str | None = None) -> dict:
    ensure()
    with db.transaction() as c:
        wf = c.execute(select(definition).where(definition.c.name == workflow_name, definition.c.enabled == 1)).mappings().first()
        if not wf: raise DoesNotExistError("Workflow not found or disabled")
        current = state or wf["initial_state"]
        if current not in {x.get("name") for x in wf["states"]}:
            raise ValidationError("Simulation state is not part of this workflow")
        routes = []
        for tr in wf["transitions"] or []:
            if tr.get("from_state") != current: continue
            matched = _transition_conditions_match(tr, document_data, wf["doctype"])
            routes.append({"action": tr["action"], "to_state": tr["to_state"], "conditions_met": matched,
                           "parallel_steps": tr.get("parallel_steps") or [], "activities": tr.get("activities") or []})
    return {"workflow": workflow_name, "state": current, "routes": routes,
            "matched_routes": [x for x in routes if x["conditions_met"]]}


def approval_inbox(limit: int = 100) -> list[dict]:
    ensure(); session = get_session(); limit = max(1, min(int(limit), 250))
    with db.transaction() as c:
        rows = c.execute(select(instance).where(instance.c.status == "Active").order_by(instance.c.started_on).limit(limit)).mappings().all()
        out = []
        for row in rows:
            wf = c.execute(select(definition).where(definition.c.name == row["workflow"])).mappings().first()
            try:
                from .workflow_automation import instance_versions, versions
                vid = c.execute(select(instance_versions.c.version_id).where(instance_versions.c.instance_id == row["id"])).scalar()
                frozen = c.execute(select(versions.c.definition).where(versions.c.id == vid)).scalar() if vid else None
                if frozen: wf = {**dict(wf), **frozen}
            except Exception: pass
            from .document.document import get_doc
            try: doc = get_doc(row["doctype"], row["document_name"], ignore_permissions=True)
            except Exception: continue                                   # a document that was deleted must not break everyone's inbox
            for tr in wf["transitions"] or []:
                if tr.get("from_state") != row["state"]: continue
                try:
                    if not _transition_conditions_match(tr, doc.as_dict(), row["doctype"], session): continue
                except Exception: continue
                for branch in tr.get("parallel_steps") or [tr]:
                    roles = set(branch.get("roles") or [])
                    users = {str(x).lower() for x in branch.get("users") or []}
                    delegated = set()
                    try:
                        from .workflow_automation import delegations, votes
                        delegated = {r[0] for r in c.execute(select(delegations.c.delegator).where(
                            delegations.c.delegate == session.user.lower(), delegations.c.active == 1,
                            delegations.c.valid_from <= _now(), delegations.c.valid_until >= _now(),
                            (delegations.c.workflow.is_(None) | (delegations.c.workflow == row["workflow"])),
                            (delegations.c.doctype.is_(None) | (delegations.c.doctype == row["doctype"])))).all()}
                        vote_key = f"{tr['action']}::{branch.get('key')}" if branch.get("key") else tr["action"]
                        already = c.execute(select(votes.c.id).where(votes.c.instance_id == row["id"], _round(votes, row["version"]),
                            votes.c.action == vote_key, votes.c.actor == session.user)).first()
                    except Exception:
                        already = None
                    assigned = session.user == "Administrator" or bool(roles.intersection(session.roles)) or session.user.lower() in users or bool(users.intersection(delegated))
                    if assigned and not already:
                        out.append({**dict(row), "action": tr["action"], "step": branch.get("key"),
                                    "label": branch.get("label", tr["action"])})
    return out


def workflow_analytics() -> dict:
    """Company-local workflow throughput, backlog and SLA performance indicators."""
    ensure()
    from datetime import timedelta
    from .workflow_automation import sla, ensure as ensure_automation
    ensure_automation()  # the SLA tables are owned by the workflow governance extension
    at = _now()
    with db.transaction() as c:
        total = c.execute(select(func.count()).select_from(instance)).scalar() or 0
        active = c.execute(select(func.count()).select_from(instance).where(instance.c.status == "Active")).scalar() or 0
        completed = c.execute(select(func.count()).select_from(instance).where(instance.c.status == "Completed")).scalar() or 0
        overdue = c.execute(select(func.count()).select_from(instance.join(sla, sla.c.instance_id == instance.c.id))
            .where(instance.c.status == "Active", sla.c.due_on < at)).scalar() or 0
        states = [dict(x) for x in c.execute(select(instance.c.state, func.count().label("count"))
            .where(instance.c.status == "Active").group_by(instance.c.state).order_by(func.count().desc())).mappings()]
        recent = c.execute(select(instance.c.started_on, instance.c.modified_on).where(
            instance.c.status == "Completed", instance.c.modified_on >= at - timedelta(days=90))).all()
    durations = [(end - start).total_seconds() / 3600 for start, end in recent if start and end and end >= start]
    return {"total_instances": int(total), "active_instances": int(active), "completed_instances": int(completed),
        "overdue_active_instances": int(overdue), "overdue_rate": round(overdue / active, 4) if active else 0,
        "active_by_state": states, "completed_last_90_days": len(durations),
        "average_completion_hours_90_days": round(sum(durations) / len(durations), 2) if durations else None}


def install_routes(app, scope, run):
    @app.get("/api/workflows")
    def workflows(request: Request): return run(request, list_definitions)
    @app.post("/api/workflows")
    def workflow_save(request: Request, body: dict = Body(...)): return run(request, lambda: save_definition(body))
    @app.post("/api/workflows/{workflow}/start")
    def workflow_start(workflow: str, request: Request, body: dict = Body(...)):
        return run(request, lambda: start(workflow, str(body.get("doctype", "")), str(body.get("document_name", ""))))
    @app.get("/api/workflow-instances/{instance_id}")
    def workflow_get(instance_id: str, request: Request): return run(request, lambda: get_instance(instance_id))
    @app.post("/api/workflow-instances/{instance_id}/action")
    def workflow_action(instance_id: str, request: Request, body: dict = Body(...)):
        return run(request, lambda: act(instance_id, str(body.get("action", "")), str(body.get("comment", "")), body.get("step")))
    @app.get("/api/workflow-inbox")
    def workflow_inbox(request: Request, limit: int = 100): return run(request, lambda: approval_inbox(limit))
    @app.get("/api/workflow-analytics")
    def workflow_metrics(request: Request): return run(request, workflow_analytics)
    from .workflow_orchestration import install_routes as install_orchestration_routes
    install_orchestration_routes(app, run)
    install_document_routes(app, run)
    @app.get("/api/roles")
    def known_roles(request: Request):
        """Every role the designer can offer: the roles named in any DocType's permissions, the roles already used by workflows, and System Manager."""
        def fn():
            from .meta.registry import registry
            found = {"System Manager"}
            for m in registry.all():
                for p in m.permissions:
                    role = p.get("role") if isinstance(p, dict) else getattr(p, "role", None)
                    if role: found.add(str(role))
            for wf in list_definitions():
                for t in wf.get("transitions") or []:
                    found.update(str(r) for r in t.get("roles") or [])
            return sorted(found)
        return run(request, fn)

    @app.post("/api/workflows/{workflow}/simulate")
    def workflow_simulate(workflow: str, request: Request, body: dict = Body(...)):
        return run(request, lambda: simulate(workflow, body.get("document") or {}, body.get("state")))

# ---- Approval on the document itself (v1.11) -----------------------------------------------------------------
def _policy_providers() -> list:
    """Callables `decide(doctype) -> True | False | None` offered by installed apps (hook `approval_policy_provider`)."""
    from importlib import import_module
    from .meta.registry import registry
    out = []
    for app_name in registry.apps:
        try: hooks = import_module(f"{app_name}.hooks")
        except ModuleNotFoundError: continue
        path = getattr(hooks, "approval_policy_provider", None)
        if not path: continue
        try: out.append(import_module(path).decide)
        except Exception: continue
    return out


def policy(doctype: str):
    """What the company's settings say about approval for this DocType: True (required), False (not required) or None (no opinion).

    The settings are the policy; a workflow is only the route a required approval takes. False switches the workflow off for the
    DocType without deleting it; True with no enabled workflow is reported by `approval_gap` instead of being ignored."""
    for decide in _policy_providers():
        try: value = decide(doctype)
        except Exception: value = None
        if value is not None: return bool(value)
    return None


def approval_gap(doctype: str) -> bool:
    """Settings ask for approval but no workflow is active. Informational only (shown in Finance Settings): it never blocks a document."""
    return policy(doctype) is True and not _enabled_definitions(doctype)


_APPROVED_WORDS = ("Approved", "Accepted", "Confirmed")


def settle(doc) -> None:
    """A document type with no active workflow needs no approval: its approval status reads Approved from the first save.

    Approval is a GUI workflow and nothing else. Every controller that once waited for a coded `approval_status == "Approved"`
    therefore passes by itself until the company switches a workflow on for that DocType. Rejected stays rejected."""
    meta = getattr(doc, "meta", None)
    if meta is None or _engine_write.get():
        return
    f = meta.get_field("approval_status") if hasattr(meta, "get_field") else None
    if f is None or f.fieldtype != "Select":
        return
    current = str(getattr(doc, "approval_status", None) or "")
    if current not in ("", "Pending", "Pending Approval", "Draft", "Submitted for Approval"):
        return
    if any(wf["state_field"] == "approval_status" for wf in _enabled_definitions(doc.doctype)):
        return
    target = next((o for o in f.choices if o in _APPROVED_WORDS), None)
    if target:
        doc.approval_status = target


def _enabled_definitions(doctype: str) -> list[dict]:
    """Enabled workflows for the DocType that keep their state on a field (only those can gate a document)."""
    if policy(doctype) is False: return []
    try:
        ensure()
        with db.transaction() as c:
            return [dict(r) for r in c.execute(select(definition).where(
                definition.c.doctype == doctype, definition.c.enabled == 1, definition.c.state_field.isnot(None))).mappings()]
    except Exception:
        return []


def is_managed(doctype: str) -> bool:
    """True when an enabled workflow decides this DocType's approval. A company with no workflow has no approval step."""
    return bool(_enabled_definitions(doctype))


def state_flags(doctype: str, field: str, state) -> dict:
    """The flags (allows_submit, locks_content, is_final) of a state on the workflow that owns `field`."""
    for wf in _enabled_definitions(doctype):
        if wf["state_field"] != field: continue
        for x in wf["states"] or []:
            if isinstance(x, dict) and x.get("name") == str(state or ""): return x
    return {}


def approval_satisfied(doc, field: str = "approval_status") -> bool:
    """May this document go on to be submitted or posted?  No workflow = nothing to wait for; otherwise its state must allow it."""
    defs = [w for w in _enabled_definitions(doc.doctype) if w["state_field"] == field]
    if not defs: return True
    state = str(getattr(doc, field, None) or "")
    allowed = {x.get("name") for w in defs for x in (w["states"] or []) if isinstance(x, dict) and x.get("allows_submit")}
    return state in allowed if allowed else True


def guard_locked(doc) -> None:
    """A state flagged `locks_content` freezes the document: change it only after the workflow reopens it."""
    if _engine_write.get() or getattr(doc, "_old", None) is None:
        return
    for wf in _enabled_definitions(doc.doctype):
        field = wf["state_field"]
        old = str(doc._old.get(field) or "")
        if any(isinstance(x, dict) and x.get("name") == old and x.get("locks_content") for x in wf["states"] or []):
            raise ValidationError(f"This {doc.doctype} is {old} and locked. Use the approval action to reopen it before editing.")


def prepare_insert(doc):
    """Start a new document in its workflow's initial state (and refuse any other start). Returns the workflow to start after insert, or None."""
    defs = _enabled_definitions(doc.doctype)
    if not defs: return None
    for wf in defs:
        field = wf["state_field"]
        current = getattr(doc, field, None)
        if not _engine_write.get() and not getattr(doc.flags, "ignore_permissions", False) and current not in (None, "", wf["initial_state"]):
            # a field's own starting value (its default) is accepted; anything else would skip the approval
            default = doc.meta.get_field(field).default if doc.meta.get_field(field) else None
            if str(current) != str(default):
                raise ValidationError(f"{field.replace('_', ' ').title()} is controlled by this document's approval workflow; a new document starts as {wf['initial_state']}.")
        doc.set(field, wf["initial_state"])
        doc.flags.workflow_fields = set(getattr(doc.flags, "workflow_fields", set())) | {field}
    return defs[0] if len(defs) == 1 else None


def begin_instance(wf: dict, doc) -> str:
    """Create the running instance for a document (system action; the caller already checked what it needed to)."""
    s = get_session(); rid = secrets.token_hex(16); now = _now()
    with db.transaction() as c:
        c.execute(insert(instance).values(id=rid, workflow=wf["name"], doctype=doc.doctype, document_name=doc.name,
            state=wf["initial_state"], status="Active", started_by=s.user, started_on=now, modified_on=now, version=1))
        c.execute(insert(log).values(id=secrets.token_hex(16), instance_id=rid, from_state=None, to_state=wf["initial_state"],
            action="Start", actor=s.user, comment="", created_on=now))
    try:
        from .workflow_automation import attach_instance
        attach_instance(rid, wf["name"])
    except Exception:
        pass
    return rid


def after_insert(doc, wf) -> None:
    if wf is None: return
    begin_instance(wf, doc)
    _fire_notification(doc, f"workflow:{wf['name']}:started")


def _may(transition: dict, row: dict, doc, session, c) -> tuple[bool, str]:
    """Can this person take this action now? (the same rules `act` enforces, without raising)"""
    roles = set(transition.get("roles") or [])
    users = {str(x).lower() for x in (transition.get("users") or [])}
    try:
        from .workflow_automation import delegations
        delegated = {r[0] for r in c.execute(select(delegations.c.delegator).where(
            delegations.c.delegate == session.user.lower(), delegations.c.active == 1,
            delegations.c.valid_from <= _now(), delegations.c.valid_until >= _now(),
            (delegations.c.workflow.is_(None) | (delegations.c.workflow == row["workflow"])),
            (delegations.c.doctype.is_(None) | (delegations.c.doctype == row["doctype"])))).all()}
    except Exception:
        delegated = set()
    who = " or ".join(sorted(roles) + sorted(users)) or "an authorised person"
    if transition.get("approval_mode", "single") == "all":
        authorised = session.user.lower() in users or bool(users & delegated)
    else:
        authorised = (not roles and not users) or bool(roles & set(session.roles)) or session.user.lower() in users or bool(users & delegated)
    if session.user != "Administrator" and not authorised and not transition.get("anyone"):
        return False, who
    try:
        _check_separation(transition, row, doc, session)
    except PermissionDenied:
        return False, "someone other than the person who made this request"
    return True, who


def document_workflow(doctype: str, name: str) -> dict | None:
    """What the approval bar on a document shows: state, the actions this person may take, history, and submit/lock status."""
    from .document.document import get_doc
    defs = _enabled_definitions(doctype)
    doc = get_doc(doctype, name)
    session = get_session()
    with db.transaction() as c:
        row = c.execute(select(instance).where(instance.c.doctype == doctype, instance.c.document_name == name)
            .order_by(instance.c.started_on.desc())).mappings().first()
        if row is None and not defs: return None
        wf = None
        if row is not None:
            wf = c.execute(select(definition).where(definition.c.name == row["workflow"])).mappings().first()
            try:
                from .workflow_automation import instance_versions, versions
                vid = c.execute(select(instance_versions.c.version_id).where(instance_versions.c.instance_id == row["id"])).scalar()
                frozen = c.execute(select(versions.c.definition).where(versions.c.id == vid)).scalar() if vid else None
                if frozen: wf = {**dict(wf), **frozen}
            except Exception:
                pass
        elif defs:
            wf = defs[0]
        field = (wf or {}).get("state_field")
        state = (row["state"] if row is not None else (getattr(doc, field, None) if field else None))
        out = {"workflow": wf["name"], "state_field": field, "state": state, "status": row["status"] if row is not None else None,
               "instance_id": row["id"] if row is not None and row["status"] == "Active" else None, "actions": [], "history": []}
        if row is not None:
            for tr in wf["transitions"] or []:
                if tr.get("from_state") != row["state"] or row["status"] != "Active": continue
                try:
                    if not _transition_conditions_match(tr, doc.as_dict(), doctype, session): continue
                except Exception:
                    continue
                if tr.get("parallel_steps"):
                    for br in tr["parallel_steps"]:
                        ok, who = _may(br, row, doc, session, c)
                        out["actions"].append({"action": tr["action"], "label": tr.get("label") or tr["action"], "to_state": tr["to_state"], "step": br.get("key"), "step_label": br.get("label"), "can_act": ok, "reason": who})
                else:
                    ok, who = _may(tr, row, doc, session, c)
                    out["actions"].append({"action": tr["action"], "label": tr.get("label") or tr["action"], "to_state": tr["to_state"], "can_act": ok, "reason": who})
            out["history"] = [dict(x) for x in c.execute(select(log).where(log.c.instance_id == row["id"]).order_by(log.c.created_on)).mappings()]
        states = [x for x in (wf.get("states") or []) if isinstance(x, dict)]
        current = next((x for x in states if x.get("name") == state), {})
        submit_states = sorted(x["name"] for x in states if x.get("allows_submit"))
        out["locked"] = bool(current.get("locks_content"))
        out["submit_states"] = submit_states
        out["submit_ready"] = bool(submit_states) and str(state or "") in submit_states
        out["can_start"] = row is None or row["status"] != "Active"
        if out["can_start"]:
            try:
                from .permissions import has_permission
                from .meta.registry import registry
                initial = defs[0]["initial_state"] if defs else None
                fresh = str(state or "") in ("", str(initial or "")) and int(doc.docstatus or 0) == 0
                out["can_start"] = has_permission(registry.get(doctype), "write") and len(defs) >= 1 and row is None and fresh
            except Exception:
                out["can_start"] = False
    return out


def start_for_document(doctype: str, name: str) -> dict:
    """Put an existing document into its (only) workflow, for documents created before the workflow was set up."""
    defs = _enabled_definitions(doctype)
    if len(defs) != 1:
        raise ValidationError("Choose the workflow to start: this document type has " + ("none" if not defs else "more than one") + " enabled.")
    return start(defs[0]["name"], doctype, name)


def install_document_routes(app, run):
    @app.get("/api/documents/{doctype}/{name}/workflow")
    def document_workflow_get(doctype: str, name: str, request: Request): return run(request, lambda: document_workflow(doctype, name))
    @app.get("/api/workflow-starters")
    def workflow_templates_get(request: Request): return run(request, workflow_templates)
    @app.post("/api/workflow-starters/install")
    def workflow_templates_install(request: Request, body: dict = Body(...)):
        return run(request, lambda: install_templates(body.get("names") or []))
    @app.post("/api/documents/{doctype}/{name}/workflow/start")
    def document_workflow_start(doctype: str, name: str, request: Request, body: dict = Body(default={})):
        return run(request, lambda: start_for_document(doctype, name))


# ---- Starter workflows contributed by apps (v1.11) ------------------------------------------------------------
def list_for_doctype(doctype: str) -> list[str]:
    """Names of every workflow (enabled or not) defined for the DocType."""
    ensure()
    with db.transaction() as c:
        return [r[0] for r in c.execute(select(definition.c.name).where(definition.c.doctype == doctype))]


def workflow_templates() -> list[dict]:
    """Sample workflows that installed apps offer (hook `workflow_template_provider`: a module, or a list of modules, with templates()).
    Apps install them inactive; who approves what differs per company, so a company edits and switches on its own."""
    from importlib import import_module
    from .meta.registry import registry
    out, have = [], {w["name"] for w in list_definitions()}
    for app_name in registry.apps:
        try: hooks = import_module(f"{app_name}.hooks")
        except ModuleNotFoundError: continue
        paths = getattr(hooks, "workflow_template_provider", None)
        if not paths: continue
        for path in ([paths] if isinstance(paths, str) else list(paths)):
            try: items = import_module(path).templates()
            except Exception: continue
            for tpl in items:
                out.append({"name": tpl["name"], "doctype": tpl["doctype"], "app": app_name, "installed": tpl["name"] in have,
                            "states": [x["name"] for x in tpl["states"]],
                            "approvers": sorted({r for t in tpl["transitions"] for r in t.get("roles", [])}), "definition": tpl})
    return sorted(out, key=lambda x: (x["doctype"], x["name"]))


def install_templates(names: list[str]) -> list[str]:
    """Install the chosen starter workflows (System Manager) as inactive samples to review and activate. Existing definitions are left untouched."""
    s = get_session()
    if s.user != "Administrator" and "System Manager" not in s.roles:
        raise PermissionDenied("Only a System Manager can install workflows")
    wanted = {str(n) for n in names or []}
    done = []
    for tpl in workflow_templates():
        if tpl["name"] in wanted and not tpl["installed"]:
            save_definition({**tpl["definition"], "enabled": False}); done.append(tpl["name"])
    return done


def _tell_policy(doctype: str) -> None:
    """A workflow was switched on or off in the designer: let the apps' approval policy follow, so the settings never contradict it.
    Apps answer with `workflow_changed(doctype, enabled)` in the module named by the hook `approval_policy_provider`."""
    from importlib import import_module
    from .meta.registry import registry
    enabled = has_enabled_workflow(doctype)
    for app_name in registry.apps:
        try:
            path = getattr(import_module(f"{app_name}.hooks"), "approval_policy_provider", None)
            if path: getattr(import_module(path), "workflow_changed", lambda *_: None)(doctype, enabled)
        except ModuleNotFoundError: continue
        except Exception: continue


def has_enabled_workflow(doctype: str) -> bool:
    """Is any workflow switched on for the DocType? (Ignores settings policy; use `is_managed` for what actually applies.)"""
    ensure()
    with db.transaction() as c:
        return c.execute(select(definition.c.name).where(definition.c.doctype == doctype, definition.c.enabled == 1,
                                                         definition.c.state_field.isnot(None))).first() is not None


def set_enabled(name: str, enabled: bool) -> bool:
    """Switch one workflow definition on or off (system action used when the company's approval policy changes; it does not echo back to the policy)."""
    ensure()
    with db.transaction() as c:
        n = c.execute(update(definition).where(definition.c.name == name).values(enabled=1 if enabled else 0)).rowcount
    return bool(n)


def is_unused_sample(name: str) -> bool:
    """An inactive workflow that no document has ever run through: nothing depends on it, so a copied setup may replace it."""
    ensure()
    with db.transaction() as c:
        row = c.execute(select(definition.c.enabled).where(definition.c.name == name)).first()
        if row is None or row[0]: return False
        return c.execute(select(instance.c.id).where(instance.c.workflow == name).limit(1)).first() is None


def enabled_names(doctype: str) -> list[str]:
    ensure()
    with db.transaction() as c:
        return [r[0] for r in c.execute(select(definition.c.name).where(definition.c.doctype == doctype, definition.c.enabled == 1))]


def reset_state(doc, to_state: str, comment: str = "") -> bool:
    """System code sends a managed document back to an earlier state (for example approval no longer applies because its
    source changed). The running instance follows, the history records why, and the caller then saves inside `engine_write()`.
    Returns False when the document is not under an enabled workflow."""
    if not is_managed(doc.doctype): return False
    with db.transaction() as c:
        row = c.execute(select(instance).where(instance.c.doctype == doc.doctype, instance.c.document_name == doc.name)
            .order_by(instance.c.started_on.desc())).mappings().first()
        if row is None: return False
        now = _now()
        c.execute(update(instance).where(instance.c.id == row["id"]).values(state=to_state, status="Active", modified_on=now, version=row["version"] + 1))
        c.execute(insert(log).values(id=secrets.token_hex(16), instance_id=row["id"], from_state=row["state"], to_state=to_state,
            action="System reset", actor=get_session().user, comment=(comment or "")[:2000], created_on=now))
    return True
