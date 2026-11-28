from datetime import datetime, date, timezone
from velora import Document, throw, get_list, get_doc
from velora.permissions import get_session
def _d(v): return v if isinstance(v,date) else (date.fromisoformat(str(v)[:10]) if v else None)
def balances(name, allocated=0, carry=0, adjustment=0):
    """Used, pending and available days for an allocation, worked out from its leave applications."""
    rows = get_list("Leave Application", filters=[["leave_allocation", "=", name], ["workflow_status", "in", ["Pending Approval", "Approved", "Completed"]]],
                    fields=["total_days", "workflow_status"], limit=100000, ignore_permissions=True)
    used = round(sum(float(x.get("total_days") or 0) for x in rows if x.get("workflow_status") == "Completed"), 2)
    pending = round(sum(float(x.get("total_days") or 0) for x in rows if x.get("workflow_status") in ("Pending Approval", "Approved")), 2)
    return used, pending, round(float(allocated or 0) + float(carry or 0) + float(adjustment or 0) - used - pending, 2)


def refresh_balances(name):
    """Bring the stored used/pending/available days up to date after a leave application changes (reports read these columns)."""
    if not name:
        return
    from velora_erp.finance.doctype._utils import db_update
    try:
        allocation = get_doc("Leave Allocation", name, ignore_permissions=True)
    except Exception:  # noqa: BLE001 - the allocation was removed
        return
    used, pending, available = balances(name, allocation.allocated_days, allocation.carry_forward_days, allocation.adjustment_days)
    db_update(allocation, used_days=used, pending_days=pending, available_days=available)


class LeaveAllocation(Document):
    def validate(self):
        start,end=_d(self.period_start),_d(self.period_end)
        if start and end and end<start: throw("Leave allocation period end cannot precede its start.")
        if min(float(self.allocated_days or 0),float(self.carry_forward_days or 0))<0: throw("Leave allocation days cannot be negative.")
        policy=get_doc("Leave Type",self.leave_type,ignore_permissions=True) if self.leave_type else None
        if self.carry_forward_days and policy and not policy.carry_forward_allowed: throw("This leave type does not permit carry-forward.")
        if policy and policy.maximum_carry_forward_days and float(self.carry_forward_days or 0)>float(policy.maximum_carry_forward_days): throw("Carry-forward days exceed the leave policy maximum.")
        if getattr(self, "name", None):
            self.used_days, self.pending_days, self.available_days = balances(self.name, self.allocated_days, self.carry_forward_days, self.adjustment_days)
        else:
            self.used_days = self.pending_days = 0
            self.available_days = round(float(self.allocated_days or 0) + float(self.carry_forward_days or 0) + float(self.adjustment_days or 0), 2)
        if self.allocation_status=="Approved":
            s=get_session()
            from velora_erp.hr.common import decided_now
            if decided_now(self,"allocation_status"):
                self.approved_by=s.user; self.approved_on=datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
        if self.allocation_status=="Closed" and self.available_days<0: throw("A leave allocation with a negative balance cannot be closed.")
        if self.employee and self.leave_type and start and end:
            rows=get_list("Leave Allocation",filters=[["employee","=",self.employee],["leave_type","=",self.leave_type]],fields=["name","period_start","period_end"],limit=1000,ignore_permissions=True)
            for row in rows:
                if row.get("name")==getattr(self,"name",None): continue
                a,b=_d(row.get("period_start")),_d(row.get("period_end"))
                if a and b and start<=b and end>=a: throw("An employee cannot have overlapping allocations for the same leave type.")
