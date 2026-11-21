from datetime import datetime
from velora import Document, throw, get_doc
from velora.permissions import get_session
from velora_erp.hr.common import decided_now
class PerformanceCalibrationSession(Document):
    def validate(self):
        cycle=get_doc("Performance Cycle",self.cycle,ignore_permissions=True)
        if cycle.status in ("Draft","Planning","Cancelled"): throw("Calibration requires an active performance cycle.")
        seen=set()
        for row in list(getattr(self,"calibration_items",None) or []):
            review=str(getattr(row,"review","") or "")
            if not review or review in seen: throw("A review may appear only once in a calibration session.")
            seen.add(review); source=get_doc("Performance Review",review,ignore_permissions=True)
            if source.cycle != self.cycle: throw("Every calibrated review must belong to the selected cycle.")
            original=float(getattr(source,"overall_score",0) or 0)
            row.original_score=original; row.original_rating=getattr(source,"overall_rating",None)
            proposed=getattr(row,"proposed_score",None)
            if proposed not in (None,"") and not 0 <= float(proposed) <= 5: throw("Calibrated score must be between 0 and 5.")
            if getattr(row,"decision",None) in ("Accepted","Rejected") and not str(getattr(row,"rationale","") or "").strip(): throw("Document the rationale for every calibration decision.")
        if self.status in ("Pending Approval","Approved","Closed") and not seen: throw("Add at least one review to the calibration session.")
        if self.status == "Approved":
            if decided_now(self,"status"):
                self.approved_by=get_session().user; self.approved_on=datetime.utcnow().replace(microsecond=0)
