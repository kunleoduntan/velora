from velora import Document, get_doc, throw

class CustomerComplaint(Document):
    def validate(self):
        old = getattr(self, "_old", None) or {}
        previous = old.get("resolution_status")
        allowed = {
            "Open": {"Open", "Under Investigation", "Awaiting Customer", "Resolved", "Rejected"},
            "Under Investigation": {"Under Investigation", "Awaiting Customer", "Resolved", "Rejected"},
            "Awaiting Customer": {"Awaiting Customer", "Under Investigation", "Resolved", "Rejected"},
            "Resolved": {"Resolved", "Closed", "Under Investigation"},
            "Closed": {"Closed"},
            "Rejected": {"Rejected", "Under Investigation"},
        }
        if previous and self.resolution_status not in allowed.get(previous, {previous}):
            throw(f"Complaint status cannot move from {previous} to {self.resolution_status}.")
        customer=get_doc("Customer",self.customer)
        if customer.disabled: throw("Select an active Customer.")
        if self.sales_invoice:
            invoice=get_doc("Sales Invoice",self.sales_invoice)
            if invoice.party!=self.customer or int(invoice.docstatus or 0)!=1: throw("Complaint Sales Invoice must be submitted and belong to the selected Customer.")
        if self.delivery_note:
            note=get_doc("Delivery Note",self.delivery_note)
            if note.party!=self.customer or int(note.docstatus or 0)!=1: throw("Complaint Delivery Note must be submitted and belong to the selected Customer.")
        if self.resolution_status in ("Resolved","Closed") and not str(self.resolution or "").strip():
            throw("A resolution description is required before a complaint can be resolved or closed.")
        if self.resolution_status in ("Resolved","Closed") and not self.resolved_on:
            throw("Resolved On date is required before a complaint can be resolved or closed.")
        if self.related_return:
            ret=get_doc("Sales Return",self.related_return)
            if ret.party!=self.customer: throw("Related Sales Return must belong to the complaint Customer.")
        if self.related_replacement_order:
            order=get_doc("Sales Order",self.related_replacement_order)
            if order.party!=self.customer: throw("Replacement Sales Order must belong to the complaint Customer.")
