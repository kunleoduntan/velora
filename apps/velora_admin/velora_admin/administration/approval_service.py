"""Approval engine for Velora Admin Administrative Requests.

Actions are executed in the authenticated company/site transaction through the API route provider.
"""
from datetime import datetime
import json

from velora import get_doc, throw
from velora.meta.registry import registry
from velora.permissions import check_permission, get_session


def _employee_for_requester(doc):
    """Resolve requester Employee by exact employee name, login, email or Person link."""
    requester = str(getattr(doc, "requester", "") or "").strip()
    if not requester:
        return None
    try:
        return get_doc("Employee", requester)
    except Exception:
        pass
    from velora import get_list
    candidates = []
    for field in ("user_account", "email"):
        try:
            candidates = get_list("Employee", filters={field: requester},
                                fields=["name", "user_account", "reports_to", "department", "disabled"],
                                limit=20, ignore_permissions=True)
        except Exception:
            candidates = []
        if candidates:
            return candidates[0]
    # Employee metadata varies by installation; only query exact Person-link fields that exist.
    try:
        meta = registry.get("Employee")
        candidate_fields = {f.fieldname for f in meta.fields}
        for field in ("person", "person_record", "person_id"):
            if field in candidate_fields:
                candidates = get_list("Employee", filters={field: requester},
                                    fields=["name", "user_account", "reports_to", "department", "disabled"],
                                    limit=20, ignore_permissions=True)
                if candidates:
                    return candidates[0]
    except Exception:
        pass
    # Only fall back to the logged-in Employee when requester explicitly equals this login.
    try:
        session_user = get_session().user
        if requester == session_user and session_user:
            candidates = get_list("Employee", filters={"user_account": session_user},
                                fields=["name", "user_account", "reports_to", "department", "disabled"],
                                limit=20, ignore_permissions=True)
            if candidates:
                return candidates[0]
    except Exception:
        pass
    return None


def _resolve_dynamic_approver(doc, approver_type):
    """Resolve Manager or Department Head to a login; never fall back to a broad role."""
    employee = _employee_for_requester(doc)
    if not employee:
        throw(f"Cannot resolve the requester to an Employee record for {approver_type} approval. Check the Employee user account mapping.")
    if getattr(employee, "disabled", False):
        throw("The requester is linked to a disabled Employee record; approval routing is blocked.")
    target_employee = None
    if approver_type == "Requester's Manager":
        manager_name = getattr(employee, "reports_to", None)
        if not manager_name:
            throw("The requester has no Reports To manager configured in Employee.")
        target_employee = get_doc("Employee", manager_name)
    elif approver_type == "Department Head":
        department = getattr(doc, "department", None) or getattr(employee, "department", None)
        if not department:
            throw("Department Head approval requires a Department on the request or requester Employee.")
        department_doc = get_doc("Department", department)
        head_name = getattr(department_doc, "department_head", None)
        if not head_name:
            throw(f"Department {department} has no Department Head configured.")
        target_employee = get_doc("Employee", head_name)
    if not target_employee or getattr(target_employee, "disabled", False):
        throw(f"The resolved {approver_type} is missing or inactive.")
    login = str(getattr(target_employee, "user_account", "") or getattr(target_employee, "email", "") or "").strip()
    if not login:
        throw(f"The resolved {approver_type} Employee has no system user account or email mapping.")
    requester_login = str(getattr(employee, "user_account", "") or getattr(employee, "email", "") or "").strip()
    if target_employee.name == employee.name or (requester_login and login == requester_login):
        throw("Self-approval is not permitted. The requester cannot be assigned as their own approver.")
    return login


def _active_delegations_for(user):
    """Return active delegations where user is the delegate; missing DocType is safe."""
    try:
        from velora import get_list
        today = datetime.now().date().isoformat()
        rows = get_list("Approval Delegation", filters={"delegate_user": user, "status": "Active"},
                        fields=["name", "delegator_user", "delegate_user", "start_date", "end_date", "doctype_scope"], limit=500, ignore_permissions=True)
        return [r for r in rows if (not r.get("start_date") or str(r["start_date"]) <= today) and (not r.get("end_date") or str(r["end_date"]) >= today)]
    except Exception:
        return []


