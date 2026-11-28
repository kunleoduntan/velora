from datetime import datetime, timezone
from velora import Document, get_list, throw
from velora.permissions import get_session
from velora_erp.hr.common import decided_now
from velora_erp.hr import staffing


def _g(row, key): return row.get(key) if isinstance(row, dict) else getattr(row, key, None)
def _s(row, key, value):
    if isinstance(row, dict): row[key] = value
    else: setattr(row, key, value)


class DepartmentStaffBudget(Document):
    def validate(self):
        start, end = staffing.as_date(self.from_date), staffing.as_date(self.to_date)
        if not start or not end or end < start: throw("The budget period must have an end date on or after its start date.")
        lines = list(self.lines or [])
        if not lines: throw("Add at least one designation to the staff budget.")
        seen, months = set(), staffing.months_between(start, end)
        total = {"head": 0, "filled": 0, "committed": 0, "vacant": 0, "cost": 0.0}
        for i, row in enumerate(lines, 1):
            des = _g(row, "designation")
            if not des: throw(f"Line {i}: choose a designation.")
            key = (des, _g(row, "employment_type") or "")
            if key in seen: throw(f"Line {i}: {des} appears twice for the same employment type; combine the headcount in one line.")
            seen.add(key)
            hc = int(_g(row, "budgeted_headcount") or 0)
            if hc < 0: throw(f"Line {i}: budgeted headcount cannot be negative.")
            cost = float(_g(row, "monthly_cost_per_head") or 0)
            if cost < 0: throw(f"Line {i}: monthly cost cannot be negative.")
            fl = staffing.filled(self.department, des)
            cm = staffing.committed(self.department, des, start=start, end=end)
            _s(row, "annual_cost", round(hc * cost * months, 2)); _s(row, "filled", fl); _s(row, "committed", cm)
            _s(row, "vacant", max(0, hc - fl - cm))
            total["head"] += hc; total["filled"] += fl; total["committed"] += cm; total["vacant"] += max(0, hc - fl - cm); total["cost"] += hc * cost * months
        self.total_budgeted_headcount, self.total_filled, self.total_committed, self.total_vacant = total["head"], total["filled"], total["committed"], total["vacant"]
        self.total_annual_cost = round(total["cost"], 2)
        if self.budget_status in ("Pending Approval", "Approved"):
            for b in get_list("Department Staff Budget", filters=[["department", "=", self.department], ["budget_status", "=", "Approved"]], fields=["name", "from_date", "to_date"], limit=1000, ignore_permissions=True):
                if b["name"] == getattr(self, "name", None): continue
                a, z = staffing.as_date(b["from_date"]), staffing.as_date(b["to_date"])
                if a and z and start <= z and end >= a and self.budget_status == "Approved":
                    throw(f"{b['name']} is already approved for this department over an overlapping period. Close it or change the dates.")
        if self.budget_status == "Approved" and decided_now(self, "budget_status"):
            self.approved_by = get_session().user; self.approved_on = datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
