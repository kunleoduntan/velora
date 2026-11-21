from datetime import datetime, date
from velora import Document, throw, get_doc
from velora.permissions import get_session
from velora_erp.hr.common import decided_now

def _d(v): return v if isinstance(v,date) else (date.fromisoformat(str(v)[:10]) if v else None)
class JobOffer(Document):
    def validate(self):
        if _d(self.offer_expiry_date) and _d(self.offer_date) and _d(self.offer_expiry_date) < _d(self.offer_date):
            throw("Offer expiry cannot be earlier than the offer date.")
        if self.gross_compensation is not None and float(self.gross_compensation or 0)<0: throw("Offered compensation cannot be negative.")
        if _d(self.proposed_start_date) and _d(self.offer_date) and _d(self.proposed_start_date)<_d(self.offer_date): throw("The proposed start date cannot precede the offer date.")
        if self.decision=="Accepted" and _d(self.offer_expiry_date) and _d(self.offer_expiry_date)<date.today() and not (getattr(self,"_old",None) or {}).get("decision")=="Accepted":
            throw("This offer has expired and can no longer be accepted.")
        if self.approval_status in {"Approved","Rejected"}:
            s=get_session()
            if decided_now(self,"approval_status"):
                self.approved_by=s.user; self.approved_on=datetime.utcnow().replace(microsecond=0)
        if self.decision == "Accepted" and self.approval_status != "Approved":
            throw("A candidate cannot accept an offer until it has been approved.")
        if self.converted_employee and self.decision != "Accepted":
            throw("Only an accepted offer can be linked to a converted Employee.")