def _delegated_authorized(row, session=None):
    session = session or get_session()
    for delegation in _active_delegations_for(session.user):
        delegated_from = delegation.get("delegator_user")
        assigned_role_or_user = delegated_from == row.assigned_approver or delegated_from in set(getattr(session, "roles", ()) or ())
        if assigned_role_or_user and (not delegation.get("doctype_scope") or delegation.get("doctype_scope") in ("Request", "*")):
            return True
    return False



def _request(name):
    doc = get_doc("Request", name)
    if int(doc.docstatus or 0) != 1:
        throw("Only submitted Administrative Requests can be approved or rejected.")
    if doc.status != "Pending Approval":
        throw(f"This request is not pending approval (current status: {doc.status}).")
    return doc


def _level(doc):
    level_no = int(doc.current_level or 0)
    for row in doc.approval_history or []:
        if int(row.level_no or 0) == level_no and row.status == "Pending":
            return row
    throw("The current approval level is missing or is no longer pending.")


def _is_authorized(row, session=None):
    session = session or get_session()
    kind = (row.approver_type or "").strip()
    assigned = (row.assigned_approver or "").strip()
    if kind == "Specific User":
        return session.user == assigned
    if kind == "Specific Role":
        try:
            from velora.permissions import _effective_roles
            roles = _effective_roles(session)
        except Exception:
            roles = set(session.roles or ())
        return assigned in roles
    return False


def _require_authorized(row):
    session = get_session()
    if not _is_authorized(row, session) and not _delegated_authorized(row, session):
        throw("You are not assigned to approve this level and no active delegation grants access.")


def _notify_user(user, subject, message, docname):
    if not user:
        return
    try:
        if not registry.exists("Notification Log"):
            return
        from velora import new_doc
        fields = {f.fieldname for f in registry.get("Notification Log").fields}
        values = {"user": user, "subject": subject, "message": message, "ref_doctype": "Request", "ref_name": docname, "document_type": "Request", "document_name": docname, "type": "Alert"}
        payload = {k:v for k,v in values.items() if k in fields}
        if payload:
            new_doc("Notification Log", **payload).insert(ignore_permissions=True)
    except Exception:
        return

def _notify_approval_row(doc, row, message):
    assigned = str(row.assigned_approver or "").strip()
    targets = []
    if row.approver_type == "Specific User" and assigned:
        targets = [assigned]
    elif row.approver_type == "Specific Role" and assigned:
        try:
            from velora import get_list
            targets = [x.get("user") for x in get_list("User Role", filters={"role": assigned}, fields=["user"], limit=500, ignore_permissions=True) if x.get("user")]
        except Exception:
            targets = []
    else:
        targets = [assigned] if assigned else []
    for user in sorted(set(targets)):
        _notify_user(user, f"Request {doc.name} requires approval", message, doc.name)

def _notify_requester(doc, subject, message):
    try:
        employee = _employee_for_requester(doc)
        user = getattr(employee, "user_account", None) or getattr(employee, "email", None) if employee else None
        _notify_user(user, subject, message, doc.name)
    except Exception:
        return

