"""Customer and Supplier portal: invitations and the data each signed-in contact may see.

Security rule, kept deliberately simple: a provider never reads a customer or supplier from the request. It looks up the
signed-in portal user's own *Portal Account* and uses the party stored there, so a contact can only ever see their own records.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timezone
from decimal import Decimal

from velora import get_doc, get_list, new_doc, throw
from velora.exceptions import PermissionDenied

ROLE = {"Customer": "Customer Portal", "Supplier": "Supplier Portal", "Employee": "Employee Portal"}
AGEING = (("Current", None, 0), ("1-30 days", 1, 30), ("31-60 days", 31, 60), ("61-90 days", 61, 90), ("Over 90 days", 91, None))


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def _day(v):
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


# ---- who is signed in -------------------------------------------------------------------------------------

def account_for(user: dict, portal_type: str) -> dict:
    """The signed-in user's active Portal Account of the expected type, or a refusal."""
    if ROLE[portal_type] not in (user.get("roles") or []):
        raise PermissionDenied(f"This area is for {portal_type.lower()} portal users.")
    rows = get_list("Portal Account", filters=[["email", "=", user["email"]]], fields=["name", "portal_type", "customer", "supplier", "employee", "status", "full_name"],
                    limit=1, ignore_permissions=True)
    row = rows[0] if rows else None
    if not row or row["status"] != "Active" or row["portal_type"] != portal_type or not row.get(portal_type.lower()):
        raise PermissionDenied("Your portal access is not active. Please contact the company.")
    return {**row, "party": row[portal_type.lower()]}


# ---- invitations (staff side) ---------------------------------------------------------------------------------

def _temp_password() -> str:
    from velora.controlplane.passwords import temporary_password
    return temporary_password()


def invite(email: str, full_name: str, portal_type: str, party: str) -> dict:
    """Create the portal sign-in and its Portal Account. The temporary password is returned once and stored nowhere."""
    from velora import portal as core
    if portal_type not in ROLE:
        throw("Portal must be Customer, Supplier or Employee.")
    if not party:
        throw(f"Select the {portal_type.lower()}.")
    if not get_list(portal_type, filters=[["name", "=", party]], fields=["name"], limit=1, ignore_permissions=True):
        throw(f"{portal_type} {party} does not exist.")
    password = _temp_password()
    user = core.create_portal_user(email, full_name, password, roles=[ROLE[portal_type]], must_change=True)
    try:
        doc = new_doc("Portal Account", email=user["email"], full_name=user["full_name"], portal_type=portal_type, status="Active",
                      last_invited=datetime.now(timezone.utc).replace(tzinfo=None), **{portal_type.lower(): party})
        doc.insert()
    except Exception:
        core.set_portal_user_status(user["email"], "suspended")
        raise
    return {"email": user["email"], "temporary_password": password, "account": doc.name}


def reset_password(email: str) -> dict:
    from velora import portal as core
    doc = get_doc("Portal Account", str(email).strip().lower())
    password = _temp_password()
    core.admin_set_password(doc.email, password, temporary=True)
    doc.last_invited = datetime.now(timezone.utc).replace(tzinfo=None)
    doc.save()
    return {"email": doc.email, "temporary_password": password}


def set_status(email: str, status: str) -> dict:
    from velora import portal as core
    if status not in ("Active", "Suspended"):
        throw("Status must be Active or Suspended.")
    doc = get_doc("Portal Account", str(email).strip().lower())
    core.set_portal_user_status(doc.email, "active" if status == "Active" else "suspended")
    doc.status = status
    doc.save()
    return {"email": doc.email, "status": status}


# ---- shared helpers -----------------------------------------------------------------------------------------

def _party_card(doctype: str, name: str) -> dict:
    rows = get_list(doctype, filters=[["name", "=", name]], limit=1, ignore_permissions=True,
                    fields=[f"{doctype.lower()}_name", "email", "phone", "currency", "billing_address", "payment_terms"] + (["credit_limit"] if doctype == "Customer" else []))
    return {"code": name, **(rows[0] if rows else {})}


def _invoice_rows(doctype: str, party: str, status: str | None = None) -> list[dict]:
    rows = get_list(doctype, filters=[["party", "=", party], ["docstatus", "=", 1]], order_by="invoice_date desc", limit=1000, ignore_permissions=True,
                    fields=["name", "invoice_date", "due_date", "currency", "grand_total", "amount_settled", "payment_status", "party_reference", "narration"])
    today, out = date.today(), []
    for r in rows:
        outstanding = _d(r["grand_total"]) - _d(r["amount_settled"])
        due = _day(r["due_date"] or r["invoice_date"])
        overdue_days = (today - due).days if outstanding > 0 and due < today else 0
        row = {**r, "outstanding": outstanding, "overdue_days": overdue_days, "state": "Paid" if outstanding <= 0 else ("Overdue" if overdue_days else "Open")}
        if status in (None, "", "all") or status.lower() == row["state"].lower():
            out.append(row)
    return out


