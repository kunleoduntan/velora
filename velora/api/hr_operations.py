"""Controlled HR operational, recruitment and workforce reporting endpoints.

These APIs expose reviewable operational data. They deliberately do not create
payroll journals, GL entries, or convert an accepted offer into an Employee.
"""
from __future__ import annotations

from datetime import date
from fastapi import Body, FastAPI, Request

from ..exceptions import PermissionDenied, ValidationError
from ..permissions import get_session


def _require_hr():
    session = get_session()
    roles = set(getattr(session, "roles", ()) or ())
    if session.user != "Administrator" and not roles.intersection({"System Manager", "HR Manager", "HR Officer"}):
        raise PermissionDenied("Only HR Manager, HR Officer or System Manager may access this HR operation.")


def _date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def install_hr_operations_routes(app: FastAPI, run):
    @app.get("/api/hr/recruitment/pipeline")
    def recruitment_pipeline(request: Request, requisition: str | None = None, department: str | None = None):
        def fn():
            _require_hr()
            from collections import Counter
            from velora import get_list
            req_filters = []
            if requisition:
                req_filters.append(["name", "=", requisition])
            if department:
                req_filters.append(["department", "=", department])
            requisitions = get_list("Job Requisition", filters=req_filters, fields=["name", "requisition_title", "department", "designation", "vacancy_count", "requisition_status", "target_start_date"], limit=10000, ignore_permissions=True)
            req_names = {x.get("name") for x in requisitions}
            app_filters = [["requisition", "in", sorted(req_names)]] if req_names else [["name", "=", "__no_matching_requisition__"]]
            applications = get_list("Job Application", filters=app_filters, fields=["name", "candidate", "requisition", "application_date", "application_stage", "assigned_recruiter", "offer"], limit=50000, ignore_permissions=True)
            offers = get_list("Job Offer", fields=["name", "application", "candidate", "requisition", "offer_date", "offer_expiry_date", "approval_status", "decision", "converted_employee"], limit=20000, ignore_permissions=True)
            if req_names:
                offers = [x for x in offers if x.get("requisition") in req_names]
            stage_counts = Counter(x.get("application_stage") or "Unknown" for x in applications)
            offer_counts = Counter(x.get("decision") or "Pending" for x in offers)
            today = date.today()
            open_reqs = [x for x in requisitions if x.get("requisition_status") == "Approved"]
            vacancy_total = sum(max(0, int(x.get("vacancy_count") or 0)) for x in open_reqs)
            accepted_not_converted = [x for x in offers if x.get("decision") == "Accepted" and not x.get("converted_employee")]
            expired_pending = [x for x in offers if x.get("decision") == "Pending" and _date(x.get("offer_expiry_date")) and _date(x.get("offer_expiry_date")) < today]
            return {"requisitions": requisitions, "applications": applications, "offers": offers,
                "summary": {"requisition_count": len(requisitions), "approved_requisitions": len(open_reqs),
                    "approved_vacancies": vacancy_total, "application_count": len(applications),
                    "applications_by_stage": dict(sorted(stage_counts.items())),
                    "offers_by_decision": dict(sorted(offer_counts.items())),
                    "accepted_offers_pending_employee_conversion": len(accepted_not_converted),
                    "expired_pending_offers": len(expired_pending)}}
        return run(request, fn)

    @app.post("/api/hr/recruitment/offers/{offer_name}/decision")
    def record_offer_decision(offer_name: str, request: Request, body: dict = Body(...)):
        def fn():
            _require_hr()
            from velora import get_doc
            decision = str(body.get("decision") or "").strip()
            if decision not in {"Accepted", "Declined"}:
                raise ValidationError("Decision must be Accepted or Declined.")
            offer = get_doc("Job Offer", offer_name, ignore_permissions=True)
            if offer.approval_status != "Approved":
                raise ValidationError("Only an approved Job Offer can receive a candidate decision.")
            if offer.decision != "Pending":
                raise ValidationError("This offer already has a recorded decision.")
            expiry = _date(getattr(offer, "offer_expiry_date", None))
            if expiry and expiry < date.today():
                raise ValidationError("This offer has expired. Reissue or extend it through the approved offer process.")
            offer.decision = decision
            if hasattr(offer, "save"):
                offer.save(ignore_permissions=True)
            # Acceptance is not an employment event. Employee creation and onboarding
            # remain a separately approved conversion process.
            return {"offer": offer.name, "decision": decision,
                "next_step": "Complete approved employee conversion and onboarding" if decision == "Accepted" else "Close or retain the application under recruitment policy",
                "employee_created": False}
        return run(request, fn)

    @app.get("/api/hr/leave/administration")
    def leave_administration(request: Request, employee: str | None = None, department: str | None = None):
        def fn():
            _require_hr()
            from collections import Counter
            from velora import get_list
            employee_filters = []
            if employee:
                employee_filters.append(["name", "=", employee])
            if department:
                employee_filters.append(["department", "=", department])
            employees = get_list("Employee", filters=employee_filters, fields=["name", "employee_name", "department", "company", "disabled"], limit=20000, ignore_permissions=True)
            names = {x.get("name") for x in employees}
            if not names:
                return {"allocations": [], "applications": [], "summary": {"employees": 0, "allocations": 0, "pending_requests": 0, "approved_days": 0, "available_days": 0}}
            allocations = get_list("Leave Allocation", filters=[["employee", "in", sorted(names)]], fields=["name", "employee", "leave_type", "period_start", "period_end", "allocated_days", "carry_forward_days", "adjustment_days", "used_days", "pending_days", "available_days", "allocation_status"], limit=50000, ignore_permissions=True)
            applications = get_list("Leave Application", filters=[["employee", "in", sorted(names)]], fields=["name", "employee", "leave_type", "from_date", "to_date", "total_days", "workflow_status", "payroll_treatment"], limit=50000, ignore_permissions=True)
            status_counts = Counter(x.get("workflow_status") or "Unknown" for x in applications)
            return {"employees": employees, "allocations": allocations, "applications": applications,
                "summary": {"employees": len(employees), "allocations": len(allocations),
                    "pending_requests": status_counts.get("Pending Approval", 0),
                    "approved_days": round(sum(float(x.get("total_days") or 0) for x in applications if x.get("workflow_status") in {"Approved", "Completed"}), 2),
                    "available_days": round(sum(float(x.get("available_days") or 0) for x in allocations if x.get("allocation_status") == "Approved"), 2),
                    "requests_by_status": dict(sorted(status_counts.items()))}}
        return run(request, fn)

    @app.get("/api/hr/leave/payroll-handoff-preview")
    def leave_payroll_handoff_preview(request: Request, start_date: str, end_date: str, company: str | None = None):
        def fn():
            _require_hr()
            from collections import defaultdict
            from velora import get_list
            start, end = _date(start_date), _date(end_date)
            if not start or not end or end < start:
                raise ValidationError("Provide a valid date range using YYYY-MM-DD; End Date cannot precede Start Date.")
            employees = get_list("Employee", filters=([["company", "=", company]] if company else []), fields=["name", "employee_name", "department", "company"], limit=20000, ignore_permissions=True)
            emp_map = {x.get("name"): x for x in employees}
            rows = get_list("Leave Application", filters=[["workflow_status", "in", ["Approved", "Completed"]], ["from_date", "<=", end.isoformat()], ["to_date", ">=", start.isoformat()]], fields=["name", "employee", "leave_type", "from_date", "to_date", "total_days", "workflow_status", "payroll_treatment"], limit=50000, ignore_permissions=True)
            result = []
            totals = defaultdict(float)
            for row in rows:
                emp = emp_map.get(row.get("employee"))
                if not emp:
                    continue
                treatment = row.get("payroll_treatment") or "Unclassified"
                days = float(row.get("total_days") or 0)
                totals[treatment] += days
                result.append({**row, "employee_name": emp.get("employee_name"), "department": emp.get("department"), "company": emp.get("company")})
            return {"period": {"start_date": start.isoformat(), "end_date": end.isoformat()}, "items": result,
                "summary": {"applications": len(result), "days_by_payroll_treatment": {k: round(v, 2) for k, v in sorted(totals.items())}},
                "posting_status": "Preview only. No Salary Slip, payroll transaction or General Ledger entry has been created."}
        return run(request, fn)

    @app.get("/api/hr/reports/workforce")
    def workforce_report(request: Request, start_date: str, end_date: str, company: str | None = None, department: str | None = None):
        def fn():
            _require_hr()
            from collections import Counter
            from velora import get_list
            start, end = _date(start_date), _date(end_date)
            if not start or not end or end < start:
                raise ValidationError("Provide a valid reporting date range; End Date cannot precede Start Date.")
            filters = []
            if company: filters.append(["company", "=", company])
            if department: filters.append(["department", "=", department])
            employees = get_list("Employee", filters=filters, fields=["name", "employee_name", "company", "department", "employee_type", "date_of_joining", "disabled"], limit=30000, ignore_permissions=True)
            names = {x.get("name") for x in employees}
            joiners = [x for x in employees if _date(x.get("date_of_joining")) and start <= _date(x.get("date_of_joining")) <= end]
            attendance = get_list("Attendance", filters=[["attendance_date", ">=", start.isoformat()], ["attendance_date", "<=", end.isoformat()]], fields=["name", "employee", "attendance_date", "status"], limit=100000, ignore_permissions=True) if names else []
            attendance = [x for x in attendance if x.get("employee") in names]
            leave = get_list("Leave Application", filters=[["from_date", "<=", end.isoformat()], ["to_date", ">=", start.isoformat()]], fields=["name", "employee", "total_days", "workflow_status", "leave_type"], limit=50000, ignore_permissions=True) if names else []
            leave = [x for x in leave if x.get("employee") in names]
            separations = get_list("Employee Separation", fields=["name", "employee", "last_working_date", "workflow_status", "reason"], limit=30000, ignore_permissions=True) if names else []
            separations = [x for x in separations if x.get("employee") in names and _date(x.get("last_working_date")) and start <= _date(x.get("last_working_date")) <= end and x.get("workflow_status") not in {"Draft", "Rejected"}]
            by_department = Counter(x.get("department") or "Unassigned" for x in employees if not x.get("disabled"))
            by_type = Counter(x.get("employee_type") or "Unclassified" for x in employees if not x.get("disabled"))
            attendance_counts = Counter(x.get("status") or "Unknown" for x in attendance)
            approved_leave_days = sum(float(x.get("total_days") or 0) for x in leave if x.get("workflow_status") in {"Approved", "Completed"})
            active = sum(1 for x in employees if not x.get("disabled"))
            return {"period": {"start_date": start.isoformat(), "end_date": end.isoformat()},
                "filters": {"company": company, "department": department},
                "summary": {"headcount": len(employees), "active_headcount": active, "joiners": len(joiners), "separations": len(separations),
                    "net_headcount_movement": len(joiners) - len(separations), "attendance_records": len(attendance),
                    "attendance_by_status": dict(sorted(attendance_counts.items())), "approved_leave_days": round(approved_leave_days, 2),
                    "leave_requests": len(leave)},
                "by_department": [{"department": k, "headcount": v} for k, v in sorted(by_department.items())],
                "by_employee_type": [{"employee_type": k, "headcount": v} for k, v in sorted(by_type.items())],
                "joiners": joiners, "separations": separations,
                "methodology": "Headcount is the current filtered Employee register; joiners and separations are events within the selected period. Net movement is joiners less qualifying separations."}
        return run(request, fn)