def approve(name, comment=""):
    doc = _request(name)
    row = _level(doc)
    _require_authorized(row)
    row.status = "Approved"
    row.action_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row.comments = (comment or "").strip()

    next_rows = [r for r in doc.approval_history if int(r.level_no or 0) > int(doc.current_level or 0) and r.status in ("Waiting", "Pending")]
    next_rows.sort(key=lambda r: int(r.level_no or 0))
    if next_rows:
        next_rows[0].status = "Pending"
        doc.current_level = int(next_rows[0].level_no)
        doc.status = "Pending Approval"
    else:
        doc.status = "Approved"
        doc.current_level = 0
    doc.save()
    if next_rows:
        _notify_approval_row(doc, next_rows[0], f"Request {doc.name} is ready for your approval at level {next_rows[0].level_no}.")
    else:
        # Create the fulfilment record once final approval is granted. This is
        # idempotent and leaves the approved request unassigned until operations assigns it.
        try:
            from .fulfilment_service import ensure_for_approved_request
            ensure_for_approved_request(doc.name)
        except Exception:
            # Approval must remain valid; fulfilment can be created by the
            # administrator from the approved-request queue if creation fails.
            pass
        _notify_requester(doc, f"Request {doc.name} approved", f"Your Request {doc.name} has completed all approval levels and is approved.")
    return {"name": doc.name, "status": doc.status, "current_level": doc.current_level,
            "approved_level": int(row.level_no or 0), "next_level": int(next_rows[0].level_no) if next_rows else None}


def reject(name, comment):
    comment = (comment or "").strip()
    if not comment:
        throw("A rejection comment is mandatory.")
    doc = _request(name)
    row = _level(doc)
    _require_authorized(row)
    row.status = "Rejected"
    row.action_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row.comments = comment
    doc.status = "Rejected"
    doc.current_level = 0
    doc.save()
    _notify_requester(doc, f"Request {doc.name} rejected", f"Your Request {doc.name} was rejected. Reason: {comment}")
    return {"name": doc.name, "status": doc.status, "rejected_level": int(row.level_no or 0)}


def inbox():
    check_permission(registry.get("Request"), "read")
    session = get_session()
    rows = registry.get("Request")
    from velora import get_list
    docs = get_list("Request", filters={"status": "Pending Approval", "docstatus": 1},
                    fields=["name", "requester", "request_type", "department", "estimated_cost", "currency", "required_by_date", "status", "current_level", "sla_due_datetime", "sla_status"], limit=500)
    visible = []
    for item in docs:
        try:
            doc = get_doc("Request", item["name"])
            current = _level(doc)
            direct = _is_authorized(current, session)
            delegated = not direct and _delegated_authorized(current, session)
            if direct or delegated:
                payload = dict(item)
                payload["current_approver_type"] = current.approver_type
                payload["assigned_approver"] = current.assigned_approver
                payload["delegated_approval"] = bool(delegated)
                visible.append(payload)
        except Exception:
            # Invalid/missing chains and records outside permissions are not exposed in inbox.
            continue
    return visible


def summary():
    items = inbox()
    now = datetime.now()
    overdue = 0
    for item in items:
        due = item.get("sla_due_datetime")
        try:
            if due and datetime.fromisoformat(str(due)) < now:
                overdue += 1
        except ValueError:
            pass
    return {"pending_count": len(items), "overdue_count": overdue, "items": items}


def my_requests():
    """Return Administrative Requests associated with the current user or Person/Employee mapping."""
    check_permission(registry.get("Request"), "read")
    session = get_session()
    from velora import get_list
    fields = ["name", "requester", "request_type", "department", "estimated_cost", "currency", "required_by_date", "status", "current_level", "sla_due_datetime", "sla_status"]
    rows = get_list("Request", filters={"requester": session.user}, fields=fields, limit=500)
    requester_ids = {session.user}
    try:
        employee_rows = get_list("Employee", filters={"user_account": session.user}, fields=["name"], limit=20, ignore_permissions=True)
        employee_meta = registry.get("Employee")
        available = {f.fieldname for f in employee_meta.fields}
        for employee in employee_rows:
            requester_ids.add(employee.get("name"))
            for person_field in ("person", "person_record", "person_id"):
                if person_field in available:
                    try:
                        detail = get_doc("Employee", employee["name"], ignore_permissions=True)
                        person_value = getattr(detail, person_field, None)
                        if person_value:
                            requester_ids.add(str(person_value))
                    except Exception:
                        pass
    except Exception:
        pass
    known = {x["name"] for x in rows}
    for requester_id in sorted(x for x in requester_ids if x):
        if requester_id == session.user:
            continue
        try:
            more = get_list("Request", filters={"requester": requester_id}, fields=fields, limit=500)
            rows.extend(x for x in more if x["name"] not in known)
            known.update(x["name"] for x in more)
        except Exception:
            continue
    return rows