def _ageing(rows: list[dict]) -> list[dict]:
    by_currency: dict[str, dict[str, Decimal]] = {}
    for r in rows:
        if r["outstanding"] <= 0:
            continue
        for label, low, high in AGEING:
            d = r["overdue_days"]
            if (low is None or d >= low) and (high is None or d <= high):
                by_currency.setdefault(r["currency"], {k[0]: Decimal("0") for k in AGEING})[label] += r["outstanding"]
                break
    return [{"currency": cur, "buckets": [{"label": k, "amount": v} for k, v in b.items()], "total": sum(b.values(), Decimal("0"))} for cur, b in by_currency.items()]


def _summary(rows: list[dict]) -> dict:
    open_rows = [r for r in rows if r["outstanding"] > 0]
    out: dict[str, dict] = {}
    for r in open_rows:
        s = out.setdefault(r["currency"], {"currency": r["currency"], "outstanding": Decimal("0"), "overdue": Decimal("0"), "open_invoices": 0})
        s["outstanding"] += r["outstanding"]
        s["open_invoices"] += 1
        if r["overdue_days"]:
            s["overdue"] += r["outstanding"]
    return {"open_invoices": len(open_rows), "overdue_invoices": sum(1 for r in open_rows if r["overdue_days"]), "by_currency": list(out.values())}


def _orders(doctype: str, party: str) -> list[dict]:
    return get_list(doctype, filters=[["party", "=", party], ["docstatus", "=", 1]], order_by="document_date desc", limit=500, ignore_permissions=True,
                    fields=["name", "document_date", "currency", "grand_total", "document_status", "narration"])


# ---- customer portal ----------------------------------------------------------------------------------------

def customer_overview(user, args):
    acc = account_for(user, "Customer")
    rows = _invoice_rows("Sales Invoice", acc["party"])
    complaints = get_list("Customer Complaint", filters=[["customer", "=", acc["party"]]], fields=["name", "resolution_status"], limit=500, ignore_permissions=True)
    return {"who": {"name": acc["full_name"], "email": user["email"]}, "party": _party_card("Customer", acc["party"]), "summary": _summary(rows), "ageing": _ageing(rows),
            "recent_invoices": rows[:6], "open_orders": sum(1 for o in _orders("Sales Order", acc["party"]) if o["document_status"] in ("Open", "Partially Processed")),
            "open_complaints": sum(1 for c in complaints if c["resolution_status"] not in ("Resolved", "Closed", "Rejected"))}


def customer_invoices(user, args):
    acc = account_for(user, "Customer")
    return {"items": _invoice_rows("Sales Invoice", acc["party"], (args or {}).get("status"))}


def customer_orders(user, args):
    return {"items": _orders("Sales Order", account_for(user, "Customer")["party"])}


def customer_complaints(user, args):
    acc = account_for(user, "Customer")
    items = get_list("Customer Complaint", filters=[["customer", "=", acc["party"]]], order_by="complaint_date desc", limit=200, ignore_permissions=True,
                     fields=["name", "complaint_date", "category", "severity", "description", "resolution_status", "resolution", "sales_invoice"])
    tickets = {t["reference_name"]: t for t in get_list("Support Ticket", filters=[["customer", "=", acc["party"]], ["reference_doctype", "=", "Customer Complaint"]], limit=500, ignore_permissions=True,
                                                        fields=["name", "reference_name", "status", "resolution_due"])}
    for item in items:
        t = tickets.get(item["name"])
        item["ticket"], item["ticket_status"] = (t["name"], t["status"]) if t else (None, None)
    return {"items": items}


COMPLAINT_CATEGORIES = ("Product Quality", "Wrong Item", "Short Delivery", "Late Delivery", "Pricing or Billing", "Service", "Warranty", "Other")


def customer_complaint_create(user, body):
    acc = account_for(user, "Customer")
    category, description = str(body.get("category") or ""), str(body.get("description") or "").strip()
    if category not in COMPLAINT_CATEGORIES or not description:
        throw("Choose a category and describe the problem.")
    invoice = body.get("sales_invoice") or None
    if invoice and not get_list("Sales Invoice", filters=[["name", "=", invoice], ["party", "=", acc["party"]], ["docstatus", "=", 1]], fields=["name"], limit=1, ignore_permissions=True):
        throw("That invoice is not on your account.")
    doc = new_doc("Customer Complaint", customer=acc["party"], complaint_date=date.today(), category=category,
                  severity=body.get("severity") if body.get("severity") in ("Low", "Medium", "High", "Critical") else "Medium",
                  description=description[:5000], sales_invoice=invoice, resolution_status="Open")
    doc.insert(ignore_permissions=True)
    return {"name": doc.name, "resolution_status": doc.resolution_status, "ticket": _open_support_ticket(doc, acc, user)}


