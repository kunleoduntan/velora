"""Universal administrative operations and configurable automation.

This module intentionally does not define or execute approval workflows. Approval
configuration and decisions are delegated to the framework's workflow engine.
"""
import json
from datetime import date, datetime, timedelta

try:
    import frappe
except ImportError:  # allow route registration and static tests outside a Frappe site
    frappe = None

def _frappe():
    global frappe
    if frappe is None:
        import importlib
        frappe = importlib.import_module("frappe")
    return frappe

DOCTYPES = {
    "tasks": "Task",
    "facilities": "Facility",
    "work_orders": "Facility Work Order",
    "vehicles": "Administrative Vehicle",
    "trips": "Trip",
    "vendors": "Vendor",
    "supplies": "Supply Item",
    "stock_transactions": "Stock Transaction",
    "correspondence": "Administrative Correspondence",
    "events": "Administrative Event",
    "visitors": "Administrative Visitor",
    "travel": "Administrative Travel Request",
    "automation_rules": "Automation Rule",
    "knowledge_articles": "Knowledge Article",
    "renewals": "Renewal Register",
}


def _available(doctype):
    return frappe.db.exists("DocType", doctype)


def _count(doctype, filters=None):
    if not _available(doctype):
        return 0
    return frappe.db.count(doctype, filters=filters or {})


def _below_reorder_count():
    if not _available("Supply Item"):
        return 0
    rows = frappe.get_all("Supply Item", filters={"active": 1}, fields=["quantity_on_hand", "reorder_level"], limit_page_length=10000)
    return sum(1 for row in rows if row.get("reorder_level") is not None and (row.get("quantity_on_hand") or 0) <= row.get("reorder_level"))


def operations_dashboard():
    """Return high-level operational indicators across universal admin domains."""
    _frappe()
    today = date.today()
    return {
        "as_of": today.isoformat(),
        "tasks": {
            "open": _count("Task", {"status": ["in", ["Open", "In Progress", "Waiting"]]}),
            "overdue": _count("Task", {"status": ["in", ["Open", "In Progress", "Waiting"]], "due_date": ["<", today]}),
            "completed_today": _count("Task", {"status": "Completed", "completed_on": [">=", today]}),
        },
        "facilities": {"active": _count("Facility", {"status": "Active"}), "open_work_orders": _count("Facility Work Order", {"status": ["in", ["Open", "Assigned", "In Progress", "On Hold"]]})},
        "fleet": {"vehicles": _count("Administrative Vehicle"), "service_due": _count("Administrative Vehicle", {"service_due_date": ["<=", today], "status": ["!=", "Retired"]}), "trips_pending": _count("Trip", {"status": ["in", ["Requested", "Scheduled"]]})},
        "vendors": {"active": _count("Vendor", {"status": "Active"}), "contracts_expiring": _count("Vendor", {"contract_end": ["between", [today, frappe.utils.add_days(today, 60)]], "status": "Active"})},
        "supplies": {"items": _count("Supply Item"), "below_reorder": _below_reorder_count()},
        "correspondence": {"open": _count("Administrative Correspondence", {"status": ["in", ["Received", "Registered", "Assigned", "Draft Response", "Awaiting Approval"]]}), "overdue_responses": _count("Administrative Correspondence", {"response_due": ["<", today], "status": ["not in", ["Sent", "Closed"]]})},
        "events": {"planned": _count("Administrative Event", {"status": ["in", ["Planning", "Confirmed"]]})},
        "visitors": {"expected_today": _count("Administrative Visitor", {"visit_date": today, "status": "Expected"})},
        "travel": {"pending": _count("Administrative Travel Request", {"status": ["in", ["Requested", "Approved", "Booked"]]})},
        "automation": {"enabled_rules": _count("Automation Rule", {"enabled": 1})},
    }


def create_task(payload):
    _frappe()
    allowed = {"title", "task_type", "category", "description", "status", "priority", "assigned_to", "department", "due_date", "recurrence", "source_doctype", "source_name", "checklist_json"}
    data = {k: v for k, v in (payload or {}).items() if k in allowed}
    if not data.get("title"):
        frappe.throw("Task title is required")
    doc = frappe.get_doc({"doctype": "Task", **data})
    doc.insert(ignore_permissions=False)
    return doc.as_dict()