def request_detail(name):
    """Return detail only to the requester, current approver, or privileged administrators."""
    check_permission(registry.get("Request"), "read")
    doc = get_doc("Request", name)
    from velora import get_list
    session = get_session()
    roles = set(getattr(session, "roles", ()) or ())
    privileged = session.user == "Administrator" or "System Manager" in roles
    requester_match = str(getattr(doc, "requester", "") or "") == session.user
    if not requester_match:
        try:
            employee_rows = get_list("Employee", filters={"user_account": session.user}, fields=["name"], limit=20, ignore_permissions=True)
            requester_ids = {x.get("name") for x in employee_rows}
            employee_meta = registry.get("Employee")
            available = {f.fieldname for f in employee_meta.fields}
            for employee in employee_rows:
                for person_field in ("person", "person_record", "person_id"):
                    if person_field in available:
                        try:
                            employee_doc = get_doc("Employee", employee["name"], ignore_permissions=True)
                            value = getattr(employee_doc, person_field, None)
                            if value:
                                requester_ids.add(str(value))
                        except Exception:
                            pass
            requester_match = str(doc.requester or "") in requester_ids
        except Exception:
            requester_match = False
    approver_match = False
    try:
        approver_match = _is_authorized(_level(doc), session) or _delegated_authorized(_level(doc), session)
    except Exception:
        approver_match = False
    if not (privileged or requester_match or approver_match):
        throw("You do not have access to this Request.")
    fields = ["name", "requester", "request_type", "department", "organisation_unit", "location", "priority", "description", "estimated_cost", "currency", "required_by_date", "approval_matrix", "current_level", "status", "sla_due_datetime", "sla_status", "escalated", "escalated_on", "approval_history"]
    payload = {field: getattr(doc, field, None) for field in fields}
    payload["approval_history"] = [dict(row) if hasattr(row, "items") else {k: getattr(row, k, None) for k in ("level_no", "approver_type", "assigned_approver", "status", "action_on", "comments")} for row in (doc.approval_history or [])]
    return payload


def routing_diagnostics(name):
    """Read-only routing diagnostic for authorized readers; validates current chain assignments."""
    check_permission(registry.get("Request"), "read")
    doc = get_doc("Request", name)
    issues = []
    if not doc.approval_matrix:
        issues.append({"code": "MISSING_MATRIX", "severity": "error", "message": "No Approval Matrix is selected."})
    if not doc.approval_history:
        issues.append({"code": "EMPTY_CHAIN", "severity": "error", "message": "Approval history is empty."})
    for row in doc.approval_history or []:
        assigned = str(row.assigned_approver or "").strip()
        if row.approver_type in ("Specific User", "Specific Role") and not assigned:
            issues.append({"code": "UNASSIGNED_APPROVER", "severity": "error", "level": row.level_no, "message": f"Level {row.level_no} has no assigned approver."})
        elif row.approver_type in ("Requester's Manager", "Department Head") and assigned in (row.approver_type, ""):
            issues.append({"code": "UNRESOLVED_DYNAMIC_APPROVER", "severity": "error", "level": row.level_no, "message": f"Level {row.level_no} dynamic approver is not resolved."})
        if row.status == "Pending" and int(row.level_no or 0) != int(doc.current_level or 0):
            issues.append({"code": "NONCURRENT_PENDING_LEVEL", "severity": "warning", "level": row.level_no, "message": f"Level {row.level_no} is pending but is not the active level."})
    due = getattr(doc, "sla_due_datetime", None)
    try:
        if due and datetime.fromisoformat(str(due)) < datetime.now() and doc.status == "Pending Approval":
            issues.append({"code": "SLA_OVERDUE", "severity": "warning", "message": "The request SLA is overdue."})
    except ValueError:
        issues.append({"code": "INVALID_SLA_DATE", "severity": "warning", "message": "SLA due datetime cannot be parsed."})
    return {"name": doc.name, "status": doc.status, "current_level": doc.current_level, "issue_count": len(issues), "issues": issues, "healthy": not any(x["severity"] == "error" for x in issues)}


