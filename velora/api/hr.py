"""HR-specific read-only preview services for controlled workforce operations."""
from __future__ import annotations

from fastapi import Body, FastAPI, Request

from ..exceptions import PermissionDenied, ValidationError
from ..permissions import get_session


def _require_hr_preview_access():
    session = get_session()
    roles = set(getattr(session, "roles", ()) or ())
    if session.user != "Administrator" and not roles.intersection({"System Manager", "HR Manager", "HR Officer"}):
        raise PermissionDenied("Only HR Manager, HR Officer or System Manager may access this HR operation.")


def install_hr_routes(app: FastAPI, run):
    @app.post("/api/hr/leave-policy/preview")
    def preview_leave_policy(request: Request, body: dict = Body(...)):
        def fn():
            _require_hr_preview_access()
            from datetime import date
            from velora import get_doc
            from velora_erp.hr.doctype.leave_policy_assignment.leave_policy_assignment import (
                _eligible_employees, _employee_context, _date,
            )

            policy_name = str(body.get("policy") or "").strip()
            period_name = str(body.get("leave_period") or "").strip()
            assignment_date = _date(body.get("assignment_date"))
            if not policy_name or not period_name or not assignment_date:
                raise ValidationError("Policy, Leave Period and Assignment Date are required.")
            policy = get_doc("Leave Policy", policy_name, ignore_permissions=True)
            period = get_doc("Leave Period", period_name, ignore_permissions=True)
            if policy.status != "Active":
                raise ValidationError("Only an Active Leave Policy can be previewed for assignment.")
            if period.period_status != "Open":
                raise ValidationError("Only an Open Leave Period can receive policy allocations.")
            start, end = _date(period.from_date), _date(period.to_date)
            if not start or not end or end < start:
                raise ValidationError("The selected Leave Period has an invalid date range.")
            if policy.company and period.company and policy.company != period.company:
                raise ValidationError("Leave Policy and Leave Period must belong to the same legal entity.")
            if assignment_date < _date(policy.effective_from) or (_date(policy.effective_to) and assignment_date > _date(policy.effective_to)):
                raise ValidationError("Assignment Date falls outside the Leave Policy effective period.")
            if start < _date(policy.effective_from) or (_date(policy.effective_to) and end > _date(policy.effective_to)):
                raise ValidationError("Leave Period must fall within the Leave Policy effective period.")
            selection_mode = body.get("selection_mode") or "All Eligible Employees"
            selected = body.get("selected_employees") or []
            if selection_mode == "Selected Employees" and not selected:
                raise ValidationError("Select at least one employee.")
            employees = _eligible_employees(policy, selection_mode, selected, start, False, assignment_date, end)
            if len(employees) > 1000:
                raise ValidationError("A single policy assignment is limited to 1,000 employees. Split larger populations into controlled assignments.")
            from velora import get_list
            existing = get_list("Leave Allocation", filters=[["employee", "in", [e.name for e in employees]]],
                fields=["name", "employee", "leave_type", "period_start", "period_end", "allocation_status"],
                limit=100000, ignore_permissions=True) if employees else []
            rows = []
            for employee in employees:
                context = {"department": getattr(employee, "department", None), "designation": getattr(employee, "designation", None)}
                for entitlement in list(policy.entitlements or []):
                    leave_type = entitlement.get("leave_type") if isinstance(entitlement, dict) else entitlement.leave_type
                    conflict = any(
                        row.get("employee") == employee.name and row.get("leave_type") == leave_type
                        and _date(row.get("period_start")) and _date(row.get("period_end"))
                        and start <= _date(row.get("period_end")) and end >= _date(row.get("period_start"))
                        for row in existing
                    )
                    amount = entitlement.get("annual_entitlement_days", 0) if isinstance(entitlement, dict) else entitlement.annual_entitlement_days
                    method = entitlement.get("proration_method", "Full Entitlement") if isinstance(entitlement, dict) else entitlement.proration_method
                    from velora_erp.hr.doctype.leave_policy_assignment.leave_policy_assignment import _prorated_days
                    days = _prorated_days(amount, method, employee, start, end)
                    rows.append({
                        "employee": employee.name,
                        "employee_name": getattr(employee, "employee_name", employee.name),
                        "department": context.get("department"),
                        "designation": context.get("designation"),
                        "leave_type": leave_type,
                        "entitlement_days": days,
                        "result": "Skipped - overlapping allocation exists" if conflict else ("Skipped - no entitlement after proration" if days <= 0 else "Will Create"),
                    })
            return {
                "policy": policy.name, "policy_name": policy.policy_name, "policy_version": policy.policy_version,
                "leave_period": period.name, "period_start": str(start), "period_end": str(end),
                "eligible_employee_count": len(employees), "allocation_count": sum(1 for r in rows if r["result"] == "Will Create"),
                "skipped_count": sum(1 for r in rows if r["result"].startswith("Skipped")), "rows": rows,
            }
        return run(request, fn)

    def _require_hr_integration_access(write=True):
        session=get_session(); roles=set(getattr(session,"roles",()) or ())
        allowed={"System Manager","HR Manager"} | ({"HR Officer"} if not write else set())
        if write: allowed.add("API:write")
        if session.user!="Administrator" and not roles.intersection(allowed):
            raise PermissionDenied("Attendance integration administration requires HR Manager or System Manager; API clients require the write scope.")

    @app.get("/api/hr/attendance-integrations/providers")
    def attendance_integration_providers(request: Request):
        def fn():
            _require_hr_integration_access(write=False)
            from velora_erp.hr.attendance_integrations import PROVIDERS
            return PROVIDERS
        return run(request, fn)

    @app.post("/api/hr/attendance-integrations/{integration}/punches")
    def receive_attendance_punches(integration: str, request: Request, body: dict = Body(...)):
        def fn():
            _require_hr_integration_access(write=True)
            from velora_erp.hr.attendance_integrations import ingest_events
            events=body.get("events") if isinstance(body,dict) else None
            return ingest_events(integration, events, source="Normalised Event Push")
        return run(request, fn)

    @app.post("/api/hr/attendance-integrations/{integration}/reconcile")
    def reconcile_attendance_punches(integration: str, request: Request, body: dict = Body(default={} )):
        def fn():
            _require_hr_integration_access(write=True)
            from velora_erp.hr.attendance_integrations import reconcile_punches
            return reconcile_punches(integration, body.get("start_date"), body.get("end_date"), body.get("limit",2000))
        return run(request, fn)

    @app.post("/api/hr/attendance-integrations/{integration}/test-connection")
    def test_attendance_integration(integration: str, request: Request):
        def fn():
            _require_hr_integration_access(write=True)
            from velora_erp.hr.attendance_integrations import test_biotime_connection
            return test_biotime_connection(integration)
        return run(request, fn)

    @app.get("/api/hr/attendance-integrations/{integration}/mapping-suggestions")
    def attendance_mapping_suggestions(integration: str, request: Request, limit: int = 200):
        def fn():
            _require_hr_integration_access(write=False)
            from velora_erp.hr.attendance_integrations import suggest_device_user_mappings
            return suggest_device_user_mappings(integration, limit)
        return run(request, fn)

    @app.get("/api/hr/attendance-integrations/health/summary")
    def attendance_integration_health(request: Request):
        def fn():
            _require_hr_integration_access(write=False)
            from velora import get_list
            integrations=get_list("Attendance Integration",fields=["name","integration_name","provider","health_status","last_sync_on","last_health_check","consecutive_failures","auto_sync_enabled"],limit=1000,ignore_permissions=True)
            devices=get_list("Attendance Device",fields=["name","device_name","serial_number","health_status","last_seen_on","unmapped_user_count"],limit=5000,ignore_permissions=True)
            return {"integrations":integrations,"devices":devices,
                "counts":{"integrations":len(integrations),"healthy":sum(1 for x in integrations if x.get("health_status")=="Healthy"),"failed":sum(1 for x in integrations if x.get("health_status")=="Failed"),"devices":len(devices),"offline_devices":sum(1 for x in devices if x.get("health_status")=="Offline")}}
        return run(request, fn)

    @app.post("/api/hr/attendance-integrations/{integration}/sync-biotime")
    def sync_zkteco_biotime(integration: str, request: Request, body: dict = Body(...)):
        def fn():
            _require_hr_integration_access(write=True)
            from velora_erp.hr.attendance_integrations import sync_biotime_report
            if not body.get("start_date") or not body.get("end_date"):
                raise ValidationError("start_date and end_date are required (YYYY-MM-DD).")
            return sync_biotime_report(integration,body["start_date"],body["end_date"])
        return run(request, fn)


    def _performance_portal_employee():
        """Resolve the authenticated user's explicit Employee mapping; never trust a client-supplied employee ID."""
        from velora import get_list
        session=get_session()
        if session.user == "Administrator":
            raise PermissionDenied("Administrator must use the HR administration workspace, not an employee portal identity.")
        rows=get_list("Employee",filters=[["user_account","=",session.user]],fields=["name","employee_name","department","designation","user_account","disabled","employment_status"],limit=2,ignore_permissions=True)
        if len(rows)!=1 or rows[0].get("disabled") or rows[0].get("employment_status")=="Left":
            raise PermissionDenied("Your login is not linked to exactly one active Employee record. Contact HR to configure the Employee System User Account.")
        return {k: v for k, v in rows[0].items() if k not in ("disabled", "employment_status")}

    @app.get("/api/hr/me/overview")
    def employee_self_service_overview(request: Request):
        def fn():
            employee = _performance_portal_employee()
            from velora import get_list
            employee_name = employee["name"]
            leave = get_list("Leave Application", filters=[["employee", "=", employee_name]],
                fields=["name", "leave_type", "from_date", "to_date", "total_days", "workflow_status", "payroll_treatment"],
                limit=200, ignore_permissions=True)
            attendance = get_list("Attendance", filters=[["employee", "=", employee_name]],
                fields=["name", "attendance_date", "status", "worked_hours", "approval_status"],
                order_by="attendance_date desc", limit=100, ignore_permissions=True)
            documents = get_list("Employee Document", filters=[["employee", "=", employee_name]],
                fields=["name", "document_type", "document_title", "issue_date", "expiry_date", "verification_status"],
                order_by="expiry_date asc", limit=100, ignore_permissions=True)
            allocations = get_list("Leave Allocation", filters=[["employee", "=", employee_name], ["allocation_status", "=", "Approved"]],
                fields=["name", "leave_type", "period_start", "period_end", "allocated_days", "carry_forward_days", "adjustment_days"], limit=1000, ignore_permissions=True)
            employee_assets = get_list("Employee Asset Assignment", filters=[["employee", "=", employee_name]],
                fields=["name", "asset_reference", "asset_description", "asset_category", "serial_number", "assigned_on", "expected_return_date", "assignment_status", "condition_on_issue", "condition_on_return"], limit=1000, ignore_permissions=True)
            from datetime import date, timedelta
            today = date.today()
            expiry_dates = [date.fromisoformat(str(x["expiry_date"])[:10]) for x in documents if x.get("expiry_date")]
            return {"employee": employee, "leave_applications": leave, "leave_allocations": allocations, "assets": employee_assets, "attendance": attendance,
                "documents": documents, "summary": {"leave_requests": len(leave),
                "pending_leave": sum(1 for x in leave if x.get("workflow_status") in ("Draft", "Pending Approval")),
                "attendance_records": len(attendance),
                "expired_documents": sum(1 for x in expiry_dates if x < today),
                "documents_expiring_30_days": sum(1 for x in expiry_dates if today <= x <= today + timedelta(days=30))}}
        return run(request, fn)

    @app.get("/api/hr/me/requests")
    def employee_self_service_requests(request: Request):
        def fn():
            employee = _performance_portal_employee()
            from velora import get_list
            rows = get_list("HR Service Request", filters=[["employee", "=", employee["name"]]],
                fields=["name", "request_type", "subject", "priority", "request_status", "assigned_to", "resolution", "resolved_on"],
                order_by="modified desc", limit=200, ignore_permissions=True)
            return {"items": rows, "total": len(rows)}
        return run(request, fn)

    @app.post("/api/hr/me/requests")
    def employee_create_self_service_request(request: Request, body: dict = Body(...)):
        def fn():
            employee = _performance_portal_employee()
            from velora import new_doc
            request_type = str(body.get("request_type") or "Other").strip()
            subject = str(body.get("subject") or "").strip()
            details = str(body.get("details") or "").strip()
            allowed = {"Personal Information Update", "Employment Letter", "Salary Confirmation Letter", "Document Request", "Leave Query", "Attendance Correction", "Benefits Query", "Other"}
            if request_type not in allowed or not subject or not details:
                raise ValidationError("Choose a valid request type and provide both Subject and Details.")
            doc = new_doc("HR Service Request", employee=employee["name"], request_type=request_type,
                subject=subject[:200], details=details[:10000], priority=body.get("priority") if body.get("priority") in ("Low", "Normal", "High", "Urgent") else "Normal",
                request_status="Open")
            doc.insert(ignore_permissions=True)
            return {"name": doc.name, "request_status": doc.request_status}
        return run(request, fn)

    @app.get("/api/hr/me/payslips")
    def employee_self_service_payslips(request: Request):
        def fn():
            employee = _performance_portal_employee()
            from velora import get_list, get_doc
            rows = get_list("Salary Slip", filters=[["employee", "=", employee["name"]], ["status", "in", ["Posted", "Partially Paid", "Paid"]]],
                fields=["name", "period_start", "period_end", "currency", "gross_earnings", "employee_deductions", "loan_repayments", "advance_recoveries", "net_pay", "paid_amount", "outstanding_amount", "status"],
                order_by="period_end desc", limit=120, ignore_permissions=True)
            result = []
            for row in rows:
                slip = get_doc("Salary Slip", row["name"], ignore_permissions=True)
                lines = []
                for line in list(getattr(slip, "lines", None) or []):
                    if getattr(line, "hide_on_payslip", 0):
                        continue    # e.g. employer pension expense/liability: posted, but not shown to the employee
                    lines.append({"component": getattr(line, "component_name", None) or getattr(line, "component_code", None), "component_code": getattr(line, "component_code", None),
                        "component_type": getattr(line, "component_type", None), "amount": getattr(line, "amount", 0),
                        "is_employer_contribution": getattr(line, "component_type", None) == "Employer Contribution"})
                result.append({**row, "lines": lines})
            return {"items": result, "total": len(result)}
        return run(request, fn)

    @app.post("/api/hr/me/leave-applications")
    def employee_submit_leave_application(request: Request, body: dict = Body(...)):
        def fn():
            employee = _performance_portal_employee()
            from datetime import date
            from velora import get_list, new_doc
            leave_type = str(body.get("leave_type") or "").strip()
            start = str(body.get("from_date") or "")[:10]
            end = str(body.get("to_date") or "")[:10]
            reason = str(body.get("reason") or "").strip()
            if not leave_type or not start or not end or not reason:
                raise ValidationError("Leave Type, From Date, To Date and Reason are required.")
            try:
                start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
            except ValueError:
                raise ValidationError("Leave dates must use YYYY-MM-DD format.")
            if end_date < start_date:
                raise ValidationError("To Date cannot be earlier than From Date.")
            allocations = get_list("Leave Allocation", filters=[["employee", "=", employee["name"]], ["leave_type", "=", leave_type], ["allocation_status", "=", "Approved"]],
                fields=["name", "period_start", "period_end"], limit=1000, ignore_permissions=True)
            allocation = next((x for x in allocations if str(x.get("period_start") or "")[:10] <= start and str(x.get("period_end") or "")[:10] >= end), None)
            if not allocation:
                raise ValidationError("No approved leave allocation covers the selected dates. Contact HR before submitting this request.")
            doc = new_doc("Leave Application", employee=employee["name"], leave_type=leave_type, leave_allocation=allocation["name"],
                from_date=start, to_date=end, half_day=1 if body.get("half_day") else 0,
                half_day_period=body.get("half_day_period") if body.get("half_day") else None,
                reason=reason[:5000], supporting_document=str(body.get("supporting_document") or "")[:500], workflow_status="Pending Approval")
            doc.insert(ignore_permissions=True)
            return {"name": doc.name, "workflow_status": doc.workflow_status, "total_days": doc.total_days, "payroll_treatment": doc.payroll_treatment}
        return run(request, fn)

    @app.get("/api/hr/workforce/dashboard")
    def hr_workforce_dashboard(request: Request, company: str | None = None, department: str | None = None):
        def fn():
            _require_hr_preview_access()
            from datetime import date
            from velora import get_list
            filters = []
            if company: filters.append(["company", "=", company])
            if department: filters.append(["department", "=", department])
            employees = get_list("Employee", filters=filters, fields=["name", "disabled", "employee_type", "department", "date_of_joining"], limit=20000, ignore_permissions=True)
            employee_names = [x.get("name") for x in employees if x.get("name")]
            separations = get_list("Employee Separation", fields=["name", "employee", "workflow_status", "last_working_date", "reason"], limit=10000, ignore_permissions=True)
            relations = get_list("Employee Relations Case", fields=["name", "employee", "case_status", "case_type", "reported_date"], limit=10000, ignore_permissions=True)
            leave = get_list("Leave Application", fields=["name", "employee", "workflow_status", "total_days", "from_date", "to_date"], limit=20000, ignore_permissions=True)
            assets = get_list("Employee Asset Assignment", fields=["name", "employee", "assignment_status", "asset_category", "expected_return_date"], limit=20000, ignore_permissions=True)
            if employee_names:
                allowed = set(employee_names)
                separations = [x for x in separations if x.get("employee") in allowed]
                leave = [x for x in leave if x.get("employee") in allowed]
                assets = [x for x in assets if x.get("employee") in allowed]
                relations = [x for x in relations if x.get("employee") in allowed]
            else:
                separations, leave, assets, relations = [], [], [], []
            from velora.permissions import has_permission
            from velora.meta.registry import registry as _registry
            # these lists are read with system rights for speed; only count what the caller could open themselves
            if not has_permission(_registry.get("Employee Relations Case"), "read"): relations = []
            if not has_permission(_registry.get("Employee Separation"), "read"): separations = []
            active = sum(1 for x in employees if not x.get("disabled"))
            return {"headcount": len(employees), "active_headcount": active,
                "by_department": [{"department": d or "Unassigned", "headcount": sum(1 for x in employees if (x.get("department") or "Unassigned") == (d or "Unassigned"))} for d in sorted({x.get("department") or "Unassigned" for x in employees})],
                "separations": {"total": len(separations), "open": sum(x.get("workflow_status") not in ("Closed", "Rejected") for x in separations)},
                "employee_relations": {"total": len(relations), "open": sum(x.get("case_status") not in ("Closed", "Withdrawn") for x in relations)},
                "leave": {"pending": sum(x.get("workflow_status") == "Pending Approval" for x in leave), "approved_days": round(sum(float(x.get("total_days") or 0) for x in leave if x.get("workflow_status") in ("Approved", "Completed")), 2)},
                "assets": {"issued": sum(x.get("assignment_status") == "Issued" for x in assets), "overdue_return": sum(1 for x in assets if x.get("assignment_status") == "Issued" and x.get("expected_return_date") and str(x.get("expected_return_date"))[:10] < date.today().isoformat())}}
        return run(request, fn)

    def _performance_direct_reports(manager_name):
        from datetime import date
        from velora import get_list
        today=date.today().isoformat()
        assignments=get_list("Reporting Assignment",filters=[["reports_to","=",manager_name],["assignment_status","=","Approved"],["is_primary","=",1]],fields=["employee","effective_from","effective_to"],limit=5000,ignore_permissions=True)
        names=sorted({a.get("employee") for a in assignments if a.get("employee") and str(a.get("effective_from") or "0001-01-01")<=today and (not a.get("effective_to") or str(a.get("effective_to"))>=today)})
        return names

    @app.get("/api/hr/performance/me")
    def employee_performance_portal(request: Request):
        def fn():
            employee=_performance_portal_employee(); employee_name=employee["name"]
            from velora import get_list
            goals=get_list("Performance Goal",filters=[["employee","=",employee_name]],fields=["name","goal_title","cycle","goal_level","goal_type","measure","baseline","target_value","actual_value","progress_percent","weight","status","due_date","evidence","parent_goal"],limit=2000,ignore_permissions=True)
            reviews=get_list("Performance Review",filters=[["employee","=",employee_name]],fields=["name","review_code","cycle","review_type","review_status","overall_score","overall_rating","self_assessment","manager_summary","strengths","improvement_areas","employee_acknowledged","employee_comments"],limit=500,ignore_permissions=True)
            checkins=get_list("Performance Check In",filters=[["employee","=",employee_name]],fields=["name","cycle","goal","check_in_date","progress_summary","achievements","blockers","wellbeing_pulse","next_check_in","visibility"],limit=1000,ignore_permissions=True)
            checkins=[x for x in checkins if x.get("visibility")!="HR Restricted"]
            competencies=get_list("Employee Competency Assessment",filters=[["employee","=",employee_name]],fields=["name","competency","cycle","current_level","required_level","gap_level","development_priority","status"],limit=2000,ignore_permissions=True)
            plans=get_list("Performance Improvement Plan",filters=[["employee","=",employee_name]],fields=["name","review","status","start_date","end_date"],limit=200,ignore_permissions=True)
            return {"employee":{"id":employee_name,"name":employee.get("employee_name"),"department":employee.get("department"),"designation":employee.get("designation")},"goals":goals,"reviews":reviews,"check_ins":checkins,"competency_assessments":competencies,"improvement_plans":plans,"summary":{"goals":len(goals),"goals_at_risk":sum(1 for x in goals if x.get("status")=="At Risk"),"average_goal_progress":round(sum(float(x.get("progress_percent") or 0) for x in goals)/len(goals),1) if goals else 0,"reviews_pending_acknowledgement":sum(1 for x in reviews if x.get("review_status") in ("Approved","Acknowledged") and not x.get("employee_acknowledged")),"open_competency_gaps":sum(1 for x in competencies if int(x.get("gap_level") or 0)>0)}}
        return run(request,fn)

    @app.post("/api/hr/performance/me/goals/{goal_name}/progress")
    def employee_update_goal(goal_name: str, request: Request, body: dict = Body(...)):
        def fn():
            employee=_performance_portal_employee()
            from velora import get_doc
            from datetime import date
            goal=get_doc("Performance Goal",goal_name,ignore_permissions=True)
            if goal.employee!=employee["name"]: raise PermissionDenied("Employees may update only their own assigned goals.")
            if goal.status in ("Draft","Cancelled","Not Achieved"): raise ValidationError("This goal is not open for progress updates.")
            if body.get("progress_percent") is not None:
                progress=float(body["progress_percent"])
                if progress<0 or progress>100: raise ValidationError("Progress must be between 0 and 100%.")
                goal.progress_percent=progress
            if body.get("actual_value") is not None: goal.actual_value=float(body["actual_value"])
            if body.get("evidence") is not None: goal.evidence=str(body["evidence"])[:10000]
            if body.get("status") in ("In Progress","At Risk","Completed"): goal.status=body["status"]
            goal.last_check_in=date.today().isoformat()
            goal.save(ignore_permissions=True)
            return {"goal":goal.name,"progress_percent":goal.progress_percent,"actual_value":goal.actual_value,"status":goal.status,"last_check_in":goal.last_check_in}
        return run(request,fn)

    @app.post("/api/hr/performance/me/check-ins")
    def employee_create_performance_checkin(request: Request, body: dict = Body(...)):
        def fn():
            employee=_performance_portal_employee()
            from velora import get_doc,new_doc
            from datetime import date
            cycle_name=str(body.get("cycle") or "").strip()
            if not cycle_name: raise ValidationError("Performance Cycle is required.")
            cycle=get_doc("Performance Cycle",cycle_name,ignore_permissions=True)
            if cycle.status in ("Draft","Cancelled","Closed"): raise ValidationError("The selected Performance Cycle is not open for check-ins.")
            goal_name=body.get("goal")
            if goal_name:
                goal=get_doc("Performance Goal",goal_name,ignore_permissions=True)
                if goal.employee!=employee["name"]: raise PermissionDenied("A check-in may only reference one of your own goals.")
            doc=new_doc("Performance Check In",employee=employee["name"],cycle=cycle_name,goal=goal_name,check_in_date=date.today().isoformat(),progress_summary=str(body.get("progress_summary") or "")[:10000],achievements=str(body.get("achievements") or "")[:10000],blockers=str(body.get("blockers") or "")[:10000],wellbeing_pulse=body.get("wellbeing_pulse") if body.get("wellbeing_pulse") in ("Positive","Neutral","Needs Attention") else None,next_check_in=body.get("next_check_in"),visibility="Employee and Manager")
            doc.insert(ignore_permissions=True)
            return {"name":doc.name,"employee":employee["name"],"cycle":cycle_name,"check_in_date":doc.check_in_date}
        return run(request,fn)

    @app.post("/api/hr/performance/me/reviews/{review_name}/acknowledge")
    def employee_acknowledge_performance_review(review_name: str, request: Request, body: dict = Body(default={} )):
        def fn():
            employee=_performance_portal_employee()
            from velora import get_doc
            review=get_doc("Performance Review",review_name,ignore_permissions=True)
            if review.employee!=employee["name"]: raise PermissionDenied("Employees may acknowledge only their own reviews.")
            if review.review_status not in ("Approved","Acknowledged","Closed"): raise ValidationError("Only an approved review can be acknowledged.")
            review.employee_acknowledged=1
            review.employee_comments=str(body.get("comments") or "")[:10000]
            if review.review_status=="Approved": review.review_status="Acknowledged"
            review.save(ignore_permissions=True)
            return {"review":review.name,"employee_acknowledged":True,"review_status":review.review_status}
        return run(request,fn)

    @app.get("/api/hr/performance/manager/team")
    def manager_team_performance_portal(request: Request, cycle: str | None = None):
        def fn():
            manager=_performance_portal_employee(); session=get_session(); roles=set(getattr(session,"roles",()) or ())
            if session.user!="Administrator" and not roles.intersection({"Department Manager","HR Manager","HR Officer","System Manager"}):
                raise PermissionDenied("Team Performance access requires a manager or authorised HR role.")
            from velora import get_list
            reports=_performance_direct_reports(manager["name"])
            if not reports: return {"manager":manager["name"],"direct_reports":[],"summary":{"employees":0,"goals":0,"goals_at_risk":0,"reviews_pending":0}}
            goals=get_list("Performance Goal",filters=[["employee","in",reports]]+([["cycle","=",cycle]] if cycle else []),fields=["name","employee","goal_title","cycle","progress_percent","status","due_date"],limit=10000,ignore_permissions=True)
            reviews=get_list("Performance Review",filters=[["employee","in",reports]]+([["cycle","=",cycle]] if cycle else []),fields=["name","employee","cycle","review_status","overall_score","overall_rating"],limit=5000,ignore_permissions=True)
            checkins=get_list("Performance Check In",filters=[["employee","in",reports]],fields=["name","employee","cycle","check_in_date","progress_summary","achievements","blockers","visibility"],limit=5000,ignore_permissions=True)
            checkins=[x for x in checkins if x.get("visibility")!="HR Restricted" and (not cycle or x.get("cycle")==cycle)]
            employees=get_list("Employee",filters=[["name","in",reports]],fields=["name","employee_name","department","designation"],limit=5000,ignore_permissions=True)
            return {"manager":manager["name"],"direct_reports":employees,"goals":goals,"reviews":reviews,"check_ins":checkins,"summary":{"employees":len(employees),"goals":len(goals),"goals_at_risk":sum(1 for x in goals if x.get("status")=="At Risk"),"average_goal_progress":round(sum(float(x.get("progress_percent") or 0) for x in goals)/len(goals),1) if goals else 0,"reviews_pending":sum(1 for x in reviews if x.get("review_status") not in ("Approved","Acknowledged","Closed"))}}
        return run(request,fn)

    @app.post("/api/hr/performance/manager/team/{employee_name}/check-ins")
    def manager_create_team_checkin(employee_name: str, request: Request, body: dict = Body(...)):
        def fn():
            manager=_performance_portal_employee(); session=get_session(); roles=set(getattr(session,"roles",()) or ())
            if session.user!="Administrator" and not roles.intersection({"Department Manager","HR Manager","HR Officer","System Manager"}): raise PermissionDenied("Manager check-ins require a manager or authorised HR role.")
            if employee_name not in _performance_direct_reports(manager["name"]): raise PermissionDenied("Managers may create check-ins only for current direct reports.")
            from velora import get_doc,new_doc
            from datetime import date
            cycle_name=str(body.get("cycle") or "").strip()
            if not cycle_name: raise ValidationError("Performance Cycle is required.")
            cycle=get_doc("Performance Cycle",cycle_name,ignore_permissions=True)
            if cycle.status in ("Draft","Cancelled","Closed"): raise ValidationError("The selected Performance Cycle is not open for check-ins.")
            goal_name=body.get("goal")
            if goal_name:
                goal=get_doc("Performance Goal",goal_name,ignore_permissions=True)
                if goal.employee!=employee_name: raise PermissionDenied("The selected goal does not belong to this direct report.")
            doc=new_doc("Performance Check In",employee=employee_name,cycle=cycle_name,goal=goal_name,manager=manager["name"],check_in_date=date.today().isoformat(),progress_summary=str(body.get("progress_summary") or "")[:10000],achievements=str(body.get("achievements") or "")[:10000],blockers=str(body.get("blockers") or "")[:10000],wellbeing_pulse=body.get("wellbeing_pulse") if body.get("wellbeing_pulse") in ("Positive","Neutral","Needs Attention") else None,next_check_in=body.get("next_check_in"),visibility="Employee and Manager")
            doc.insert(ignore_permissions=True)
            return {"name":doc.name,"employee":employee_name,"manager":manager["name"],"cycle":cycle_name}
        return run(request,fn)

    @app.get("/api/hr/performance/dashboard")
    def performance_dashboard(request: Request, cycle: str | None = None):
        def fn():
            session=get_session(); roles=set(getattr(session,"roles",()) or ())
            if session.user!="Administrator" and not roles.intersection({"System Manager","HR Manager","HR Officer"}):
                raise PermissionDenied("Performance dashboard access requires an authorised HR role.")
            from velora import get_list
            filters=[["cycle","=",cycle]] if cycle else []
            reviews=get_list("Performance Review",filters=filters,fields=["name","employee","cycle","review_status","overall_score","overall_rating"],limit=10000,ignore_permissions=True)
            goals=get_list("Performance Goal",filters=filters,fields=["name","employee","department","status","progress_percent","weight","goal_level"],limit=20000,ignore_permissions=True)
            pips=get_list("Performance Improvement Plan",fields=["name","employee","review","status","start_date","end_date"],limit=5000,ignore_permissions=True)
            if cycle:
                cycle_review_names={r.get("name") for r in reviews}
                pips=[p for p in pips if p.get("review") in cycle_review_names]
            competency=get_list("Employee Competency Assessment",fields=["name","employee","competency","cycle","current_level","required_level","gap_level","development_priority","status"],filters=filters,limit=20000,ignore_permissions=True)
            campaigns=get_list("Performance Rater Campaign",fields=["name","campaign_name","cycle","status","completion_percent","minimum_raters"],filters=filters,limit=5000,ignore_permissions=True)
            calibrations=get_list("Performance Calibration Session",fields=["name","cycle","status","session_date"],filters=filters,limit=5000,ignore_permissions=True)
            total=len(reviews); approved=sum(1 for r in reviews if r.get("review_status") in ("Approved","Acknowledged","Closed"))
            scores=[float(r.get("overall_score") or 0) for r in reviews if r.get("overall_score") not in (None,"")]
            gaps=[x for x in competency if int(x.get("gap_level") or 0)>0]
            departments={}
            for goal in goals:
                dept=goal.get("department") or "Unassigned"
                row=departments.setdefault(dept,{"goals":0,"completed":0,"at_risk":0,"progress_total":0})
                row["goals"]+=1; row["completed"]+=int(goal.get("status")=="Completed"); row["at_risk"]+=int(goal.get("status")=="At Risk"); row["progress_total"]+=float(goal.get("progress_percent") or 0)
            department_performance=[{"department":k,"goals":v["goals"],"completed":v["completed"],"at_risk":v["at_risk"],"average_progress":round(v["progress_total"]/v["goals"],1) if v["goals"] else 0} for k,v in sorted(departments.items())]
            return {"cycle":cycle,"reviews":{"total":total,"approved":approved,"pending":total-approved,"completion_percent":round(approved/total*100,1) if total else 0,"average_score":round(sum(scores)/len(scores),2) if scores else None,"rating_distribution":{rating:sum(1 for r in reviews if r.get("overall_rating")==rating) for rating in ["Exceptional","Exceeds Expectations","Meets Expectations","Partially Meets","Does Not Meet"]}},"goals":{"total":len(goals),"completed":sum(1 for g in goals if g.get("status")=="Completed"),"at_risk":sum(1 for g in goals if g.get("status")=="At Risk"),"average_progress":round(sum(float(g.get("progress_percent") or 0) for g in goals)/len(goals),1) if goals else 0,"department_performance":department_performance},"improvement_plans":{"total":len(pips),"active":sum(1 for p in pips if p.get("status")=="Active"),"unsuccessful":sum(1 for p in pips if p.get("status")=="Unsuccessful")},"competency_gaps":{"assessments":len(competency),"employees_with_gaps":len({x.get("employee") for x in gaps}),"open_gaps":len(gaps),"high_or_critical":sum(1 for x in gaps if x.get("development_priority") in ("High","Critical"))},"feedback_campaigns":{"total":len(campaigns),"open":sum(1 for x in campaigns if x.get("status")=="Open"),"completed":sum(1 for x in campaigns if x.get("status")=="Completed"),"average_completion":round(sum(float(x.get("completion_percent") or 0) for x in campaigns)/len(campaigns),1) if campaigns else 0},"calibration":{"sessions":len(calibrations),"pending_approval":sum(1 for x in calibrations if x.get("status")=="Pending Approval"),"approved":sum(1 for x in calibrations if x.get("status")=="Approved")},"development_actions":{"source":"Review, check-in and improvement-plan action lists","standalone_reporting":False}}

        return run(request, fn)



    @app.post("/api/hr/performance/cycles/{cycle_name}/assignment-preview")
    def performance_cycle_assignment_preview(cycle_name: str, request: Request, body: dict = Body(default={} )):
        def fn():
            _require_hr_preview_access()
            from velora import get_doc, get_list
            cycle=get_doc("Performance Cycle",cycle_name,ignore_permissions=True)
            if cycle.status not in ("Planning","Active"):
                raise ValidationError("Only a Planning or Active Performance Cycle can be assigned.")
            filters=[["status","=","Active"]]
            if cycle.company: filters.append(["company","=",cycle.company])
            if body.get("department"): filters.append(["department","=",body["department"]])
            employees=get_list("Employee",filters=filters,fields=["name","employee_name","department","designation","reports_to"],limit=10000,ignore_permissions=True)
            existing=get_list("Performance Cycle Assignment",filters=[["cycle","=",cycle_name]],fields=["employee"],limit=20000,ignore_permissions=True)
            assigned={x.get("employee") for x in existing}
            rows=[{"employee":e.get("name"),"employee_name":e.get("employee_name"),"department":e.get("department"),"manager":e.get("reports_to"),"already_assigned":e.get("name") in assigned} for e in employees]
            return {"cycle":cycle_name,"eligible_count":len(rows),"new_assignments":sum(not r["already_assigned"] for r in rows),"employees":rows}
        return run(request,fn)

    @app.post("/api/hr/performance/cycles/{cycle_name}/assign")
    def performance_cycle_assign(cycle_name: str, request: Request, body: dict = Body(default={} )):
        def fn():
            _require_hr_preview_access()
            from velora import get_doc,get_list,new_doc
            from datetime import date
            cycle=get_doc("Performance Cycle",cycle_name,ignore_permissions=True)
            if cycle.status not in ("Planning","Active"):
                raise ValidationError("Only a Planning or Active Performance Cycle can be assigned.")
            selected=body.get("employees") or []
            if not isinstance(selected,list) or len(selected)>1000:
                raise ValidationError("Provide a list of no more than 1,000 employee IDs.")
            existing={x.get("employee") for x in get_list("Performance Cycle Assignment",filters=[["cycle","=",cycle_name]],fields=["employee"],limit=20000,ignore_permissions=True)}
            created=[]
            for employee_name in sorted(set(str(x).strip() for x in selected if str(x).strip())):
                if employee_name in existing: continue
                employee=get_doc("Employee",employee_name,ignore_permissions=True)
                assignment=new_doc("Performance Cycle Assignment",cycle=cycle_name,employee=employee_name,manager=getattr(employee,"reports_to",None),assignment_date=date.today().isoformat(),self_review_due=getattr(cycle,"self_review_deadline",None),manager_review_due=getattr(cycle,"manager_review_deadline",None),status="Assigned")
                assignment.insert(ignore_permissions=True); created.append(assignment.name)
            return {"cycle":cycle_name,"created":len(created),"assignments":created,"skipped_existing":len(set(str(x).strip() for x in selected if str(x).strip()))-len(created)}
        return run(request,fn)

    @app.get("/api/hr/performance/intelligence/trends")
    def performance_trends(request: Request, employee: str | None = None, department: str | None = None):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            filters=[]
            if employee: filters.append(["employee","=",employee])
            reviews=get_list("Performance Review",filters=filters,fields=["employee","cycle","overall_score","overall_rating","review_status"],limit=20000,ignore_permissions=True)
            if department:
                employees=get_list("Employee",filters=[["department","=",department]],fields=["name"],limit=10000,ignore_permissions=True)
                allowed={e.get("name") for e in employees}; reviews=[r for r in reviews if r.get("employee") in allowed]
            cycles={}
            for review in reviews:
                key=review.get("cycle") or "Unassigned"
                row=cycles.setdefault(key,{"cycle":key,"reviews":0,"scores":[],"completed":0})
                row["reviews"]+=1
                if review.get("overall_score") not in (None,""): row["scores"].append(float(review["overall_score"]))
                row["completed"]+=int(review.get("review_status") in ("Approved","Acknowledged","Closed"))
            trend=[{"cycle":k,"reviews":v["reviews"],"average_score":round(sum(v["scores"])/len(v["scores"]),2) if v["scores"] else None,"completion_percent":round(v["completed"]/v["reviews"]*100,1) if v["reviews"] else 0} for k,v in cycles.items()]
            return {"employee":employee,"department":department,"periods":trend,"review_count":len(reviews)}
        return run(request,fn)

    @app.get("/api/hr/succession/overview")
    def succession_overview(request: Request):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            positions=get_list("Critical Position",filters=[["status","=","Active"]],fields=["name","position_title","department","criticality","target_coverage"],limit=5000,ignore_permissions=True)
            candidates=get_list("Succession Candidate",fields=["critical_position","employee","readiness","readiness_score","status"],limit=20000,ignore_permissions=True)
            rows=[]
            for position in positions:
                pool=[c for c in candidates if c.get("critical_position")==position.get("name") and c.get("status") not in ("Withdrawn",)]
                rows.append({**position,"successor_count":len(pool),"ready_now":sum(c.get("readiness")=="Ready Now" for c in pool),"coverage_gap":max(0,int(position.get("target_coverage") or 0)-len(pool))})
            return {"critical_positions":rows,"position_count":len(rows),"positions_without_successors":sum(not r["successor_count"] for r in rows),"coverage_gaps":sum(r["coverage_gap"] for r in rows)}
        return run(request,fn)

    @app.post("/api/hr/performance/calibration/{session_name}/apply")
    def apply_performance_calibration(session_name: str, request: Request):
        def fn():
            session=get_session(); roles=set(getattr(session,"roles",()) or ())
            if session.user!="Administrator" and not roles.intersection({"System Manager","HR Manager"}):
                raise PermissionDenied("Only HR Manager or System Manager may apply approved calibration decisions.")
            from velora import get_doc
            calibration=get_doc("Performance Calibration Session",session_name,ignore_permissions=True)
            if calibration.status!="Approved":
                raise ValidationError("Only an approved Calibration Session can be applied to Performance Reviews.")
            applied=[]
            for item in list(getattr(calibration,"calibration_items",None) or []):
                if getattr(item,"decision",None)!="Accepted" or getattr(item,"proposed_score",None) in (None,""):
                    continue
                review=get_doc("Performance Review",item.review,ignore_permissions=True)
                if review.cycle!=calibration.cycle:
                    raise ValidationError(f"Review {review.name} no longer belongs to the calibration cycle.")
                review.calibrated_score=float(item.proposed_score)
                review.save(ignore_permissions=True)
                applied.append(review.name)
            return {"session":calibration.name,"applied_reviews":applied,"applied_count":len(applied)}
        return run(request, fn)

    @app.post("/api/hr/performance/workflow/reminders/preview")
    def performance_reminder_preview(request: Request):
        def fn():
            _require_hr_preview_access()
            from datetime import date
            from velora import get_list
            today=date.today().isoformat()
            assignments=get_list("Performance Cycle Assignment",filters=[["status","not in",["Completed","Cancelled"]]],fields=["name","cycle","employee","manager","review","self_review_due","manager_review_due","status"],limit=20000,ignore_permissions=True)
            employees={x.get("name"):x for x in get_list("Employee",fields=["name","user_account"],limit=20000,ignore_permissions=True)}
            managers={x.get("name"):x for x in get_list("Employee",fields=["name","user_account"],limit=20000,ignore_permissions=True)}
            existing={x.get("idempotency_key") for x in get_list("Performance Workflow Reminder",fields=["idempotency_key"],limit=50000,ignore_permissions=True)}
            candidates=[]
            for a in assignments:
                status=a.get("status")
                due=a.get("self_review_due")
                if due and str(due)<=today and status in ("Assigned","Self Review Pending","Overdue"):
                    typ="Overdue" if str(due)<today else "Self Review Due"
                    recipient=(employees.get(a.get("employee")) or {}).get("user_account")
                    key=f"{a['name']}|self|{due}"
                    if recipient and key not in existing: candidates.append({"assignment":a["name"],"cycle":a.get("cycle"),"employee":a.get("employee"),"recipient_user":recipient,"reminder_type":typ,"due_date":str(due),"idempotency_key":key})
                due=a.get("manager_review_due")
                if due and str(due)<=today and status in ("Manager Review Pending","Overdue"):
                    typ="Overdue" if str(due)<today else "Manager Review Due"
                    recipient=(managers.get(a.get("manager")) or {}).get("user_account")
                    key=f"{a['name']}|manager|{due}"
                    if recipient and key not in existing: candidates.append({"assignment":a["name"],"cycle":a.get("cycle"),"employee":a.get("employee"),"recipient_user":recipient,"reminder_type":typ,"due_date":str(due),"idempotency_key":key})
            return {"as_of":today,"candidate_count":len(candidates),"candidates":candidates}
        return run(request,fn)

    @app.post("/api/hr/performance/workflow/reminders/queue")
    def performance_reminder_queue(request: Request, body: dict = Body(default={} )):
        def fn():
            _require_hr_preview_access()
            from datetime import datetime, timezone
            from velora import get_list,new_doc
            keys=body.get("idempotency_keys") or []
            if not isinstance(keys,list) or len(keys)>5000:
                raise ValidationError("Provide no more than 5,000 reminder keys.")
            preview=performance_reminder_preview(request)
            allowed={x["idempotency_key"]:x for x in preview["candidates"]}
            if not keys: keys=list(allowed)
            if any(k not in allowed for k in keys):
                raise ValidationError("One or more reminder keys are no longer eligible. Refresh the preview.")
            existing={x.get("idempotency_key") for x in get_list("Performance Workflow Reminder",fields=["idempotency_key"],limit=50000,ignore_permissions=True)}
            queued=[]
            for key in sorted(set(keys)):
                if key in existing: continue
                row=allowed[key]
                doc=new_doc("Performance Workflow Reminder",**row,status="Queued",queued_on=datetime.now(timezone.utc).isoformat())
                doc.insert(ignore_permissions=True); queued.append(doc.name)
            return {"queued_count":len(queued),"reminders":queued,"delivery":"Queued only; no notification has been sent."}
        return run(request,fn)

    @app.get("/api/hr/performance/workflow/reminders")
    def performance_reminder_inbox(request: Request, status: str | None = "Queued"):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            filters=[["status","=",status]] if status else []
            rows=get_list("Performance Workflow Reminder",filters=filters,fields=["name","assignment","cycle","employee","recipient_user","reminder_type","due_date","status","queued_on","sent_on","delivery_error"],order_by="queued_on desc",limit=5000,ignore_permissions=True)
            return {"items":rows,"count":len(rows)}
        return run(request,fn)

    @app.get("/api/hr/training/catalog")
    def training_catalog(request: Request, active_only: bool = True):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            filters=[["active","=",1]] if active_only else []
            courses=get_list("Training Course",filters=filters,fields=["name","course_code","course_title","course_category","delivery_method","provider","duration_hours","competency","estimated_cost","currency"],order_by="course_title asc",limit=5000,ignore_permissions=True)
            return {"items":courses,"count":len(courses)}
        return run(request,fn)

    @app.get("/api/hr/training/needs-analysis")
    def training_needs_analysis(request: Request, employee: str | None = None, department: str | None = None):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            rows=get_list("Employee Competency Assessment",filters=[["status","=","Confirmed"]],fields=["name","employee","competency","current_level","required_level","gap_level","development_priority","recommended_action","assessment_date"],order_by="assessment_date desc",limit=20000,ignore_permissions=True)
            employees={x.get("name"):x for x in get_list("Employee",fields=["name","employee_name","department"],limit=20000,ignore_permissions=True)}
            latest={}
            for row in rows:
                emp=row.get("employee")
                if employee and emp!=employee: continue
                info=employees.get(emp,{})
                if department and info.get("department")!=department: continue
                key=(emp,row.get("competency"))
                if key not in latest and int(row.get("gap_level") or 0)>0:
                    latest[key]={**row,"employee_name":info.get("employee_name",emp),"department":info.get("department")}
            result=list(latest.values())
            priority={"Critical":0,"High":1,"Medium":2,"Low":3}
            result.sort(key=lambda x:(priority.get(x.get("development_priority"),4),-int(x.get("gap_level") or 0),str(x.get("employee_name") or "")))
            return {"items":result,"count":len(result),"employee_filter":employee,"department_filter":department,"source":"Latest Confirmed Employee Competency Assessment per employee and competency"}
        return run(request,fn)

    @app.get("/api/hr/training/programs")
    def training_programs(request: Request, status: str | None = "Approved"):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            filters=[["approval_status","=",status]] if status else []
            rows=get_list("Training Program",filters=filters,fields=["name","program_code","program_title","course","program_type","target_department","target_competency","start_date","end_date","budget_amount","currency","approval_status"],order_by="start_date asc",limit=5000,ignore_permissions=True)
            return {"items":rows,"count":len(rows)}
        return run(request,fn)


    @app.get("/api/hr/training/operations")
    def training_operations(request: Request, program: str | None = None):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            from collections import Counter
            sessions=get_list("Training Session", filters=([["program","=",program]] if program else []), fields=["name","program","session_title","start_datetime","end_datetime","facilitator","venue","capacity","session_status","attendance_recorded"], order_by="start_datetime asc", limit=10000, ignore_permissions=True)
            enrollments=get_list("Training Enrollment", fields=["name","session","employee","status","attendance_status","assessment_score","certificate_reference","training_cost"], order_by="modified desc", limit=50000, ignore_permissions=True)
            session_names={x["name"] for x in sessions}
            roster=[x for x in enrollments if x.get("session") in session_names]
            counts=Counter(x.get("status") or "Unknown" for x in roster)
            costs=sum(float(x.get("training_cost") or 0) for x in roster)
            return {"sessions":sessions,"enrollments":roster,"summary":{"sessions":len(sessions),"enrollments":len(roster),"completed":counts.get("Completed",0),"pending":counts.get("Nominated",0)+counts.get("Enrolled",0),"actual_cost":round(costs,2)}}
        return run(request,fn)

    @app.post("/api/hr/training/enrollments/{enrollment_name}/attendance")
    def training_record_attendance(enrollment_name: str, request: Request, body: dict = Body(...)):
        def fn():
            _require_hr_preview_access()
            from velora import get_doc
            attendance=str(body.get("attendance_status") or "").strip()
            if attendance not in ("Present","Absent","Partial"):
                raise ValidationError("Attendance must be Present, Absent or Partial.")
            doc=get_doc("Training Enrollment",enrollment_name,ignore_permissions=True)
            doc.attendance_status=attendance
            if attendance in ("Present","Partial") and body.get("assessment_score") is not None:
                score=float(body["assessment_score"])
                if score<0 or score>100: raise ValidationError("Assessment score must be between 0 and 100.")
                doc.assessment_score=score
            doc.save(ignore_permissions=True)
            return {"name":doc.name,"attendance_status":doc.attendance_status,"assessment_score":doc.assessment_score}
        return run(request,fn)

    @app.post("/api/hr/training/enrollments/{enrollment_name}/certificate")
    def training_issue_certificate(enrollment_name: str, request: Request, body: dict = Body(...)):
        def fn():
            _require_hr_preview_access()
            from velora import get_doc
            from datetime import date
            doc=get_doc("Training Enrollment",enrollment_name,ignore_permissions=True)
            if doc.status!="Completed" or doc.attendance_status not in ("Present","Partial"):
                raise ValidationError("A certificate can only be issued after completed training with recorded attendance.")
            reference=str(body.get("certificate_reference") or "").strip()
            if not reference: raise ValidationError("Certificate reference is required.")
            doc.certificate_reference=reference
            
            doc.save(ignore_permissions=True)
            return {"name":doc.name,"certificate_reference":doc.certificate_reference}
        return run(request,fn)

    @app.get("/api/hr/training/analytics")
    def training_analytics(request: Request):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            from collections import defaultdict
            rows=get_list("Training Enrollment",fields=["name","employee","session","status","attendance_status","assessment_score","training_cost"],limit=50000,ignore_permissions=True)
            by_employee=defaultdict(list)
            for r in rows:
                if r.get("employee"): by_employee[r["employee"]].append(r)
            completed=[r for r in rows if r.get("status")=="Completed"]
            scores=[float(r["assessment_score"]) for r in completed if r.get("assessment_score") is not None]
            total=sum(float(r.get("training_cost") or 0) for r in rows)
            return {"enrollments":len(rows),"completed":len(completed),"completion_rate":round(len(completed)*100/len(rows),1) if rows else 0,"average_assessment_score":round(sum(scores)/len(scores),1) if scores else None,"actual_training_cost":round(total,2),"employees_trained":len(by_employee),"source":"Training Enrollment records; effectiveness proxy uses recorded assessment scores, not causal impact evaluation"}
        return run(request,fn)


    @app.get("/api/hr/training/effectiveness")
    def training_effectiveness(request: Request, program: str | None = None):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            sessions=get_list("Training Session", fields=["name","program"], limit=50000, ignore_permissions=True)
            session_map={x["name"]:x for x in sessions}
            enrollments=get_list("Training Enrollment", fields=["name","employee","session","status","attendance_status","training_completed_on","assessment_score","development_plan"], limit=50000, ignore_permissions=True)
            programs=get_list("Training Program", fields=["name","target_competency","course"], limit=20000, ignore_permissions=True)
            program_map={x["name"]:x for x in programs}
            courses=get_list("Training Course", fields=["name","competency"], limit=20000, ignore_permissions=True)
            course_map={x["name"]:x for x in courses}
            assessments=get_list("Employee Competency Assessment", filters=[["status","=","Confirmed"]], fields=["name","employee","competency","current_level","assessment_date"], order_by="assessment_date asc", limit=100000, ignore_permissions=True)
            by_key={}
            for a in assessments:
                try: level=float(a.get("current_level")); date=str(a.get("assessment_date") or "")
                except (TypeError,ValueError): continue
                by_key.setdefault((a.get("employee"),a.get("competency")),[]).append((date,level))
            result=[]
            for e in enrollments:
                session=session_map.get(e.get("session"),{}); prog=program_map.get(session.get("program"),{})
                if program and prog.get("name")!=program: continue
                if e.get("status")!="Completed" or e.get("attendance_status") not in ("Present","Partial") or not e.get("training_completed_on"): continue
                course=course_map.get(prog.get("course"),{})
                competency=prog.get("target_competency") or course.get("competency")
                if not competency: continue
                values=by_key.get((e.get("employee"),competency),[]); completed=str(e["training_completed_on"])
                before=[x for x in values if x[0]<completed]; after=[x for x in values if x[0]>completed]
                if not before or not after: continue
                pre=max(before,key=lambda x:x[0]); post=min(after,key=lambda x:x[0])
                result.append({"enrollment":e["name"],"employee":e.get("employee"),"program":prog.get("name"),"competency":competency,"completed_on":completed,"pre_assessment_date":pre[0],"pre_level":pre[1],"post_assessment_date":post[0],"post_level":post[1],"level_change":round(post[1]-pre[1],2),"development_plan":e.get("development_plan")})
            improvements=sum(1 for x in result if x["level_change"]>0)
            return {"items":result,"count":len(result),"employees_with_improvement":improvements,"average_level_change":round(sum(x["level_change"] for x in result)/len(result),2) if result else None,"method":"Closest confirmed competency assessment before and after recorded training completion; association only, not causal attribution."}
        return run(request,fn)

    @app.get("/api/hr/training/budget-analysis")
    def training_budget_analysis(request: Request, program: str | None = None):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            sessions=get_list("Training Session",fields=["name","program"],limit=50000,ignore_permissions=True)
            session_program={x["name"]:x.get("program") for x in sessions}
            budgets=get_list("Training Program",fields=["name","program_title","budget_amount","currency","start_date","end_date","approval_status"],limit=20000,ignore_permissions=True)
            costs=get_list("Training Enrollment",fields=["session","training_cost","status"],limit=100000,ignore_permissions=True)
            rows=[]
            for p in budgets:
                if program and p["name"]!=program: continue
                actual=sum(float(x.get("training_cost") or 0) for x in costs if session_program.get(x.get("session"))==p["name"] and x.get("status") not in ("Withdrawn","Failed"))
                budget=float(p.get("budget_amount") or 0); variance=budget-actual
                rows.append({**p,"budget":budget,"actual_cost":round(actual,2),"available_budget":round(variance,2),"utilisation_percent":round(actual*100/budget,1) if budget>0 else None,"over_budget":actual>budget})
            return {"items":rows,"count":len(rows),"total_budget":round(sum(x["budget"] for x in rows),2),"total_actual":round(sum(x["actual_cost"] for x in rows),2)}
        return run(request,fn)

    @app.get("/api/hr/training/recommendations")
    def training_recommendations(request: Request, employee: str | None = None, department: str | None = None):
        def fn():
            _require_hr_preview_access()
            from velora import get_list
            assessments=get_list("Employee Competency Assessment",filters=[["status","=","Confirmed"]],fields=["employee","competency","gap_level","development_priority","assessment_date"],order_by="assessment_date desc",limit=50000,ignore_permissions=True)
            employees={x["name"]:x for x in get_list("Employee",fields=["name","employee_name","department"],limit=30000,ignore_permissions=True)}
            courses=get_list("Training Course",filters=[["active","=",1]],fields=["name","course_title","course_code","competency","course_category","estimated_cost","currency"],limit=30000,ignore_permissions=True)
            latest={}
            for a in assessments:
                emp=a.get("employee"); info=employees.get(emp,{})
                if employee and emp!=employee: continue
                if department and info.get("department")!=department: continue
                key=(emp,a.get("competency"))
                if key not in latest and float(a.get("gap_level") or 0)>0: latest[key]={**a,"employee_name":info.get("employee_name",emp),"department":info.get("department")}
            rows=[]
            for gap in latest.values():
                matches=[c for c in courses if c.get("competency")==gap.get("competency")]
                rows.append({"employee":gap.get("employee"),"employee_name":gap.get("employee_name"),"department":gap.get("department"),"competency":gap.get("competency"),"gap_level":gap.get("gap_level"),"priority":gap.get("development_priority"),"recommended_courses":matches})
            return {"items":rows,"count":len(rows),"matching":"Exact competency match against active Training Course records; recommendations require HR review."}
        return run(request,fn)
