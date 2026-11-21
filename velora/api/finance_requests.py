"""Finance eRequest review, employee self-service and analytics API.

Requests are control records only. This API never creates or posts ledger entries.
"""
from datetime import datetime, timezone
import json
from fastapi import Body, FastAPI, Request
from ..exceptions import PermissionDenied, ValidationError
from ..permissions import get_session

def _now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _roles(s): return set(getattr(s, "roles", ()) or ())
def _policy(company=None):
    """Return the applicable enabled policy; configuration is mandatory, never guessed."""
    from velora import get_list
    rows=get_list("Finance Request Policy", filters=[["enabled","=",1]], fields=["name","company","finance_roles","manager_roles","request_types","priorities","transaction_types","approval_rules","finance_actions","workflow_definition","default_currency"], limit=500, ignore_permissions=True)
    exact=[r for r in rows if company and r.get("company")==company]
    global_rows=[r for r in rows if not r.get("company")]
    candidates=exact or global_rows
    if len(candidates)!=1:
        raise ValidationError("Configure exactly one applicable enabled Finance Request Policy for this company before using Finance eRequest.")
    row=candidates[0]
    def parsed(key, default):
        value=row.get(key)
        if value in (None, ""): return default
        try: return json.loads(value) if isinstance(value,str) else value
        except (TypeError,ValueError): raise ValidationError(f"Finance Request Policy {key} must contain valid JSON.") from None
    row["finance_roles"]=parsed("finance_roles",[])
    row["manager_roles"]=parsed("manager_roles",[])
    row["request_types"]=parsed("request_types",[])
    row["priorities"]=parsed("priorities",[])
    row["transaction_types"]=parsed("transaction_types",[])
    row["approval_rules"]=parsed("approval_rules",[])
    row["finance_actions"]=parsed("finance_actions",[])
    return row

def _finance(s, policy=None):
    policy=policy or _policy()
    return s.user == "Administrator" or bool(_roles(s) & set(policy["finance_roles"]))
def _manager(s, policy=None):
    policy=policy or _policy()
    return s.user == "Administrator" or bool(_roles(s) & set(policy["manager_roles"]))
def _approval_roles(policy, amount):
    from decimal import Decimal
    value=Decimal(str(amount or 0)); matched=[]
    for rule in policy["approval_rules"]:
        try:
            ceiling=Decimal(str(rule.get("maximum_amount")))
            floor=Decimal(str(rule.get("minimum_amount",0)))
        except Exception: raise ValidationError("Approval policy contains an invalid amount range.") from None
        if floor <= value <= ceiling: matched.append(rule)
    if len(matched)!=1: raise ValidationError("No unique approval rule covers this request amount. Review the Finance Request Policy.")
    roles=set(matched[0].get("approver_roles") or [])
    if not roles: raise ValidationError("The matching approval rule has no approver roles configured.")
    return roles
def _employee(s):
    from velora import get_list
    rows = get_list("Employee", filters=[["user_account", "=", s.user], ["disabled", "=", 0]], fields=["name", "department"], limit=2, ignore_permissions=True)
    if len(rows) != 1: raise PermissionDenied("An active Employee account must be linked uniquely to this user.")
    return rows[0]
def _request(name):
    from velora import get_doc
    return get_doc("Finance Service Request", name, ignore_permissions=True)
def _save(doc): doc.save(ignore_permissions=True)