# Employee-facing request creation and administration APIs.
def _require_admin_role():
    session = get_session()
    roles = set(getattr(session, "roles", ()) or ())
    if session.user != "Administrator" and not roles.intersection({"System Manager", "Administration Manager", "Administrative Manager"}):
        throw("Administrative configuration requires System Manager or an Administration Manager role.")
    return session

def _current_person_link(session):
    from velora import get_list
    try:
        employee_rows = get_list("Employee", filters={"user_account": session.user}, fields=["name"], limit=20, ignore_permissions=True)
        meta = registry.get("Employee")
        fieldnames = {f.fieldname for f in meta.fields}
        for row in employee_rows:
            employee = get_doc("Employee", row["name"], ignore_permissions=True)
            for field in ("person", "person_record", "person_id"):
                if field in fieldnames and getattr(employee, field, None):
                    return getattr(employee, field)
            if registry.get("Person") and getattr(employee, "name", None):
                # Link by Person naming convention is not assumed; return only a verified link.
                pass
    except Exception:
        pass
    throw("Your user account is not linked to a Person record through Employee. Contact Administration to complete your employee mapping.")

def request_catalog():
    check_permission(registry.get("Request"), "create")
    from velora import get_list
    types = get_list("Request Type", filters={"is_active": 1}, fields=["name", "request_type_name", "category", "description", "requires_cost", "allow_attachments", "sla_hours", "default_department", "default_approval_matrix"], limit=500)
    matrices = get_list("Approval Matrix", filters={"is_active": 1}, fields=["name"], limit=500)
    departments = []
    currencies = []
    try:
        departments = get_list("Department", fields=["name"], limit=500)
    except Exception:
        pass
    try:
        currencies = get_list("Currency", fields=["name"], limit=500)
    except Exception:
        pass
    return {"request_types": types, "approval_matrices": matrices, "departments": departments, "currencies": currencies}

def create_request(payload):
    check_permission(registry.get("Request"), "create")
    from velora import new_doc
    session = get_session()
    kind = str(payload.get("request_type") or "").strip()
    if not kind:
        throw("Request Type is required.")
    request_type = get_doc("Request Type", kind)
    if not request_type or not request_type.is_active:
        throw("The selected Request Type is inactive or unavailable.")
    description = str(payload.get("description") or "").strip()
    if len(description) < 5:
        throw("Please provide a description of at least five characters.")
    estimated_cost = payload.get("estimated_cost")
    if request_type.requires_cost and (estimated_cost in (None, "")):
        throw("This request type requires an estimated cost.")
    if estimated_cost not in (None, "") and float(estimated_cost) < 0:
        throw("Estimated cost cannot be negative.")
    service_name = payload.get("service")
    service_form_data = payload.get("service_form_data") or {}
    if isinstance(service_form_data, str):
        try: service_form_data = json.loads(service_form_data)
        except Exception: throw("Service Form Data must be valid JSON.")
    if not isinstance(service_form_data, dict): throw("Service Form Data must be an object.")
    service = None
    if service_name:
        service = get_doc("Service", service_name, ignore_permissions=True)
        if not service or not service.is_active or getattr(service, "request_type", None) != kind:
            throw("Selected service is inactive or does not match the request type.")
        for custom_field in (getattr(service, "fields", []) or []):
            fname = str(getattr(custom_field, "fieldname", "") or "").strip()
            label = getattr(custom_field, "field_label", fname)
            value = service_form_data.get(fname)
            if getattr(custom_field, "required", 0) and value in (None, "", False):
                throw(f"{label} is required.")
            if value not in (None, "") and getattr(custom_field, "fieldtype", "") == "Select":
                allowed = [x.strip() for x in str(getattr(custom_field, "options", "") or "").splitlines() if x.strip()]
                if allowed and str(value) not in allowed: throw(f"Invalid value for {label}.")
    values = {
        "request_type": kind, "service": service_name, "service_form_data": json.dumps(service_form_data, ensure_ascii=False), "requester": _current_person_link(session),
        "department": payload.get("department") or (getattr(service, "default_department", None) if service else None) or getattr(request_type, "default_department", None),
        "organisation_unit": payload.get("organisation_unit"), "location": payload.get("location"),
        "priority": payload.get("priority") if payload.get("priority") in ("Low", "Medium", "High", "Urgent") else "Medium",
        "description": description[:10000], "estimated_cost": estimated_cost or 0,
        "currency": payload.get("currency"), "required_by_date": payload.get("required_by_date"),
        "approval_matrix": (getattr(service, "approval_matrix_override", None) if service and getattr(service, "approval_matrix_override", None) else payload.get("approval_matrix")) or getattr(request_type, "default_approval_matrix", None),
    }
    doc = new_doc("Request", **values)
    doc.insert()
    return {"name": doc.name, "status": doc.status or "Draft", "request_type": doc.request_type}