def _open_support_ticket(complaint, acc, user):
    """Every portal complaint also opens a Support Ticket, so it gets an owner and a service-level clock. The complaint itself never fails because of this."""
    try:
        priority = {"Low": "Low", "Medium": "Medium", "High": "High", "Critical": "Urgent"}.get(complaint.severity, "Medium")
        category = complaint.category if get_list("Support Category", filters={"name": complaint.category}, fields=["name"], limit=1, ignore_permissions=True) else None
        ticket = new_doc("Support Ticket", subject=f"{complaint.category}: {complaint.description[:80]}", description=complaint.description, priority=priority, category=category,
                         source="Portal", requester_type="Customer", customer=acc["party"], requester_name=acc.get("full_name"), requester_email=user.get("email"),
                         reference_doctype="Customer Complaint", reference_name=complaint.name)
        ticket.insert(ignore_permissions=True)
        return ticket.name
    except Exception:  # noqa: BLE001
        return None


# ---- supplier portal ----------------------------------------------------------------------------------------

def supplier_overview(user, args):
    acc = account_for(user, "Supplier")
    rows = _invoice_rows("Purchase Invoice", acc["party"])
    orders = _orders("Purchase Order", acc["party"])
    return {"who": {"name": acc["full_name"], "email": user["email"]}, "party": _party_card("Supplier", acc["party"]), "summary": _summary(rows), "ageing": _ageing(rows),
            "recent_invoices": rows[:6], "open_orders": sum(1 for o in orders if o["document_status"] in ("Open", "Partially Processed"))}


def supplier_invoices(user, args):
    return {"items": _invoice_rows("Purchase Invoice", account_for(user, "Supplier")["party"], (args or {}).get("status"))}


def supplier_orders(user, args):
    return {"items": _orders("Purchase Order", account_for(user, "Supplier")["party"])}


# ---- employee portal ------------------------------------------------------------------------------------------------

def _employee(user):
    acc = account_for(user, "Employee")
    return acc, acc["party"]


def employee_overview(user, args):
    acc, code = _employee(user)
    rows = get_list("Employee", filters=[["name", "=", code]], limit=1, ignore_permissions=True,
                    fields=["employee_name", "designation", "department", "branch", "email", "phone", "mobile", "date_of_joining", "date_of_birth", "reports_to", "employee_type", "employment_status", "work_location"])
    e = rows[0] if rows else {}
    manager = None
    if e.get("reports_to"):
        m = get_list("Employee", filters=[["name", "=", e["reports_to"]]], fields=["employee_name"], limit=1, ignore_permissions=True)
        manager = m[0]["employee_name"] if m else None
    joined = _day(e["date_of_joining"]) if e.get("date_of_joining") else None
    today = date.today()
    service_years = round((today - joined).days / 365.25, 1) if joined else None
    slips = get_list("Salary Slip", filters=[["employee", "=", code], ["docstatus", "=", 1]], fields=["name", "period_start", "period_end", "currency", "net_pay", "status"], order_by="period_end desc", limit=1, ignore_permissions=True)
    leave = get_list("Leave Application", filters=[["employee", "=", code]], fields=["name", "workflow_status", "total_days"], limit=500, ignore_permissions=True)
    return {"who": {"name": acc["full_name"], "email": user["email"]}, "profile": {**{k: v for k, v in e.items() if k != "date_of_birth"}, "code": code, "manager": manager, "service_years": service_years},
            "latest_payslip": slips[0] if slips else None, "leave": {"requests": len(leave), "pending": sum(1 for r in leave if (r.get("workflow_status") or "").lower() in ("pending", "submitted", "pending approval", "draft"))}}


def employee_payslips(user, args):
    _, code = _employee(user)
    return {"items": get_list("Salary Slip", filters=[["employee", "=", code], ["docstatus", "=", 1]], order_by="period_end desc", limit=60, ignore_permissions=True,
                              fields=["name", "period_start", "period_end", "currency", "gross_earnings", "employee_deductions", "net_pay", "status"])}


def employee_leave(user, args):
    _, code = _employee(user)
    return {"items": get_list("Leave Application", filters=[["employee", "=", code]], order_by="from_date desc", limit=100, ignore_permissions=True,
                              fields=["name", "leave_type", "from_date", "to_date", "total_days", "workflow_status", "reason"])}


