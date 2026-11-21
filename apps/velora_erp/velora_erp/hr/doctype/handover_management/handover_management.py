"""Validation for leave and separation handover records."""
from velora import Document, throw

class HandoverManagement(Document):
    def validate(self):
        if self.handover_type not in {"Leave", "Separation"}:
            throw("Handover Type must be Leave or Separation.")
        expected = "Leave Application" if self.handover_type == "Leave" else "Employee Separation"
        if self.source_doctype != expected:
            throw("Handover Type and Source Document Type do not match.")
        if not self.employee or not self.source_reference:
            throw("Employee and Source Reference are required.")
        try:
            from velora import get_doc
            source=get_doc(self.source_doctype,self.source_reference,ignore_permissions=True)
            if getattr(source,"employee",None) != self.employee:
                throw("Handover Employee must match the employee on the linked source document.")
        except Exception as exc:
            if "Handover Employee" in str(exc): raise
            throw("The linked leave or separation source document could not be validated.")
        items=list(getattr(self,"handover_items",None) or [])
        seen=set()
        for item in items:
            task=str(getattr(item,"task","") or "").strip()
            if not task: throw("Every handover item requires a task description.")
            key=task.casefold()
            if key in seen: throw("Duplicate handover tasks are not allowed.")
            seen.add(key)
        self.outstanding_count=sum(1 for item in items if getattr(item,"handover_status","Pending") not in {"Accepted","Not Applicable"})
        if self.handover_status in {"Submitted","Partially Accepted","Accepted","Closed"} and not items:
            throw("A submitted handover must contain at least one task.")
        if self.handover_status in {"Accepted","Closed"} and self.outstanding_count:
            throw("All handover items must be Accepted or Not Applicable before final acceptance.")
        if self.handover_status == "Closed" and not getattr(self,"accepted_on",None):
            throw("A handover must be accepted before it can be closed.")