def submit_request(name):
    check_permission(registry.get("Request"), "write")
    doc = get_doc("Request", name)
    session = get_session()
    if str(doc.requester or "") not in (session.user, _current_person_link(session)) and session.user != "Administrator":
        throw("You can only submit your own Request.")
    if int(doc.docstatus or 0) != 0:
        throw("Only draft Administrative Requests can be submitted.")
    doc.submit()
    # Reuse the existing approval SLA field and calculate a distinct fulfilment SLA
    # using the service's configured business calendar, without creating a parallel SLA ledger.
    try:
        from .service_operations import business_due
        start = datetime.now()
        service_doc = get_doc("Service", doc.service, ignore_permissions=True) if getattr(doc, "service", None) else None
        calendar = getattr(service_doc, "business_calendar", None) if service_doc else None
        approval_hours = float(getattr(get_doc("Request Type", doc.request_type), "sla_hours", 48) or 48)
        doc.sla_due_datetime = business_due(start, approval_hours, calendar).isoformat(timespec="seconds")
        if service_doc:
            fulfilment_hours = float(getattr(service_doc, "sla_hours", 48) or 48)
            doc.fulfilment_sla_due_datetime = business_due(start, fulfilment_hours, calendar).isoformat(timespec="seconds")
        doc.sla_status = "On Track"
        doc.sla_paused = 0
        doc.save(ignore_permissions=True)
    except Exception:
        # Submission remains authoritative; legacy SLA values remain as fallback.
        pass
    first_pending = next((row for row in (doc.approval_history or []) if row.status == "Pending"), None)
    if first_pending:
        _notify_approval_row(doc, first_pending, f"Request {doc.name} was submitted and is awaiting your approval at level {first_pending.level_no}.")
    return {"name": doc.name, "status": doc.status, "current_level": doc.current_level, "sla_due_datetime": doc.sla_due_datetime}

def delegation_list():
    _require_admin_role()
    from velora import get_list
    return get_list("Approval Delegation", fields=["name", "delegator_user", "delegate_user", "start_date", "end_date", "doctype_scope", "status", "reason"], limit=500, ignore_permissions=True)

def delegation_create(payload):
    _require_admin_role()
    from velora import new_doc
    doc = new_doc("Approval Delegation", delegator_user=payload.get("delegator_user"), delegate_user=payload.get("delegate_user"), start_date=payload.get("start_date"), end_date=payload.get("end_date"), doctype_scope=payload.get("doctype_scope") or "Request", status=payload.get("status") or "Draft", reason=payload.get("reason"))
    doc.insert(ignore_permissions=True)
    return doc.as_dict()

