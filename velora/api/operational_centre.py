"""Permission-aware cross-functional operational centre.

Aggregates existing workflow approvals/tasks and safe document queues. It is a
read-only command centre: all business actions remain in their owning modules.
"""
from __future__ import annotations
from fastapi import FastAPI, Request
from ..exceptions import PermissionDenied
from ..permissions import get_session
from ..document.document import get_count, get_list

# DocTypes are optional by installation. Only records readable by the current
# session are included; a missing module or denied DocType is never bypassed.
QUEUES = [
    ("Finance", "Journal Entry", "Draft journals", {"docstatus": 0}, "#/app/Journal%20Entry"),
    ("Finance", "Sales Invoice", "Draft sales invoices", {"docstatus": 0}, "#/app/Sales%20Invoice"),
    ("Finance", "Purchase Invoice", "Draft purchase invoices", {"docstatus": 0}, "#/app/Purchase%20Invoice"),
    ("Finance", "Payment", "Draft payments", {"docstatus": 0}, "#/app/Payment"),
    ("Finance", "Finance Service Request", "Finance eRequests awaiting review", {"request_status": "Submitted"}, "#/app/Finance%20Service%20Request"),
    ("Finance", "Finance Service Request", "Finance eRequests awaiting approval", {"request_status": "Pending Approval"}, "#/app/Finance%20Service%20Request"),
    ("Procurement", "Purchase Order", "Draft purchase orders", {"docstatus": 0}, "#/app/Purchase%20Order"),
    ("Procurement", "Purchase Receipt", "Draft purchase receipts", {"docstatus": 0}, "#/app/Purchase%20Receipt"),
    ("HR", "Leave Application", "Pending leave applications", {"status": "Open"}, "#/app/Leave%20Application"),
    ("Payroll", "Payroll Run", "Payroll runs awaiting approval", {"status": "Pending Approval", "approval_status": "Pending"}, "#/app/Payroll%20Run"),
]

def _safe_count(doctype, filters):
    try:
        from ..meta.registry import registry
        meta = registry.get(doctype)
        # Validate that all filter fields exist before querying.
        valid = {f.fieldname for f in meta.fields} | {"name", "docstatus"}
        if any(k not in valid for k in filters):
            return None
        return int(get_count(doctype, filters=filters))
    except Exception:
        return None

def _safe_rows(doctype, filters, fields, limit=20):
    try:
        from ..meta.registry import registry
        meta = registry.get(doctype)
        valid = {f.fieldname for f in meta.fields} | {"name", "docstatus", "modified"}
        safe_fields = [f for f in fields if f in valid]
        return get_list(doctype, filters=filters, fields=safe_fields, order_by="modified desc", limit=limit)
    except Exception:
        return []

def operational_centre():
    session = get_session()
    approvals, tasks, exceptions = [], [], []
    try:
        from ..workflows import approval_inbox
        approvals = approval_inbox(150)
    except Exception:
        approvals = []
    try:
        from ..workflow_orchestration import list_tasks
        tasks = list_tasks("Open", 150)
    except Exception:
        tasks = []
    for area, doctype, label, filters, route in QUEUES:
        count = _safe_count(doctype, filters)
        if count is None:
            continue
        exceptions.append({"area": area, "doctype": doctype, "label": label,
                           "count": count, "route": route, "severity": "warning" if count else "normal"})
    # Workflow analytics is company-wide. Restrict it to designated management
    # roles; ordinary users still see their own approvals and assigned tasks.
    analytics_roles = {"Administrator", "System Manager", "Workflow Manager", "Executive"}
    workflow = None
    if session.user == "Administrator" or analytics_roles.intersection(session.roles):
        try:
            from ..workflows import workflow_analytics
            workflow = workflow_analytics()
        except Exception:
            workflow = None
    total_exceptions = sum(x["count"] for x in exceptions)
    return {
        "user": session.user,
        "summary": {"approvals": len(approvals), "assigned_tasks": len(tasks),
                    "draft_and_pending": total_exceptions,
                    "overdue_workflows": int(workflow.get("overdue_active_instances", 0) or 0) if workflow else None,
                    "active_workflows": int(workflow.get("active_instances", 0) or 0) if workflow else None},
        "approvals": [{"id": x.get("id"), "workflow": x.get("workflow"), "doctype": x.get("doctype"),
                       "document_name": x.get("document_name"), "state": x.get("state"),
                       "action": x.get("action"), "step": x.get("step"), "label": x.get("label"),
                       "route": f"#/app/{str(x.get('doctype','')).replace(' ', '%20')}/{str(x.get('document_name','')).replace(' ', '%20')}"}
                      for x in approvals],
        "tasks": [{"id": x.get("id"), "title": x.get("title"), "description": x.get("description"),
                   "due_on": x.get("due_on"), "instance_id": x.get("instance_id"), "status": x.get("status")}
                  for x in tasks],
        "exceptions": exceptions,
        "workflow": workflow,
        "read_only": True,
    }

def install_operational_centre_routes(app: FastAPI, run):
    @app.get("/api/operational-centre")
    def get_operational_centre(request: Request):
        return run(request, operational_centre)