def employee_holidays(user, args):
    import json as _json
    acc, code = _employee(user)
    where = (get_list("Employee", filters=[["name", "=", code]], fields=["work_location"], limit=1, ignore_permissions=True) or [{}])[0].get("work_location")
    today, days = date.today(), []
    for h in get_list("Holiday List", filters=[["disabled", "=", 0]], fields=["holiday_list_name", "work_location", "holiday_dates"], limit=50, ignore_permissions=True):
        if h.get("work_location") and h["work_location"] != where:
            continue
        raw = h["holiday_dates"]
        try:
            rows = raw if isinstance(raw, list) else _json.loads(raw or "[]")
        except ValueError:
            rows = []
        for r in rows:
            d = str((r.get("date") if isinstance(r, dict) else r) or "")[:10]
            if d and d >= today.isoformat():
                days.append({"date": d, "list": h["holiday_list_name"]})
    return {"items": sorted({d["date"]: d for d in days}.values(), key=lambda d: d["date"])[:40]}


def employee_celebrations(user, args):
    """Colleagues' birthdays and work anniversaries in the next 30 days: first names and dates only."""
    _employee(user)
    from velora_erp.engagement import service as eng
    return {"items": eng.upcoming_employee_celebrations(date.today(), 30)}


# ---- messages and preferences (every kind of portal user) -------------------------------------------------------------------------

def _any_account(user):
    for t in ("Customer", "Supplier", "Employee"):
        if ROLE[t] in (user.get("roles") or []):
            return t, account_for(user, t)
    raise PermissionDenied("Your portal access is not active. Please contact the company.")


def _addresses(user, ptype, acc) -> list[str]:
    row = get_list(ptype, filters=[["name", "=", acc["party"]]], fields=["email"], limit=1, ignore_permissions=True)
    return sorted({a.strip().lower() for a in (user["email"], row[0].get("email") if row else "") if a and a.strip()})


def _notify():
    try:
        from velora.meta.registry import registry
        from velora_notify.broadcast import service as bc
        return bc if registry.exists("Communication Opt-Out") else None
    except Exception:  # noqa: BLE001
        return None


def portal_messages(user, args):
    ptype, acc = _any_account(user)
    if not _has_doctype("Engagement Log"):
        return {"items": []}
    return {"items": get_list("Engagement Log", filters=[["party_type", "=", ptype], ["party", "=", acc["party"]], ["status", "in", ["Queued", "Released"]]], order_by="moment_date desc", limit=50,
                              ignore_permissions=True, fields=["name", "moment_date", "kind", "subject", "message"])}


def _has_doctype(name: str) -> bool:
    from velora.meta.registry import registry
    return registry.exists(name)


def portal_preferences(user, args):
    ptype, acc = _any_account(user)
    bc = _notify()
    if bc is None:
        return {"available": False, "messages_enabled": True, "addresses": []}
    addrs = _addresses(user, ptype, acc)
    return {"available": True, "messages_enabled": not any(bc.opted_out(a, "Email") for a in addrs), "addresses": addrs}


def portal_preferences_save(user, body):
    ptype, acc = _any_account(user)
    bc = _notify()
    if bc is None:
        throw("Message preferences are not available.")
    if not isinstance(body.get("messages_enabled"), bool):
        throw("Choose whether to receive messages.")
    for a in _addresses(user, ptype, acc):
        if body["messages_enabled"]:
            for r in get_list("Communication Opt-Out", filters=[["address", "=", a], ["channel", "in", ["Email", "All channels"]]], fields=["name"], limit=10, ignore_permissions=True):
                get_doc("Communication Opt-Out", r["name"], ignore_permissions=True).delete(ignore_permissions=True)
        else:
            bc.record_opt_out(a, "Email", "Unsubscribe link", "Chosen by the person in the portal")
    return portal_preferences(user, {})


def register():
    """Register the portal data providers (safe to call more than once)."""
    from velora import portal as core
    for key, fn in (("customer.overview", customer_overview), ("customer.invoices", customer_invoices), ("customer.orders", customer_orders),
                    ("customer.complaints", customer_complaints), ("supplier.overview", supplier_overview), ("supplier.invoices", supplier_invoices),
                    ("supplier.orders", supplier_orders), ("employee.overview", employee_overview), ("employee.payslips", employee_payslips), ("employee.leave", employee_leave),
                    ("employee.holidays", employee_holidays), ("employee.celebrations", employee_celebrations), ("portal.messages", portal_messages),
                    ("portal.preferences", portal_preferences)):
        core.register_resource_provider(key, fn)
    core.register_action_provider("customer.complaint", customer_complaint_create)
    core.register_action_provider("portal.preferences", portal_preferences_save)
