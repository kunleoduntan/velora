"""Request fulfilment lifecycle and assignment service."""
from datetime import datetime, date
from velora import get_doc, get_list, new_doc, throw
from velora.permissions import get_session

ADMIN_ROLES = {"System Manager", "Administration Manager", "Administrative Manager"}


def _session():
    return get_session()


def _is_admin(session=None):
    session = session or _session()
    return session.user == "Administrator" or bool(set(getattr(session, "roles", ()) or ()) & ADMIN_ROLES)


def _assignment(name):
    return get_doc("Request Fulfilment", name, ignore_permissions=True)


def _require_access(assignment, allow_admin=True):
    session = _session()
    if allow_admin and _is_admin(session):
        return session
    if session.user and session.user == getattr(assignment, "assigned_to", None):
        return session
    if session.user and any(session.user == getattr(task, "assigned_to", None) for task in (getattr(assignment, "tasks", None) or [])):
        return session
    throw("You are not authorized to manage this fulfilment assignment.")


def ensure_for_approved_request(request_name):
    """Idempotently create an unassigned fulfilment shell after final approval."""
    request_doc = get_doc("Request", request_name, ignore_permissions=True)
    if request_doc.status != "Approved":
        throw("Fulfilment can only be created for an approved Request.")
    existing = get_list("Request Fulfilment", filters={"request": request_name}, fields=["name"], limit=1, ignore_permissions=True)
    if existing:
        return existing[0]["name"]
    default_team = None
    try:
        services = get_list("Service", filters={"request_type": request_doc.request_type, "is_active": 1}, fields=["default_team"], limit=1, ignore_permissions=True)
        default_team = services[0].get("default_team") if services else None
    except Exception:
        default_team = None
    assignment = new_doc("Request Fulfilment", request=request_name, status="Unassigned", priority=request_doc.priority or "Medium", progress_percent=0, assigned_team=default_team)
    assignment.insert(ignore_permissions=True)
    try:
        from .service_catalog import apply_template
        assignment = get_doc("Request Fulfilment", assignment.name, ignore_permissions=True)
        template_result = apply_template(assignment, request_doc)
    except Exception:
        template_result = {"applied": False, "reason": "Template application unavailable"}
    request_doc.fulfilment_status = "Unassigned"
    request_doc.save(ignore_permissions=True)
    return assignment.name


def list_fulfilment():
    session = _session()
    filters = {}
    if not _is_admin(session):
        filters = {"assigned_to": session.user}
    rows = get_list("Request Fulfilment", filters=filters, fields=["name", "request", "status", "priority", "assigned_to", "assigned_team", "due_date", "progress_percent"], limit=500, ignore_permissions=True)
    if not _is_admin(session):
        try:
            task_rows = get_list("Request Fulfilment Task", filters={"assigned_to": session.user}, fields=["parent"], limit=500, ignore_permissions=True)
            existing = {row.get("name") for row in rows}
            for item in task_rows:
                parent = item.get("parent")
                if parent and parent not in existing:
                    parent_doc = _assignment(parent)
                    rows.append({"name": parent_doc.name, "request": parent_doc.request, "status": parent_doc.status, "priority": parent_doc.priority, "assigned_to": parent_doc.assigned_to, "assigned_team": parent_doc.assigned_team, "due_date": parent_doc.due_date, "progress_percent": parent_doc.progress_percent})
                    existing.add(parent)
        except Exception:
            pass
    return {"items": rows}


def get_fulfilment(name):
    assignment = _assignment(name)
    _require_access(assignment)
    return assignment.as_dict() if hasattr(assignment, "as_dict") else assignment


def assign_fulfilment(name, payload):
    assignment = _assignment(name)
    session = _require_access(assignment)
    if not _is_admin(session):
        throw("Only an Administration Manager or System Manager can assign fulfilment.")
    if assignment.status in ("Completed", "Cancelled"):
        throw("Completed or cancelled fulfilment cannot be reassigned.")
    assigned_to = (payload.get("assigned_to") or "").strip()
    if not assigned_to:
        throw("Assigned To is required.")
    assignment.assigned_to = assigned_to
    assignment.assigned_team = payload.get("assigned_team") or None
    assignment.due_date = payload.get("due_date") or None
    assignment.priority = payload.get("priority") or assignment.priority
    assignment.status = "Assigned"
    assignment.save(ignore_permissions=True)
    request_doc = get_doc("Request", assignment.request, ignore_permissions=True)
    request_doc.fulfilment_status = "Assigned"
    request_doc.fulfilment_owner = assigned_to
    request_doc.fulfilment_due_date = assignment.due_date
    request_doc.save(ignore_permissions=True)
    try:
        from .service_operations import notify_assignee
        notify_assignee(assignment, "Administrative Fulfilment Assigned", f"You have been assigned fulfilment {assignment.name} for request {request_doc.name}.")
    except Exception:
        pass
    return {"name": assignment.name, "status": assignment.status, "assigned_to": assignment.assigned_to}