def list_records(domain, filters=None, limit=100):
    _frappe()
    doctype = DOCTYPES.get(domain)
    if not doctype:
        frappe.throw("Unknown administrative domain")
    if not _available(doctype):
        return []
    filters = filters or {}
    safe_limit = max(1, min(int(limit or 100), 500))
    return frappe.get_all(doctype, filters=filters, fields=["name", "title", "status", "priority", "modified"], limit_page_length=safe_limit, order_by="modified desc")


def knowledge_search(query="", category=None, limit=30):
    _frappe()
    if not _available("Knowledge Article"):
        return []
    filters = {"published": 1}
    if category:
        filters["category"] = category
    q = (query or "").strip()
    rows = frappe.get_all("Knowledge Article", filters=filters, fields=["name", "title", "category", "service", "keywords", "review_date", "version"], limit_page_length=min(max(int(limit or 30), 1), 100), order_by="modified desc")
    if not q:
        return rows
    ql = q.casefold()
    return [r for r in rows if ql in str(r.get("title", "")).casefold() or ql in str(r.get("keywords", "")).casefold() or ql in str(r.get("category", "")).casefold()]


# Automation is deliberately declarative. Conditions and actions are limited to
# a small safe allow-list; no Python, eval, arbitrary SQL, or workflow creation.
ALLOWED_ACTIONS = {"create_task", "set_priority", "send_notification"}
ALLOWED_OPERATORS = {"equals", "not_equals", "contains", "greater_than", "less_than", "is_empty", "is_not_empty"}


def _matches(record, conditions):
    if not isinstance(conditions, list):
        return True
    for c in conditions:
        field, op, expected = c.get("field"), c.get("operator"), c.get("value")
        if not field or op not in ALLOWED_OPERATORS:
            return False
        actual = record.get(field)
        if op == "equals" and actual != expected: return False
        if op == "not_equals" and actual == expected: return False
        if op == "contains" and str(expected).casefold() not in str(actual or "").casefold(): return False
        if op == "greater_than":
            try:
                if not actual > expected: return False
            except Exception: return False
        if op == "less_than":
            try:
                if not actual < expected: return False
            except Exception: return False
        if op == "is_empty" and actual not in (None, "", []): return False
        if op == "is_not_empty" and actual in (None, "", []): return False
    return True


def evaluate_rules(event, record, dry_run=True):
    """Evaluate enabled rules for an event; return safe declarative actions.

    This function does not make approval decisions and never calls a workflow
    engine itself. A caller may dispatch approved action types to trusted services.
    """
    _frappe()
    rules = frappe.get_all("Automation Rule", filters={"enabled": 1, "trigger_event": event}, fields=["name", "title", "scope_doctype", "conditions_json", "actions_json", "priority"], order_by="priority asc", limit_page_length=250)
    output = []
    for rule in rules:
        if rule.scope_doctype and record.get("doctype") and rule.scope_doctype != record.get("doctype"):
            continue
        try:
            conditions = json.loads(rule.conditions_json or "[]")
            actions = json.loads(rule.actions_json or "[]")
        except (ValueError, TypeError):
            continue
        if not _matches(record, conditions):
            continue
        safe_actions = []
        for action in actions if isinstance(actions, list) else []:
            if not isinstance(action, dict) or action.get("type") not in ALLOWED_ACTIONS:
                continue
            safe_actions.append(action)
        output.append({"rule": rule.name, "title": rule.title, "actions": safe_actions, "dry_run": True})
    return output


# v1.6.0 operational services ------------------------------------------------
RECURRENCE_DAYS = {"Daily": 1, "Weekly": 7, "Monthly": 30, "Quarterly": 90, "Annually": 365}
WORK_ORDER_RECURRENCE_DAYS = {"Weekly": 7, "Monthly": 30, "Quarterly": 90, "Semi-Annual": 182, "Annual": 365}


