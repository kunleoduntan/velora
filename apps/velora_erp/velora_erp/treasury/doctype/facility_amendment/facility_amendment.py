from decimal import Decimal

from velora import Document, get_doc, throw
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.source_documents import ensure_approved, validate_approval_transition
from velora_erp.treasury import service as svc

D = svc.D


class FacilityAmendment(Document):
    def validate(self):
        fac = get_doc("Financing Facility", self.facility, ignore_permissions=True)
        if fac.docstatus != 1:
            throw("Choose a submitted facility.")
        if not (self.new_interest_rate or self.new_approved_limit or self.new_expiry_date):
            throw("Enter at least one change: a new rate, limit or end date.")
        if self.new_interest_rate and float(self.new_interest_rate) < 0:
            throw("The new rate cannot be negative.")
        if self.new_approved_limit and D(self.new_approved_limit) < D(fac.outstanding_principal):
            throw(f"The new limit cannot be below the {D(fac.outstanding_principal):,.2f} already outstanding.")
        if self.new_expiry_date and svc.as_date(self.new_expiry_date) < svc.as_date(fac.start_date):
            throw("The new end date cannot be before the facility started.")
        later = svc.submitted("Facility Amendment", [["facility", "=", self.facility], ["effective_date", ">", self.effective_date]], ["name"], limit=1)
        if later and self.docstatus == 0:
            throw(f"{later[0]['name']} is effective later; record amendments in date order.")
        if self.docstatus == 0:
            self.old_interest_rate, self.old_approved_limit, self.old_expiry_date = fac.interest_rate, fac.approved_limit, fac.expiry_date
        self.title = f"{fac.facility_name} from {self.effective_date}"
        validate_approval_transition(self)

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        fac = get_doc("Financing Facility", self.facility, ignore_permissions=True)
        change = {}
        if self.new_interest_rate:
            change["interest_rate"] = self.new_interest_rate
        if self.new_approved_limit:
            change["approved_limit"] = self.new_approved_limit
        if self.new_expiry_date:
            change["expiry_date"] = self.new_expiry_date
        db_update(fac, **change)
        if self.new_interest_rate and fac.interest_rate_type == "Floating":
            svc.reprice(self.facility)
        svc.refresh_facility(self.facility)

    def before_cancel(self):
        later = svc.submitted("Facility Amendment", [["facility", "=", self.facility], ["effective_date", ">", self.effective_date]], ["name"], limit=1)
        if later:
            throw(f"{later[0]['name']} was made after this amendment; cancel that one first.")


def on_cancelled(doc, report):
    fac = get_doc("Financing Facility", doc.facility, ignore_permissions=True)
    change = {}
    if doc.new_interest_rate:
        change["interest_rate"] = doc.old_interest_rate
    if doc.new_approved_limit:
        change["approved_limit"] = doc.old_approved_limit
    if doc.new_expiry_date:
        change["expiry_date"] = doc.old_expiry_date
    db_update(fac, **change)
    if doc.new_interest_rate and fac.interest_rate_type == "Floating":
        svc.reprice(doc.facility)
    svc.refresh_facility(doc.facility)
