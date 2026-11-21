from datetime import date
from velora import Document, throw, get_doc
class PerformanceRaterCampaign(Document):
    def validate(self):
        cycle=get_doc("Performance Cycle",self.cycle,ignore_permissions=True)
        if cycle.status in ("Draft","Planning","Cancelled"): throw("Rater campaigns require an active performance cycle.")
        if self.review:
            review=get_doc("Performance Review",self.review,ignore_permissions=True)
            if review.cycle != self.cycle: throw("Campaign Review must belong to the selected Performance Cycle.")
        if self.opens_on and self.closes_on and str(self.closes_on)<str(self.opens_on): throw("Campaign closing date cannot precede opening date.")
        if int(self.minimum_raters or 0)<1: throw("Minimum Raters must be at least one.")
        rows=list(getattr(self,"nominations",None) or []); seen=set(); submitted_by_employee={}; employees=set()
        for row in rows:
            rater=str(getattr(row,"rater","") or ""); employee=str(getattr(row,"employee","") or "")
            if not rater or not employee: throw("Each nomination requires an employee and a rater.")
            if rater==employee: throw("An employee cannot provide 360-degree feedback for themselves.")
            key=(employee,rater)
            if key in seen: throw("A rater may be nominated only once for an employee in a campaign.")
            seen.add(key); employees.add(employee)
            if getattr(row,"status",None)=="Submitted": submitted_by_employee[employee]=submitted_by_employee.get(employee,0)+1
        submitted=sum(submitted_by_employee.values())
        self.completion_percent=round(submitted/len(rows)*100,1) if rows else 0
        if self.status=="Completed":
            below=[employee for employee in employees if submitted_by_employee.get(employee,0)<int(self.minimum_raters or 1)]
            if below: throw("The campaign cannot be completed until every employee has received the minimum number of rater responses.")
