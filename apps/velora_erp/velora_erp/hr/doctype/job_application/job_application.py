from velora import Document, throw, get_list, get_doc

class JobApplication(Document):
    def validate(self):
        if self.application_stage == "Rejected" and not self.rejection_reason:
            throw("Provide a rejection reason for audit and candidate communication.")
        if self.candidate and self.requisition:
            for row in get_list("Job Application",filters=[["candidate","=",self.candidate],["requisition","=",self.requisition],["application_stage","!=","Rejected"]],fields=["name"],limit=5,ignore_permissions=True):
                if row.get("name")!=getattr(self,"name",None): throw(f"This candidate already has an open application ({row.get('name')}) for the same requisition.")
        if self.application_stage == "Hired":
            if not self.offer: throw("A hired application must reference its approved job offer.")
            offer=get_doc("Job Offer",self.offer,ignore_permissions=True)
            if offer.decision!="Accepted": throw("A hired application needs an offer that the candidate has accepted.")
