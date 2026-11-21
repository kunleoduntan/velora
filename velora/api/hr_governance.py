"""HR handover and controlled policy governance services.

Handover acceptance is distinct from leave approval and exit clearance. Policy
versions are retained against their document and acknowledgements reference an
exact published version.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
from fastapi import Body, FastAPI, Request
from ..exceptions import PermissionDenied, ValidationError
from ..permissions import get_session


def _session():
    return get_session()


def _require_hr(manager=False):
    s = _session(); roles = set(getattr(s, "roles", ()) or ())
    allowed = {"System Manager", "HR Manager"} if manager else {"System Manager", "HR Manager", "HR Officer"}
    if s.user != "Administrator" and not roles.intersection(allowed):
        raise PermissionDenied("This HR governance action is not permitted for the current user.")
    return s


def _may_approve_policy(session) -> bool:
    """Who approves an HR policy version is the company's setting; without VeloraERP's setting the HR managers keep it."""
    try:
        from velora_erp.finance.approval_authority import is_authorised
        return is_authorised("hr_policy.approve", user=session.user, roles=tuple(getattr(session, "roles", ()) or ()))
    except ImportError:
        return _is_hr(session, manager=True)


def _now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _date(v):
    if not v: return None
    try: return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError): return None


def _value(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)

def _set(row, key, value):
    if isinstance(row, dict): row[key] = value
    else: setattr(row, key, value)

def _is_employee_user(session, employee):
    if not employee: return False
    from velora import get_list
    rows=get_list("Employee",filters=[["user_account","=",session.user]],fields=["name"],limit=2,ignore_permissions=True)
    return len(rows)==1 and rows[0].get("name")==employee

def _is_hr(session, manager=False):
    roles=set(getattr(session,"roles",()) or ())
    allowed={"System Manager","HR Manager"} if manager else {"System Manager","HR Manager","HR Officer"}
    return session.user=="Administrator" or bool(roles.intersection(allowed))


def install_hr_governance_routes(app: FastAPI, run):
    @app.get("/api/hr/handovers")
    def list_handovers(request: Request, employee: str | None = None, handover_type: str | None = None, status: str | None = None):
        def fn():
            _require_hr(); from velora import get_list
            filters=[]
            if employee: filters.append(["employee", "=", employee])
            if handover_type: filters.append(["handover_type", "=", handover_type])
            if status: filters.append(["handover_status", "=", status])
            rows=get_list("Handover Management", filters=filters, fields=["name","employee","handover_type","source_doctype","source_reference","start_date","end_date","receiving_employee","handover_status","outstanding_count"], limit=5000, ignore_permissions=True)
            return {"items": rows, "count": len(rows)}
        return run(request, fn)

    @app.post("/api/hr/handovers")
    def create_handover(request: Request, body: dict = Body(...)):
        def fn():
            _require_hr(); from velora import get_doc, new_doc
            employee=str(body.get("employee") or "").strip(); kind=str(body.get("handover_type") or "").strip()
            source_type="Leave Application" if kind == "Leave" else "Employee Separation" if kind == "Separation" else None
            source=str(body.get("source_reference") or "").strip()
            if not employee or not source_type or not source: raise ValidationError("Employee, Handover Type and Source Reference are required.")
            source_doc=get_doc(source_type, source, ignore_permissions=True)
            if str(getattr(source_doc,"employee", "")) != employee: raise ValidationError("The selected source document does not belong to the specified employee.")
            if kind == "Leave":
                if getattr(source_doc,"workflow_status",None) not in {"Pending Approval","Approved","Completed"}: raise ValidationError("A handover can only be linked to an active leave request.")
                start=getattr(source_doc,"from_date",None); end=getattr(source_doc,"to_date",None)
            else:
                if getattr(source_doc,"workflow_status",None) in {"Draft","Rejected","Cancelled","Closed"}: raise ValidationError("A separation handover requires a submitted, active separation.")
                start=getattr(source_doc,"notice_date",None); end=getattr(source_doc,"last_working_date",None)
            items=body.get("handover_items") or []
            if not isinstance(items,list) or not items: raise ValidationError("Add at least one handover task before creating the handover.")
            doc=new_doc("Handover Management", employee=employee, handover_type=kind, source_doctype=source_type,
                source_reference=source, start_date=body.get("start_date") or start, end_date=body.get("end_date") or end,
                receiving_employee=body.get("receiving_employee"), handover_owner=body.get("handover_owner"),
                handover_meeting_date=body.get("handover_meeting_date"), handover_items=items,
                handover_notes=body.get("handover_notes"), handover_status="Draft")
            doc.insert(ignore_permissions=True)
            return {"name":doc.name,"status":doc.handover_status,"source_doctype":source_type,"source_reference":source,"created":True}
        return run(request, fn)

    @app.post("/api/hr/handovers/{handover_name}/transition")
    def transition_handover(handover_name: str, request: Request, body: dict = Body(...)):
        def fn():
            session=_session(); from velora import get_doc
            doc=get_doc("Handover Management", handover_name, ignore_permissions=True)
            action=str(body.get("action") or "").strip()
            if action == "Accept":
                if not (_is_hr(session) or _is_employee_user(session,getattr(doc,"receiving_employee",None))):
                    raise PermissionDenied("Only the designated receiving employee or HR may accept this handover.")
            elif action == "Close":
                if not _is_hr(session,manager=True): raise PermissionDenied("Only HR Manager or System Manager may close a handover.")
            else:
                if not _is_hr(session): raise PermissionDenied("Only authorised HR personnel may manage handover workflow.")
            allowed={"Submit","Accept","Return","Close","Cancel"}
            if action not in allowed: raise ValidationError("Action must be Submit, Accept, Return, Close or Cancel.")
            items=list(getattr(doc,"handover_items",None) or [])
            if action == "Submit":
                if doc.handover_status not in {"Draft","Returned for Correction"}: raise ValidationError("Only a Draft or returned handover can be submitted.")
                if not items: raise ValidationError("A handover must contain at least one task.")
                doc.handover_status="Submitted"; doc.submitted_by=session.user; doc.submitted_on=_now()
            elif action == "Accept":
                if doc.handover_status not in {"Submitted","Partially Accepted"}: raise ValidationError("Only a submitted handover can be accepted.")
                if any(_value(x,"handover_status") not in {"Accepted","Not Applicable"} for x in items): raise ValidationError("Every handover task must be Accepted or Not Applicable before final acceptance.")
                doc.handover_status="Accepted"; doc.accepted_by=session.user; doc.accepted_on=_now()
            elif action == "Return":
                if doc.handover_status not in {"Submitted","Partially Accepted"}: raise ValidationError("Only a submitted handover can be returned.")
                doc.handover_status="Returned for Correction"
            elif action == "Close":
                if doc.handover_status != "Accepted": raise ValidationError("Only an accepted handover can be closed.")
                doc.handover_status="Closed"
            elif action == "Cancel":
                if doc.handover_status in {"Accepted","Closed"}: raise ValidationError("An accepted or closed handover cannot be cancelled.")
                doc.handover_status="Cancelled"
            doc.outstanding_count=sum(1 for x in items if _value(x,"handover_status") not in {"Accepted","Not Applicable"})
            doc.save(ignore_permissions=True)
            return {"name":doc.name,"status":doc.handover_status,"outstanding_count":doc.outstanding_count}
        return run(request, fn)

    @app.post("/api/hr/handovers/{handover_name}/items/{item_index}")
    def update_handover_item(handover_name: str, item_index: int, request: Request, body: dict = Body(...)):
        def fn():
            session=_session(); from velora import get_doc
            doc=get_doc("Handover Management",handover_name,ignore_permissions=True)
            items=list(getattr(doc,"handover_items",None) or [])
            if item_index < 0 or item_index >= len(items): raise ValidationError("Handover item index is out of range.")
            item=items[item_index]
            is_hr=_is_hr(session)
            is_receiver=_is_employee_user(session,getattr(doc,"receiving_employee",None)) or _is_employee_user(session,_value(item,"assigned_to"))
            if not (is_hr or is_receiver): raise PermissionDenied("Only HR or the assigned receiving employee may update this handover task.")
            if doc.handover_status not in {"Draft","In Progress","Submitted","Partially Accepted","Returned for Correction"}: raise ValidationError("This handover is no longer editable.")
            status=str(body.get("handover_status") or _value(item,"handover_status","Pending"))
            if not is_hr and status not in {"Accepted","Rejected"}: raise PermissionDenied("The receiving employee may only accept or reject an assigned handover task.")
            if status not in {"Pending","In Progress","Submitted","Accepted","Rejected","Not Applicable"}: raise ValidationError("Invalid handover task status.")
            for key in ("handover_status","evidence_reference","recipient_comments","assigned_to","due_date"):
                if key in body: _set(item,key,body[key])
            if status == "Accepted": _set(item,"completed_on",_now())
            doc.outstanding_count=sum(1 for x in items if _value(x,"handover_status") not in {"Accepted","Not Applicable"})
            if doc.handover_status == "Submitted" and any(_value(x,"handover_status") in {"Accepted","Not Applicable"} for x in items): doc.handover_status="Partially Accepted"
            doc.save(ignore_permissions=True)
            return {"name":doc.name,"item_index":item_index,"item_status":status,"outstanding_count":doc.outstanding_count}
        return run(request, fn)

    @app.get("/api/hr/policies")
    def list_policies(request: Request, status: str | None = None, category: str | None = None):
        def fn():
            _require_hr(); from velora import get_list
            filters=[]
            if status: filters.append(["policy_status","=",status])
            if category: filters.append(["policy_category","=",category])
            rows=get_list("HR Policy Document",filters=filters,fields=["name","policy_code","policy_title","policy_category","current_version","policy_status","next_review_date","acknowledgement_required"],limit=5000,ignore_permissions=True)
            return {"items":rows,"count":len(rows)}
        return run(request, fn)

    @app.get("/api/hr/policies/available")
    def available_policies(request: Request):
        def fn():
            session=_session(); roles=set(getattr(session,"roles",()) or ()); is_hr=_is_hr(session)
            from velora import get_doc,get_list
            if is_hr:
                employees=[]
            else:
                employees=get_list("Employee",filters=[["user_account","=",session.user]],fields=["name"],limit=2,ignore_permissions=True)
                if len(employees)!=1: raise PermissionDenied("The signed-in user must be linked to one Employee record to view assigned HR policies.")
            employee=employees[0].get("name") if employees else None
            policies=get_list("HR Policy Document",filters=[["policy_status","=","Published"]],fields=["name","policy_code","policy_title","policy_category","current_version","confidentiality","acknowledgement_required","next_review_date"],limit=5000,ignore_permissions=True)
            items=[]
            for policy in policies:
                classification=policy.get("confidentiality") or "All Employees"
                if not is_hr and classification not in {"All Employees"} and not (classification=="Managers" and roles.intersection({"Department Manager","Manager","HR Manager","System Manager"})):
                    continue
                doc=get_doc("HR Policy Document",policy["name"],ignore_permissions=True)
                version=next((v for v in list(getattr(doc,"versions",None) or []) if str(_value(v,"version_number"))==str(policy.get("current_version")) and _value(v,"version_status")=="Published"),None)
                if version is None: continue
                ack_rows=[]
                if employee and policy.get("acknowledgement_required"):
                    ack_rows=get_list("HR Policy Acknowledgement",filters=[["policy_document","=",policy["name"]],["policy_version","=",str(policy.get("current_version"))],["employee","=",employee]],fields=["name","acknowledgement_status","due_date","acknowledged_on"],limit=1,ignore_permissions=True)
                items.append({**policy,"version_title":_value(version,"version_title"),"version_content":_value(version,"version_content"),"attachment":_value(version,"attachment"),"effective_from":_value(version,"effective_from"),"change_summary":_value(version,"change_summary"),"acknowledgement":ack_rows[0] if ack_rows else None})
            return {"items":items,"count":len(items),"employee":employee}
        return run(request, fn)

    @app.post("/api/hr/policies")
    def create_policy(request: Request, body: dict = Body(...)):
        def fn():
            _require_hr(manager=True); from velora import new_doc
            code=str(body.get("policy_code") or "").strip(); title=str(body.get("policy_title") or "").strip()
            if not code or not title: raise ValidationError("Policy Code and Policy Title are required.")
            from velora import get_list
            if get_list("HR Policy Document",filters=[["policy_code","=",code]],fields=["name"],limit=1,ignore_permissions=True): raise ValidationError("A policy already exists with this Policy Code.")
            doc=new_doc("HR Policy Document",policy_code=code,policy_title=title,policy_category=body.get("policy_category") or "Other",policy_owner=body.get("policy_owner"),department=body.get("department"),policy_status="Draft",confidentiality=body.get("confidentiality") or "All Employees",review_cycle_months=int(body.get("review_cycle_months") or 12),acknowledgement_required=body.get("acknowledgement_required",1),versions=[])
            doc.insert(ignore_permissions=True)
            return {"name":doc.name,"policy_code":code,"policy_status":"Draft"}
        return run(request, fn)

    @app.post("/api/hr/policies/{policy_name}/versions")
    def add_policy_version(policy_name: str, request: Request, body: dict = Body(...)):
        def fn():
            _require_hr(manager=True); from velora import get_doc
            doc=get_doc("HR Policy Document",policy_name,ignore_permissions=True)
            if doc.policy_status == "Retired": raise ValidationError("A retired policy cannot receive a new version.")
            number=str(body.get("version_number") or "").strip(); effective=_date(body.get("effective_from")); summary=str(body.get("change_summary") or "").strip()
            if not number or not effective or not summary: raise ValidationError("Version Number, Effective From and Change Summary are required.")
            versions=list(getattr(doc,"versions",None) or [])
            if any(str(_value(v,"version_number")) == number for v in versions): raise ValidationError("This policy version number already exists.")
            if versions and any(_value(v,"version_status") in {"Draft","In Review"} for v in versions): raise ValidationError("Complete or withdraw the existing draft version before creating another.")
            row={"version_number":number,"version_title":body.get("version_title"),"version_content":body.get("version_content"),"attachment":body.get("attachment"),"change_summary":summary,"effective_from":effective.isoformat(),"effective_to":body.get("effective_to"),"version_status":"Draft","supersedes_version":doc.current_version}
            versions.append(row); doc.versions=versions; doc.policy_status="In Review"; doc.save(ignore_permissions=True)
            return {"policy":doc.name,"version_number":number,"version_status":"Draft","supersedes_version":doc.current_version}
        return run(request, fn)

    @app.post("/api/hr/policies/{policy_name}/versions/{version_number}/transition")
    def transition_policy_version(policy_name: str, version_number: str, request: Request, body: dict = Body(...)):
        def fn():
            session=_require_hr(manager=True); from velora import get_doc
            doc=get_doc("HR Policy Document",policy_name,ignore_permissions=True); versions=list(getattr(doc,"versions",None) or [])
            row=next((v for v in versions if str(_value(v,"version_number"))==version_number),None)
            if row is None: raise ValidationError("Policy version was not found.")
            action=str(body.get("action") or ""); status=_value(row,"version_status")
            if action == "Submit" and status == "Draft": setattr(row,"version_status","In Review")
            elif action == "Approve" and status == "In Review":
                if not _may_approve_policy(session): raise PermissionDenied("You are not one of the roles set to approve HR policy versions (Finance Settings > Approvals > Other powers).")
                setattr(row,"version_status","Approved"); setattr(row,"approved_by",session.user); setattr(row,"approved_on",_now())
            elif action == "Publish" and status == "Approved":
                effective=_date(_value(row,"effective_from")); today=date.today()
                if not effective or effective < today: raise ValidationError("A policy version must have an effective date today or in the future before publication.")
                for old in versions:
                    if _value(old,"version_status")=="Published": setattr(old,"version_status","Superseded"); setattr(old,"effective_to",(effective.fromordinal(effective.toordinal()-1)).isoformat())
                setattr(row,"version_status","Published"); setattr(row,"published_on",_now()); doc.current_version=version_number; doc.policy_status="Published"
                months=max(1,int(getattr(doc,"review_cycle_months",12) or 12));
                import calendar
                month_index = effective.year * 12 + (effective.month - 1) + months
                target_year, target_month0 = divmod(month_index, 12)
                target_month = target_month0 + 1
                target_day = min(effective.day, calendar.monthrange(target_year, target_month)[1])
                doc.next_review_date=effective.replace(year=target_year, month=target_month, day=target_day).isoformat()
            elif action == "Withdraw" and status in {"Draft","In Review","Approved"}: setattr(row,"version_status","Withdrawn")
            else: raise ValidationError("Invalid policy version transition for the current status.")
            doc.versions=versions; doc.save(ignore_permissions=True)
            return {"policy":doc.name,"version_number":version_number,"version_status":_value(row,"version_status"),"current_version":doc.current_version}
        return run(request, fn)

    @app.post("/api/hr/policies/{policy_name}/acknowledgements")
    def assign_policy_acknowledgements(policy_name: str, request: Request, body: dict = Body(...)):
        def fn():
            _require_hr(); from velora import get_doc,get_list,new_doc
            policy=get_doc("HR Policy Document",policy_name,ignore_permissions=True); version=str(body.get("policy_version") or policy.current_version or "")
            if not version: raise ValidationError("A published policy version is required.")
            row=next((v for v in list(getattr(policy,"versions",None) or []) if str(_value(v,"version_number"))==version),None)
            if row is None or _value(row,"version_status")!="Published": raise ValidationError("Acknowledgement can only be assigned for an exact Published policy version.")
            employees=body.get("employees") or []
            if not isinstance(employees,list) or not employees: raise ValidationError("Select at least one employee for acknowledgement.")
            if len(set(employees)) != len(employees): raise ValidationError("The employee selection contains duplicates.")
            created=[]; skipped=[]
            for employee in employees:
                existing=get_list("HR Policy Acknowledgement",filters=[["policy_document","=",policy_name],["policy_version","=",version],["employee","=",employee]],fields=["name"],limit=1,ignore_permissions=True)
                if existing: skipped.append(employee); continue
                ack=new_doc("HR Policy Acknowledgement",policy_document=policy_name,policy_version=version,employee=employee,assigned_on=_now(),due_date=body.get("due_date"),acknowledgement_status="Pending")
                ack.insert(ignore_permissions=True); created.append(ack.name)
            return {"policy":policy_name,"policy_version":version,"created":created,"skipped_existing":skipped}
        return run(request, fn)

    @app.post("/api/hr/policy-acknowledgements/{ack_name}/acknowledge")
    def acknowledge_policy(ack_name: str, request: Request, body: dict = Body(...)):
        def fn():
            session=_session(); from velora import get_doc
            ack=get_doc("HR Policy Acknowledgement",ack_name,ignore_permissions=True)
            roles=set(getattr(session,"roles",()) or ()); is_hr=session.user=="Administrator" or bool(roles.intersection({"System Manager","HR Manager","HR Officer"}))
            if not is_hr:
                employee=getattr(ack,"employee",None)
                from velora import get_list
                rows=get_list("Employee",filters=[["user_account","=",session.user]],fields=["name"],limit=2,ignore_permissions=True)
                if len(rows)!=1 or rows[0].get("name")!=employee: raise PermissionDenied("Employees may acknowledge only their own assigned policy acknowledgement.")
            if ack.acknowledgement_status not in {"Pending","Overdue"}: raise ValidationError("This policy acknowledgement has already been resolved.")
            decision=str(body.get("decision") or "Acknowledged")
            if decision not in {"Acknowledged","Declined"}: raise ValidationError("Decision must be Acknowledged or Declined.")
            ack.acknowledgement_status=decision; ack.acknowledged_on=_now(); ack.acknowledgement_method=body.get("method") or ("HR Recorded" if is_hr else "Employee Portal"); ack.employee_comment=body.get("comment"); ack.recorded_by=session.user
            ack.save(ignore_permissions=True)
            return {"name":ack.name,"status":ack.acknowledgement_status,"policy_version":ack.policy_version,"acknowledged_on":ack.acknowledged_on}
        return run(request, fn)

    @app.get("/api/hr/policy-acknowledgements")
    def policy_acknowledgement_report(request: Request, policy: str | None = None, version: str | None = None, employee: str | None = None, status: str | None = None):
        def fn():
            _require_hr(); from velora import get_list
            filters=[]
            for key,val in (("policy_document",policy),("policy_version",version),("employee",employee),("acknowledgement_status",status)):
                if val: filters.append([key,"=",val])
            rows=get_list("HR Policy Acknowledgement",filters=filters,fields=["name","policy_document","policy_version","employee","assigned_on","due_date","acknowledgement_status","acknowledged_on"],limit=20000,ignore_permissions=True)
            today=date.today()
            for row in rows:
                if row.get("acknowledgement_status")=="Pending" and _date(row.get("due_date")) and _date(row.get("due_date"))<today: row["is_overdue"]=True
                else: row["is_overdue"]=False
            return {"items":rows,"count":len(rows),"pending":sum(1 for x in rows if x.get("acknowledgement_status")=="Pending"),"acknowledged":sum(1 for x in rows if x.get("acknowledgement_status")=="Acknowledged"),"declined":sum(1 for x in rows if x.get("acknowledgement_status")=="Declined"),"overdue":sum(1 for x in rows if x.get("is_overdue"))}
        return run(request, fn)
