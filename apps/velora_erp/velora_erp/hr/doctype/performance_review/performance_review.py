from datetime import datetime, timezone
from velora import Document, throw, get_doc, get_list
from velora.permissions import get_session
from velora_erp.hr.common import decided_now
class PerformanceReview(Document):
    def validate(self):
        cycle=get_doc("Performance Cycle",self.cycle,ignore_permissions=True)
        if cycle.status in ("Draft","Planning","Cancelled"): throw("Reviews can only be prepared in an active or review-stage Performance Cycle.")
        rows=list(getattr(self,"ratings",None) or [])
        for r in rows:
            for f in ("self_rating","manager_rating","final_rating"):
                v=getattr(r,f,None)
                if v not in (None,"") and not 0<=float(v)<=5: throw(f"{f.replace('_',' ').title()} must be between 0 and 5.")
        if self.calibrated_score not in (None,"") and not 0<=float(self.calibrated_score)<=5: throw("Calibrated score must be between 0 and 5.")
        if getattr(self,'employee',None) and self.cycle:
            for row in get_list("Performance Review",filters=[["employee","=",self.employee],["cycle","=",self.cycle],["review_type","=",self.review_type],["reviewer","=",self.reviewer]],fields=["name"],limit=5,ignore_permissions=True):
                if row.get("name")!=getattr(self,"name",None): throw(f"A {self.review_type or ''} review already exists for this employee and reviewer in the cycle ({row.get('name')}).")
        template=get_doc("Performance Review Template",cycle.review_template,ignore_permissions=True) if cycle.review_template else None
        if template:
            expected={str(getattr(r,"criterion_code","")).casefold():r for r in (getattr(template,"criteria",None) or [])}
            for row in rows:
                code=str(getattr(row,"criterion_code","")).casefold()
                if code not in expected: throw(f"Criterion {code} is not part of the selected review template.")
                row.weight=float(getattr(expected[code],"weight",0) or 0)
            if self.review_status in ("Pending Approval","Approved","Acknowledged","Closed"):
                missing=[code for code,r in expected.items() if getattr(r,"mandatory",1) and code not in {str(getattr(x,"criterion_code","")).casefold() for x in rows}]
                if missing: throw("Complete all mandatory review criteria before submitting for approval.")
        rated=[r for r in rows if getattr(r,"final_rating",None) not in (None,"")]
        if template and template.rating_method == "Weighted Average":
            denominator=sum(float(r.weight or 0) for r in rated)
            self.overall_score=round(sum(float(r.final_rating)*float(r.weight or 0) for r in rated)/denominator,2) if denominator else 0
        elif rated and template and template.rating_method == "Simple Average":
            self.overall_score=round(sum(float(r.final_rating) for r in rated)/len(rated),2)
        if self.calibrated_score not in (None,""): self.overall_score=float(self.calibrated_score)
        score=float(self.overall_score or 0)
        if score:
            self.overall_rating = "Exceptional" if score >= 4.5 else "Exceeds Expectations" if score >= 3.5 else "Meets Expectations" if score >= 2.5 else "Partially Meets" if score >= 1.5 else "Does Not Meet"
        if self.review_status == "Approved":
            s=get_session()
            if decided_now(self,"review_status"):
                self.approved_by=s.user; self.approved_on=datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
        if self.review_status in ("Pending Approval","Approved") and not rows: throw("Assessment ratings are required before approval.")