def start_fulfilment(name):
    assignment = _assignment(name)
    _require_access(assignment)
    if assignment.status not in ("Assigned", "Blocked"):
        throw("Only assigned or blocked fulfilment can be started.")
    assignment.status = "In Progress"
    assignment.started_on = assignment.started_on or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    assignment.save(ignore_permissions=True)
    request_doc = get_doc("Request", assignment.request, ignore_permissions=True)
    if request_doc.status == "Approved":
        request_doc.status = "In Progress"
    request_doc.fulfilment_status = "In Progress"
    request_doc.save(ignore_permissions=True)
    try:
        from .service_operations import notify_assignee
        notify_assignee(assignment, "Administrative Fulfilment Started", f"Fulfilment {assignment.name} has started.")
    except Exception:
        pass
    return {"name": assignment.name, "status": assignment.status}


def add_task(name, payload):
    assignment = _assignment(name)
    session = _require_access(assignment)
    if not _is_admin(session) and session.user != assignment.assigned_to:
        throw("Only the assigned fulfiller or an administrator can add tasks.")
    if assignment.status in ("Completed", "Cancelled"):
        throw("Tasks cannot be added to completed or cancelled fulfilment.")
    title = (payload.get("task_title") or "").strip()
    if not title:
        throw("Task title is required.")
    assignment.append("tasks", {"task_title": title, "assigned_to": payload.get("assigned_to") or assignment.assigned_to, "due_date": payload.get("due_date") or assignment.due_date, "status": "Open"})
    assignment.save(ignore_permissions=True)
    return {"name": assignment.name, "task_count": len(assignment.tasks or [])}


def update_task(name, task_id, payload):
    assignment = _assignment(name)
    session = _session()
    if assignment.status in ("Completed", "Cancelled"):
        throw("Tasks on completed or cancelled fulfilment cannot be changed.")
    task = next((t for t in assignment.tasks or [] if str(getattr(t, "name", "")) == str(task_id)), None)
    if not task:
        throw("Fulfilment task was not found.")
    if not _is_admin(session) and session.user not in (assignment.assigned_to, getattr(task, "assigned_to", None)):
        throw("You are not authorized to manage this fulfilment task.")
    status = payload.get("status")
    allowed = {"Open", "In Progress", "Blocked", "Completed", "Cancelled"}
    if status and status not in allowed:
        throw("Invalid task status.")
    if status == "In Progress" and getattr(task, "depends_on_sequence", None):
        dep_seq = int(task.depends_on_sequence)
        dependency = next((t for t in (assignment.tasks or []) if int(getattr(t, "sequence", 0) or 0) == dep_seq), None)
        if not dependency or dependency.status != "Completed":
            throw("This task cannot start until its prerequisite task is completed.")
    if status == "Completed" and not (payload.get("completion_note") or getattr(task, "completion_note", "")):
        throw("Completion note is required to complete a task.")
    evidence = payload.get("evidence_reference") or getattr(task, "evidence_reference", "")
    if status == "Completed" and getattr(task, "evidence_required", 0) and not evidence:
        throw("Evidence reference is required to complete this task.")
    if status:
        task.status = status
        if status == "Completed":
            task.completed_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if "evidence_reference" in payload:
        task.evidence_reference = payload.get("evidence_reference")
    if "completion_note" in payload:
        task.completion_note = payload.get("completion_note")
    if "assigned_to" in payload:
        task.assigned_to = payload.get("assigned_to") or None
    if "due_date" in payload:
        task.due_date = payload.get("due_date") or None
    assignment.save(ignore_permissions=True)
    total = len(assignment.tasks or [])
    done = sum(1 for t in assignment.tasks or [] if t.status == "Completed")
    assignment.progress_percent = round(done * 100 / total) if total else 0
    assignment.save(ignore_permissions=True)
    return {"name": assignment.name, "progress_percent": assignment.progress_percent}


def complete_fulfilment(name, payload):
    assignment = _assignment(name)
    session = _require_access(assignment)
    if not _is_admin(session) and session.user != assignment.assigned_to:
        throw("Only the assigned fulfiller or an administrator can complete fulfilment.")
    if assignment.status not in ("In Progress", "Assigned"):
        throw("Fulfilment must be assigned or in progress before completion.")
    tasks = list(assignment.tasks or [])
    incomplete = [t for t in tasks if t.status not in ("Completed", "Cancelled")]
    if incomplete:
        throw("All active fulfilment tasks must be completed before closing the request.")
    notes = (payload.get("completion_notes") or "").strip()
    if not notes:
        throw("Completion Notes are required.")
    assignment.status = "Completed"
    assignment.progress_percent = 100
    assignment.completion_notes = notes
    assignment.evidence_links = payload.get("evidence_links") or assignment.evidence_links
    assignment.completed_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    assignment.save(ignore_permissions=True)
    request_doc = get_doc("Request", assignment.request, ignore_permissions=True)
    request_doc.status = "Completed"
    request_doc.fulfilment_status = "Completed"
    request_doc.save(ignore_permissions=True)
    return {"name": assignment.name, "status": assignment.status, "request_status": request_doc.status}