def install_finance_request_routes(app: FastAPI, run):
    @app.get("/api/finance/request-policy")
    def finance_request_policy(request: Request):
        def fn():
            get_session(); policy=_policy()
            return {k:policy.get(k) for k in ("name","request_types","priorities","transaction_types","approval_rules","workflow_definition","default_currency")}
        return run(request,fn)
    @app.get("/api/finance/requests")
    def finance_request_list(request: Request, status: str | None = None, request_type: str | None = None, assigned_to: str | None = None):
        def fn():
            s=get_session(); from velora import get_list
            filters=[]
            if not _finance(s): filters.append(["requester", "=", _employee(s)["name"]])
            if status: filters.append(["request_status", "=", status])
            if request_type: filters.append(["request_type", "=", request_type])
            if assigned_to: filters.append(["assigned_to", "=", assigned_to])
            fields=["name","requester","department","request_type","subject","requested_amount","currency","required_by","priority","request_status","assigned_to","approved_amount","submitted_on","modified"]
            rows=get_list("Finance Service Request", filters=filters, fields=fields, order_by="modified desc", limit=1000, ignore_permissions=True)
            return {"items":rows,"count":len(rows)}
        return run(request, fn)

    @app.post("/api/finance/me/requests")
    def employee_create_finance_request(request: Request, body: dict = Body(...)):
        def fn():
            s=get_session(); emp=_employee(s); from velora import new_doc
            policy=_policy(emp.get("company")); allowed=set(policy["request_types"])
            kind=str(body.get("request_type") or "").strip(); subject=str(body.get("subject") or "").strip(); purpose=str(body.get("business_purpose") or "").strip()
            if kind not in allowed or not subject or not purpose: raise ValidationError("Choose a valid request type and provide Subject and Business Purpose.")
            from decimal import Decimal, InvalidOperation
            raw_amount=body.get("requested_amount")
            if raw_amount not in (None, ""):
                try: raw_amount=Decimal(str(raw_amount))
                except (InvalidOperation,ValueError): raise ValidationError("Requested Amount must be numeric.") from None
                if raw_amount < 0: raise ValidationError("Requested Amount cannot be negative.")
            currency=str(body.get("currency") or policy.get("default_currency") or "").strip().upper()
            if len(currency) != 3 or not currency.isalpha(): raise ValidationError("Currency must be a three-letter code.")
            priority=str(body.get("priority") or (policy["priorities"][0] if policy["priorities"] else "")).strip()
            if not priority or priority not in policy["priorities"]: raise ValidationError("Select a priority configured in Finance Request Policy.")
            doc=new_doc("Finance Service Request", company=emp.get("company"), requester=emp["name"], department=emp.get("department"), request_type=kind, subject=subject[:200], business_purpose=purpose[:10000], requested_amount=str(raw_amount) if raw_amount not in (None, "") else None, currency=currency, required_by=body.get("required_by"), priority=priority, request_status="Submitted", submitted_on=_now())
            doc.insert(ignore_permissions=True)
            return {"name":doc.name,"request_status":doc.request_status}
        return run(request, fn)

    @app.get("/api/finance/me/requests")
    def employee_finance_requests(request: Request):
        def fn():
            emp=_employee(get_session()); from velora import get_list
            fields=["name","request_type","subject","requested_amount","currency","priority","request_status","clarification_request","clarification_response","resolution_notes","linked_transaction_doctype","linked_transaction","submitted_on","resolved_on","modified"]
            rows=get_list("Finance Service Request",filters=[["requester","=",emp["name"]]],fields=fields,order_by="modified desc",limit=300,ignore_permissions=True)
            return {"items":rows,"count":len(rows)}
        return run(request, fn)

    @app.post("/api/finance/requests/{name}/action")
    def finance_request_action(name: str, request: Request, body: dict = Body(...)):
        def fn():
            s=get_session(); doc=_request(name); action=str(body.get("action") or "").strip(); now=_now(); policy=_policy(getattr(doc,"company",None))
            status=doc.request_status
            finance_actions=set(policy["finance_actions"])
            if action in finance_actions and not _finance(s,policy): raise PermissionDenied("Only Finance personnel may manage Finance requests.")
            if action == "Assign":
                if status not in ACTIVE: raise ValidationError("Only active requests can be assigned.")
                assignee=str(body.get("assigned_to") or "").strip()
                if not assignee: raise ValidationError("Assigned To is required.")
                doc.assigned_to=assignee; doc.request_status="Under Review"
            elif action == "Request Clarification":
                if status not in ACTIVE: raise ValidationError("Clarification can only be requested on an active request.")
                msg=str(body.get("message") or "").strip()
                if not msg: raise ValidationError("Provide the clarification required.")
                doc.clarification_request=msg[:5000]; doc.clarification_requested_on=now; doc.request_status="Waiting for Information"
            elif action == "Recommend Approval":
                if status not in {"Under Review","Submitted"}: raise ValidationError("Only requests under review can be recommended for approval.")
                amount=body.get("approved_amount",doc.requested_amount)
                if amount in (None, ""): raise ValidationError("An approved amount is required for a monetary request.")
                from decimal import Decimal, InvalidOperation
                try: amount=Decimal(str(amount))
                except (InvalidOperation,ValueError): raise ValidationError("Approved Amount must be numeric.") from None
                if amount < 0 or (doc.requested_amount not in (None, "") and amount > Decimal(str(doc.requested_amount))): raise ValidationError("Approved Amount must be between zero and the requested amount.")
                doc.approved_amount=str(amount); doc.recommendation_notes=str(body.get("notes") or "")[:5000]; doc.request_status="Pending Approval"; doc.recommended_by=s.user; doc.recommended_on=now
            elif action == "Approve":
                if not _manager(s,policy): raise PermissionDenied("Your configured Finance Request Policy does not authorise final approval.")
                permitted=_approval_roles(policy,doc.approved_amount)
                if permitted and not (_roles(s) & permitted) and s.user != "Administrator": raise PermissionDenied("Your role is not authorised by the amount-based approval rule.")
                if status != "Pending Approval": raise ValidationError("Only requests pending approval can be approved.")
                if doc.approved_amount in (None, ""): raise ValidationError("A recommended approved amount is required before approval.")
                if doc.workflow_instance:
                    from velora.workflows import act as workflow_act
                    workflow_act(doc.workflow_instance,"Approve",str(body.get("notes") or ""))
                doc.request_status="Approved"; doc.approved_by=s.user; doc.approved_on=now
            elif action == "Decline":
                if not _manager(s,policy): raise PermissionDenied("Your configured Finance Request Policy does not authorise decline decisions.")
                if status not in ACTIVE | {"Pending Approval"}: raise ValidationError("This request cannot be declined in its current state.")
                note=str(body.get("notes") or "").strip()
                if not note: raise ValidationError("A reason is required when declining a request.")
                if doc.workflow_instance:
                    from velora.workflows import act as workflow_act
                    workflow_act(doc.workflow_instance,"Decline",note)
                doc.resolution_notes=note[:5000]; doc.request_status="Declined"; doc.resolved_on=now
            elif action == "Respond":
                emp=_employee(s)
                if doc.requester != emp["name"] or status != "Waiting for Information": raise PermissionDenied("Only the requester may respond to an outstanding clarification.")
                response=str(body.get("response") or "").strip()
                if not response: raise ValidationError("Clarification response is required.")
                doc.clarification_response=response[:5000]; doc.clarification_responded_on=now; doc.request_status="Under Review"
            elif action == "Link Transaction":
                if status != "Approved": raise ValidationError("Only approved requests can be linked to a financial transaction.")
                doctype=str(body.get("doctype") or "").strip(); transaction=str(body.get("name") or "").strip()
                if doctype not in set(policy["transaction_types"]) or not transaction: raise ValidationError("Select a transaction type enabled in Finance Request Policy and an existing transaction.")
                from velora import get_doc
                linked=get_doc(doctype,transaction,ignore_permissions=True)
                if not linked: raise ValidationError("The selected transaction does not exist.")
                doc.linked_transaction_doctype=doctype; doc.linked_transaction=transaction; doc.request_status="Converted"; doc.resolved_on=now; doc.converted_by=s.user; doc.converted_on=now
            elif action == "Resolve":
                if status not in {"Approved","Declined"}: raise ValidationError("Only decided requests can be resolved.")
                note=str(body.get("notes") or "").strip()
                if not note: raise ValidationError("Resolution notes are required.")
                doc.resolution_notes=note[:5000]; doc.request_status="Resolved"; doc.resolved_on=now
            elif action == "Close":
                if not _manager(s,policy): raise PermissionDenied("Your configured Finance Request Policy does not authorise closure.")
                if status not in {"Resolved","Declined","Converted"}: raise ValidationError("Only resolved, declined or converted requests can be closed.")
                doc.request_status="Closed"; doc.closed_on=now
            else: raise ValidationError("Unsupported Finance request action.")
            _save(doc)
            if action == "Recommend Approval" and policy.get("workflow_definition") and not doc.workflow_instance:
                from velora.workflows import start as workflow_start
                instance=workflow_start(policy["workflow_definition"],"Finance Service Request",doc.name)
                doc.workflow_instance=instance.get("id")
                _save(doc)
            return {"name":doc.name,"request_status":doc.request_status,"assigned_to":doc.assigned_to,"linked_transaction_doctype":doc.linked_transaction_doctype,"linked_transaction":doc.linked_transaction}
        return run(request, fn)

    @app.get("/api/finance/requests/analytics")
    def finance_request_analytics(request: Request):
        def fn():
            s=get_session()
            policy=_policy()
            if not _finance(s,policy): raise PermissionDenied("Finance request analytics are restricted by Finance Request Policy.")
            from velora import get_list
            rows=get_list("Finance Service Request",fields=["name","request_type","request_status","requested_amount","approved_amount","submitted_on","resolved_on","priority","department"],limit=10000,ignore_permissions=True)
            statuses={}; types={}; requested=approved=0.0; resolved_hours=[]
            for row in rows:
                st=row.get("request_status") or "Unknown"; typ=row.get("request_type") or "Other"
                statuses[st]=statuses.get(st,0)+1; types[typ]=types.get(typ,0)+1
                try: requested+=float(row.get("requested_amount") or 0); approved+=float(row.get("approved_amount") or 0)
                except (TypeError,ValueError): pass
                if row.get("submitted_on") and row.get("resolved_on"):
                    try:
                        a=datetime.fromisoformat(str(row["submitted_on"]).replace("Z","+00:00")); b=datetime.fromisoformat(str(row["resolved_on"]).replace("Z","+00:00")); resolved_hours.append(max(0,(b-a).total_seconds()/3600))
                    except ValueError: pass
            return {"total":len(rows),"by_status":statuses,"by_type":types,"requested_amount":round(requested,2),"approved_amount":round(approved,2),"average_resolution_hours":round(sum(resolved_hours)/len(resolved_hours),2) if resolved_hours else None,"resolved_count":len(resolved_hours),"pending_count":sum(v for k,v in statuses.items() if k in ACTIVE)}
        return run(request, fn)