def _date_value(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _next_date(current, recurrence, mapping=None):
    current = _date_value(current) or date.today()
    days = (mapping or RECURRENCE_DAYS).get(recurrence)
    return current + timedelta(days=days) if days else None


def complete_task(name, notes=None):
    """Complete a task and generate its next recurring instance if configured."""
    _frappe()
    doc = frappe.get_doc("Task", name)
    if doc.status == "Completed":
        return {"task": doc.name, "already_completed": True, "next_task": None}
    doc.status = "Completed"
    doc.completed_on = datetime.now()
    if notes is not None:
        doc.completion_notes = notes
    doc.save(ignore_permissions=False)
    next_task = None
    if doc.recurrence and doc.recurrence != "None":
        due = _next_date(doc.due_date, doc.recurrence)
        if due:
            data = {"doctype": "Task", "title": doc.title,
                    "task_type": doc.task_type, "category": doc.category,
                    "description": doc.description, "status": "Open",
                    "priority": doc.priority, "assigned_to": doc.assigned_to,
                    "department": doc.department, "due_date": due,
                    "recurrence": doc.recurrence, "source_doctype": "Task",
                    "source_name": doc.name, "checklist_json": doc.checklist_json}
            next_doc = frappe.get_doc(data)
            next_doc.insert(ignore_permissions=False)
            next_task = next_doc.name
    return {"task": doc.name, "completed": True, "next_task": next_task}


def create_work_order(payload):
    _frappe()
    allowed = {"title", "facility", "work_type", "description", "status", "priority", "assigned_to", "vendor", "scheduled_date", "cost_estimate", "recurrence", "notes"}
    data = {k: v for k, v in (payload or {}).items() if k in allowed}
    if not data.get("title"):
        frappe.throw("Work order title is required")
    data.setdefault("status", "Open")
    data.setdefault("priority", "Normal")
    doc = frappe.get_doc({"doctype": "Facility Work Order", **data})
    doc.insert(ignore_permissions=False)
    return doc.as_dict()


def complete_work_order(name, actual_cost=None, notes=None):
    _frappe()
    doc = frappe.get_doc("Facility Work Order", name)
    if doc.status == "Completed":
        return {"work_order": doc.name, "already_completed": True, "next_work_order": None}
    doc.status = "Completed"
    doc.completed_date = date.today()
    if actual_cost is not None:
        doc.actual_cost = actual_cost
    if notes:
        doc.notes = notes
    doc.save(ignore_permissions=False)
    next_name = None
    if doc.recurrence and doc.recurrence != "None":
        due = _next_date(doc.scheduled_date or doc.completed_date, doc.recurrence, WORK_ORDER_RECURRENCE_DAYS)
        if due:
            nxt = frappe.get_doc({"doctype": "Facility Work Order", "title": doc.title,
                "facility": doc.facility, "work_type": doc.work_type, "description": doc.description,
                "status": "Open", "priority": doc.priority, "assigned_to": doc.assigned_to,
                "vendor": doc.vendor, "scheduled_date": due, "cost_estimate": doc.cost_estimate,
                "recurrence": doc.recurrence, "notes": doc.notes})
            nxt.insert(ignore_permissions=False)
            next_name = nxt.name
    return {"work_order": doc.name, "completed": True, "next_work_order": next_name}



def vehicle_alerts(days_ahead=30):
    """List vehicles with maintenance or document expiry due in a configurable horizon."""
    _frappe()
    today = date.today()
    horizon = today + timedelta(days=max(0, min(int(days_ahead or 30), 365)))
    if not _available("Administrative Vehicle"):
        return []
    rows = frappe.get_all("Administrative Vehicle", filters={"status": ["!=", "Retired"]},
        fields=["name", "title", "service_due_date", "insurance_expiry", "registration_expiry", "status"], limit_page_length=10000)
    alerts=[]
    for row in rows:
        for field, label in (("service_due_date", "Service"), ("insurance_expiry", "Insurance"), ("registration_expiry", "Registration")):
            due=_date_value(row.get(field))
            if due and due <= horizon:
                alerts.append({"vehicle": row.name, "title": row.title, "alert_type": label,
                    "due_date": due.isoformat(), "days_remaining": (due-today).days,
                    "overdue": due < today})
    return sorted(alerts, key=lambda x:(x["days_remaining"],x["title"]))


def process_stock_transaction(payload):
    """Create and process a supply transaction with server-side quantity protection."""
    _frappe()
    data=payload or {}
    item=data.get("item")
    txn_type=data.get("transaction_type")
    qty=float(data.get("quantity") or 0)
    if not item or txn_type not in {"Receipt", "Issue", "Return", "Adjustment"}:
        frappe.throw("Supply item and a valid transaction type are required")
    if qty <= 0:
        frappe.throw("Quantity must be greater than zero")
    item_doc=frappe.get_doc("Supply Item", item)
    current=float(item_doc.quantity_on_hand or 0)
    if txn_type == "Issue" and qty > current:
        frappe.throw(f"Insufficient stock. Available quantity: {current:g}")
    resulting = current + qty if txn_type in ("Receipt", "Return") else (current-qty if txn_type == "Issue" else qty)
    tx=frappe.get_doc({"doctype":"Stock Transaction", "title":data.get("title") or f"{txn_type} - {item_doc.title}",
        "item":item, "transaction_type":txn_type, "quantity":qty, "transaction_date":data.get("transaction_date") or date.today(),
        "requester":data.get("requester"), "issued_to":data.get("issued_to"), "source_reference":data.get("source_reference"), "notes":data.get("notes")})
    tx.insert(ignore_permissions=False)
    item_doc.quantity_on_hand=resulting
    item_doc.save(ignore_permissions=False)
    return {"transaction":tx.name, "item":item, "previous_quantity":current, "resulting_quantity":resulting, "reorder_alert":resulting <= float(item_doc.reorder_level or 0)}


def check_vehicle_trip_conflicts(vehicle=None, driver=None, departure=None, returning=None, exclude_name=None):
    """Check resource overlaps for a trip; approval decisions remain external/configured."""
    _frappe()
    if not departure or not returning:
        frappe.throw("Departure and return datetimes are required")
    if str(returning) <= str(departure):
        frappe.throw("Return datetime must be after departure datetime")
    filters={"status":["in",["Scheduled","In Progress"]]}
    rows=frappe.get_all("Trip", filters=filters, fields=["name","vehicle","driver","departure_datetime","return_datetime","status"], limit_page_length=10000)
    conflicts=[]
    for row in rows:
        if exclude_name and row.name==exclude_name: continue
        overlap = str(row.departure_datetime) < str(returning) and str(row.return_datetime) > str(departure)
        if overlap and ((vehicle and row.vehicle==vehicle) or (driver and row.driver==driver)):
            conflicts.append({"trip":row.name,"vehicle":row.vehicle,"driver":row.driver,"status":row.status,
                "conflict_resource":"vehicle" if vehicle and row.vehicle==vehicle else "driver"})
    return conflicts


def check_facility_booking_conflicts(venue, start, end, exclude_name=None):
    """Prevent overlapping confirmed/in-progress event use of a facility."""
    _frappe()
    if not venue or not start or not end:
        frappe.throw("Venue, start and end are required")
    if str(end) <= str(start):
        frappe.throw("Event end must be after start")
    rows=frappe.get_all("Administrative Event", filters={"venue":venue,"status":["in",["Confirmed","In Progress"]]},
        fields=["name","title","start_datetime","end_datetime","status"], limit_page_length=10000)
    return [{"event":r.name,"title":r.title,"status":r.status} for r in rows if (not exclude_name or r.name!=exclude_name) and str(r.start_datetime)<str(end) and str(r.end_datetime)>str(start)]


def run_daily_admin_automation():
    """Daily maintenance: create due recurrence, produce actionable alerts, and evaluate configured rules in dry-run."""
    _frappe()
    today=date.today()
    generated_tasks=[]
    # Generate recurring tasks when a completed recurring task is the latest template.
    if _available("Task"):
        completed=frappe.get_all("Task", filters={"status":"Completed","recurrence":["!=","None"]},
            fields=["name","title","task_type","category","description","priority","assigned_to","department","due_date","recurrence","checklist_json"], limit_page_length=10000)
        for task in completed:
            if not task.due_date: continue
            next_due=_next_date(task.due_date, task.recurrence)
            if next_due and next_due <= today:
                # Idempotency via source reference and due date.
                existing=frappe.get_all("Task",filters={"source_doctype":"Task","source_name":task.name,"due_date":next_due},fields=["name"],limit=1)
                if not existing:
                    new=frappe.get_doc({"doctype":"Task","title":task.title,"task_type":task.task_type,
                        "category":task.category,"description":task.description,"status":"Open","priority":task.priority,
                        "assigned_to":task.assigned_to,"department":task.department,"due_date":next_due,
                        "recurrence":task.recurrence,"source_doctype":"Task","source_name":task.name,
                        "checklist_json":task.checklist_json})
                    new.insert(ignore_permissions=False); generated_tasks.append(new.name)
    return {"run_date":today.isoformat(),"recurring_tasks_created":generated_tasks,"vehicle_alerts":vehicle_alerts(30),
        "stock_reorder_items":_below_reorder_count(),"automation_rules_evaluated":0,
        "note":"Configured rules are evaluated on event entry points in dry-run mode; no approval workflow is created or bypassed."}
