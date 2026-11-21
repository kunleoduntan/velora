from datetime import datetime, date, timedelta
import json
from velora import Document, throw, get_doc, get_list
from velora.permissions import get_session

def _d(v): return v if isinstance(v,date) else (date.fromisoformat(str(v)[:10]) if v else None)
def _rows(value):
    if isinstance(value,str):
        try: value=json.loads(value or "[]")
        except Exception: return []
    return value if isinstance(value,list) else []
def _refresh(*names):
    from velora_erp.hr.doctype.leave_allocation.leave_allocation import refresh_balances
    for name in {n for n in names if n}:
        refresh_balances(name)


class LeaveApplication(Document):
    def on_update(self):
        _refresh(self.leave_allocation,(getattr(self,"_old",None) or {}).get("leave_allocation"))

    def after_delete(self):
        _refresh(self.leave_allocation)

    def validate(self):
        start,end=_d(self.from_date),_d(self.to_date)
        if not start or not end: return
        if end < start: throw("Leave end date cannot precede start date.")
        try: employee=get_doc("Employee",self.employee,ignore_permissions=True) if self.employee else None
        except Exception: employee=None
        if employee and self.workflow_status in {"Pending Approval","Approved"}:
            if employee.get("employment_status") in {"Left","Suspended"}: throw(f"Leave cannot be requested for an employee whose status is {employee.get('employment_status')}.")
            if employee.get("date_of_joining") and start<_d(employee.date_of_joining): throw("Leave cannot start before the employee's joining date.")
        if self.half_day and start != end: throw("Half-day leave must be for one date only.")
        policy=get_doc("Leave Type",self.leave_type,ignore_permissions=True)
        if policy.disabled: throw("This leave type is disabled.")
        if self.half_day and not policy.allow_half_day: throw("Half-day leave is not permitted for this leave type.")
        if policy.requires_attachment and not self.supporting_document: throw("A supporting document is required for this leave type.")
        holidays=set()
        if not self.holiday_list:
            periods=get_list("Leave Period",filters=[["period_status","=","Open"],["from_date","<=",start.isoformat()],["to_date",">=",end.isoformat()]],fields=["holiday_list"],limit=5,ignore_permissions=True)
            self.holiday_list=next((p.get("holiday_list") for p in periods if p.get("holiday_list")),None)
        if self.holiday_list:
            holiday_doc=get_doc("Holiday List",self.holiday_list,ignore_permissions=True)
            holidays={str(x)[:10] for x in _rows(holiday_doc.holiday_dates)}
        days=0; cursor=start
        while cursor<=end:
            is_weekend=cursor.weekday()>=5
            if (policy.include_weekends or not is_weekend) and cursor.isoformat() not in holidays: days+=1
            cursor+=timedelta(days=1)
        self.total_days=0.5 if self.half_day else float(days)
        if self.total_days<=0: throw("The selected leave period contains no working days.")
        if policy.max_consecutive_days and self.total_days>int(policy.max_consecutive_days): throw("Requested leave exceeds the maximum consecutive days allowed by policy.")
        old=getattr(self,"_old",None) or {}
        status_changed=old.get("workflow_status")!=self.workflow_status
        if old and not status_changed and self.workflow_status in {"Approved","Completed"}:
            # an approved leave is a decision: its dates, type and allocation cannot change without a new approval
            for f in ("employee","leave_type","leave_allocation","from_date","to_date","half_day"):
                if str(old.get(f) or "")[:10]!=str(getattr(self,f,None) or "")[:10] and not (f=="half_day" and int(old.get(f) or 0)==int(getattr(self,f,0) or 0)):
                    throw(f"An {self.workflow_status.lower()} leave application cannot be changed ({f.replace('_',' ')}). Cancel it and submit a new request.")
        if self.workflow_status in {"Approved","Rejected","Completed"} and status_changed:
            s=get_session()
            self.approved_by=s.user; self.approved_on=datetime.utcnow().replace(microsecond=0)
        if self.workflow_status=="Pending Approval" and getattr(policy,'minimum_notice_days',0) and (start-date.today()).days<int(policy.minimum_notice_days) and not getattr(self,"_old",None):
            throw(f"This leave type needs at least {int(policy.minimum_notice_days)} days' notice.")
        if self.workflow_status in {"Pending Approval","Approved","Completed"}:
            if not self.leave_allocation: throw("A leave request submitted for approval must reference a leave allocation.")
            allocation=get_doc("Leave Allocation",self.leave_allocation,ignore_permissions=True)
            if allocation.allocation_status!="Approved": throw("Leave can only be requested against an approved allocation.")
            if allocation.employee!=self.employee or allocation.leave_type!=self.leave_type: throw("Leave allocation employee and leave type must match the application.")
            if start<_d(allocation.period_start) or end>_d(allocation.period_end): throw("Leave dates must fall within the allocation period.")
            old_status=(getattr(self,"_old",None) or {}).get("workflow_status")
            if self.workflow_status=="Completed":
                if end>date.today(): throw("Leave cannot be marked completed before its end date.")
            if self.workflow_status in {"Pending Approval","Approved"}:
                history=get_list("Leave Application",filters=[["leave_allocation","=",self.leave_allocation],["workflow_status","in",["Pending Approval","Approved","Completed"]]],fields=["name","total_days","workflow_status"],limit=1000,ignore_permissions=True)
                used=sum(float(x.get("total_days") or 0) for x in history if x.get("workflow_status")=="Completed")
                reserved=sum(float(x.get("total_days") or 0) for x in history if x.get("workflow_status" ) in {"Pending Approval","Approved"} and x.get("name")!=getattr(self,"name",None))
                entitlement=float(allocation.allocated_days or 0)+float(allocation.carry_forward_days or 0)+float(allocation.adjustment_days or 0)
                if entitlement-used-reserved < self.total_days and not getattr(policy,'allow_negative_balance',0): throw("Insufficient available leave balance after existing reservations and completed leave.")
            self.payroll_treatment="Paid Leave" if policy.is_paid else "Unpaid Leave"
        else: self.payroll_treatment="Not Applicable"
        # Block overlapping active requests for the same employee.
        if self.workflow_status in {"Pending Approval","Approved","Completed"}:
            existing=get_list("Leave Application",filters=[["employee","=",self.employee],["workflow_status","in",["Pending Approval","Approved","Completed"]]],fields=["name","from_date","to_date","half_day","half_day_period"],limit=1000,ignore_permissions=True)
            for row in existing:
                if row.get("name")==getattr(self,"name",None): continue
                if self.half_day and row.get("half_day") and self.half_day_period and row.get("half_day_period") and self.half_day_period!=row.get("half_day_period") and _d(row.get("from_date"))==start: continue   # morning + afternoon of one day do not clash
                a,b=_d(row.get("from_date")),_d(row.get("to_date"))
                if a and b and start<=b and end>=a: throw("This leave request overlaps another pending or approved leave application.")