def close_fulfilment(name, reason=""):
    assignment = _assignment(name)
    session = _require_access(assignment)
    if not _is_admin(session):
        throw("Only an administrator can close fulfilment.")
    if assignment.status != "Completed":
        throw("Only completed fulfilment can be closed.")
    assignment.status = "Closed"
    assignment.closed_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    assignment.closure_reason = reason or "Closed after successful fulfilment."
    assignment.save(ignore_permissions=True)
    return {"name": assignment.name, "status": assignment.status}


def approved_queue():
    session = _session()
    if not _is_admin(session):
        throw("Only an administrator can view the approved fulfilment queue.")
    approved = get_list("Request", filters={"status": "Approved"}, fields=["name", "request_type", "requester", "department", "priority", "required_by_date", "estimated_cost"], limit=500, ignore_permissions=True)
    assignments = get_list("Request Fulfilment", fields=["request", "name", "status"], limit=500, ignore_permissions=True)
    existing = {row.get("request") for row in assignments}
    return {"items": [row for row in approved if row.get("name") not in existing]}


def create_from_approved_request(request_name):
    session = _session()
    if not _is_admin(session):
        throw("Only an administrator can create fulfilment assignments.")
    name = ensure_for_approved_request(request_name)
    return {"name": name, "request": request_name}


def routing_recommendation(request_name):
 """Capacity-aware recommendation using existing service defaults and live fulfilment workload; no assignment is made."""
 session=_session()
 if not _is_admin(session):throw("Only an administrator can view routing recommendations.")
 request_doc=get_doc("Request",request_name,ignore_permissions=True)
 service=None
 if getattr(request_doc,"service",None):
  try:service=get_doc("Service",request_doc.service,ignore_permissions=True)
  except Exception:service=None
 preferred_team=getattr(service,"default_team",None) if service else None
 assignments=get_list("Request Fulfilment",fields=["assigned_team","assigned_to","status"],limit=10000,ignore_permissions=True)
 active=[a for a in assignments if a.get("status") not in ("Completed","Closed","Cancelled")]
 workload={}
 for a in active:
  team=a.get("assigned_team") or "Unassigned"
  workload[team]=workload.get(team,0)+1
 candidates=set(workload)
 if preferred_team:candidates.add(preferred_team)
 recommended=sorted(candidates,key=lambda team:(workload.get(team,0),0 if team==preferred_team else 1,team))[0] if candidates else None
 rationale=("Capacity-ranked recommendation using active workload; the service default is used as a tie-break preference." if preferred_team and recommended!=preferred_team else "Service default team selected after workload ranking." if preferred_team else "Lowest active workload team selected from teams already present in fulfilment assignments." if recommended else "No team workload data or service default is configured.")
 return {"request":request_name,"service":getattr(service,"name",None),"recommended_team":recommended,"preferred_team":preferred_team,"priority":getattr(request_doc,"priority",None) or "Medium","team_workload":workload,"rationale":rationale,"is_suggestion_only":True}


def reopen_fulfilment(name, reason):
 """Reopen the existing fulfilment record, rather than creating a parallel work item."""
 assignment=_assignment(name);session=_require_access(assignment)
 if not _is_admin(session):throw("Only an Administration Manager or System Manager can reopen fulfilment.")
 if assignment.status not in ("Completed","Closed"):throw("Only completed or closed fulfilment can be reopened.")
 reason=str(reason or "").strip()
 if not reason:throw("A reopening reason is required.")
 now=datetime.now().isoformat(timespec="seconds")
 assignment.status="Assigned";assignment.reopen_count=int(getattr(assignment,"reopen_count",0) or 0)+1;assignment.last_reopened_on=now;assignment.reopening_reason=reason
 assignment.completed_on=None;assignment.closed_on=None;assignment.closure_reason=None;assignment.progress_percent=min(int(getattr(assignment,"progress_percent",0) or 0),99)
 assignment.save(ignore_permissions=True)
 request_doc=get_doc("Request",assignment.request,ignore_permissions=True)
 request_doc.status="In Progress";request_doc.fulfilment_status="Assigned";request_doc.reopened_count=int(getattr(request_doc,"reopened_count",0) or 0)+1;request_doc.last_reopened_on=now;request_doc.reopening_reason=reason
 request_doc.fulfilment_owner=assignment.assigned_to;request_doc.fulfilment_due_date=assignment.due_date
 request_doc.save(ignore_permissions=True)
 try:
  from .service_operations import notify_assignee
  notify_assignee(assignment,"Administrative Fulfilment Reopened",f"Fulfilment {assignment.name} has been reopened. Reason: {reason}")
 except Exception:pass
 return {"name":assignment.name,"request":assignment.request,"status":assignment.status,"reopen_count":assignment.reopen_count,"reason":reason}