def delegation_update(name, payload):
    _require_admin_role()
    doc = get_doc("Approval Delegation", name, ignore_permissions=True)
    for field in ("delegator_user", "delegate_user", "start_date", "end_date", "doctype_scope", "status", "reason"):
        if field in payload:
            setattr(doc, field, payload[field])
    doc.save(ignore_permissions=True)
    return doc.as_dict()

def escalation_rules():
    _require_admin_role()
    from velora import get_list
    return get_list("Approval Escalation Rule", fields=["name", "rule_name", "scope", "sla_hours", "escalate_to_user", "escalate_to_role", "notify_on_due", "notify_on_overdue", "is_active"], limit=500, ignore_permissions=True)

def escalation_rule_create(payload):
    _require_admin_role()
    from velora import new_doc
    doc = new_doc("Approval Escalation Rule", rule_name=payload.get("rule_name"), scope=payload.get("scope") or "Request", sla_hours=int(payload.get("sla_hours") or 48), escalate_to_user=payload.get("escalate_to_user"), escalate_to_role=payload.get("escalate_to_role"), notify_on_due=payload.get("notify_on_due", 1), notify_on_overdue=payload.get("notify_on_overdue", 1), is_active=payload.get("is_active", 1))
    doc.insert(ignore_permissions=True)
    return doc.as_dict()

def escalation_rule_update(name, payload):
    _require_admin_role()
    doc = get_doc("Approval Escalation Rule", name, ignore_permissions=True)
    for field in ("rule_name", "scope", "sla_hours", "escalate_to_user", "escalate_to_role", "notify_on_due", "notify_on_overdue", "is_active"):
        if field in payload:
            setattr(doc, field, payload[field])
    doc.save(ignore_permissions=True)
    return doc.as_dict()

def analytics():
    check_permission(registry.get("Request"), "read")
    from velora import get_list
    rows = get_list("Request", fields=["name", "status", "estimated_cost", "currency", "sla_status", "sla_due_datetime", "creation", "request_type", "department"], limit=5000)
    statuses = {}
    types = {}
    departments = {}
    overdue = due_soon = total_cost = 0
    for row in rows:
        status = row.get("status") or "Unknown"
        statuses[status] = statuses.get(status, 0) + 1
        key = row.get("request_type") or "Unspecified"
        types[key] = types.get(key, 0) + 1
        dep = row.get("department") or "Unassigned"
        departments[dep] = departments.get(dep, 0) + 1
        try:
            total_cost += float(row.get("estimated_cost") or 0)
        except (TypeError, ValueError):
            pass
        sla = str(row.get("sla_status") or "")
        if sla == "Overdue": overdue += 1
        elif sla == "Due Soon": due_soon += 1
    fulfilment_statuses = {}
    fulfilment_overdue = fulfilment_unassigned = 0
    active_fulfilment = 0
    try:
        assignments = get_list("Request Fulfilment", fields=["name", "status", "assigned_to", "due_date"], limit=5000, ignore_permissions=True)
        today = datetime.now().date()
        for assignment in assignments:
            fstatus = assignment.get("status") or "Unknown"
            fulfilment_statuses[fstatus] = fulfilment_statuses.get(fstatus, 0) + 1
            if fstatus in ("Assigned", "In Progress", "Blocked"):
                active_fulfilment += 1
            if fstatus == "Unassigned" or not assignment.get("assigned_to") and fstatus not in ("Completed", "Closed", "Cancelled"):
                fulfilment_unassigned += 1
            due = assignment.get("due_date")
            try:
                if due and str(due)[:10] < today.isoformat() and fstatus not in ("Completed", "Closed", "Cancelled"):
                    fulfilment_overdue += 1
            except Exception:
                pass
    except Exception:
        pass
    return {"total_requests": len(rows), "status_counts": statuses, "request_type_counts": types, "department_counts": departments, "overdue_count": overdue, "due_soon_count": due_soon, "estimated_cost_total": total_cost, "fulfilment_status_counts": fulfilment_statuses, "fulfilment_overdue_count": fulfilment_overdue, "fulfilment_unassigned_count": fulfilment_unassigned, "active_fulfilment_count": active_fulfilment}
