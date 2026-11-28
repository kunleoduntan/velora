"""Finance service request controls; requests never create ledger postings."""
from datetime import datetime, timezone
import json
from decimal import Decimal, InvalidOperation
from velora import Document, throw, get_doc
from velora.permissions import get_session

_ACTIVE = {"Submitted", "Under Review", "Waiting for Information", "Pending Approval"}
_FINAL = {"Approved", "Declined", "Converted", "Resolved", "Closed"}

class FinanceServiceRequest(Document):
    def validate(self):
        session = get_session()
        from velora import get_list
        policies=get_list("Finance Request Policy",filters=[["enabled","=",1]],fields=["finance_roles","manager_roles"],limit=500,ignore_permissions=True)
        applicable=policies
        if len(applicable)!=1: throw("Configure exactly one enabled Finance Request Policy before using Finance eRequest.")
        policy=applicable[0]
        try: finance_roles=set(json.loads(policy.get("finance_roles") or "[]"))
        except Exception: throw("Finance Request Policy Finance Roles must be valid JSON.")
        roles = set(getattr(session, "roles", ()) or ())
        is_finance = session.user == "Administrator" or bool(roles.intersection(finance_roles))
        if not self.requester:
            throw("Requester is required.")
        if not (self.subject or "").strip() or not (self.business_purpose or "").strip():
            throw("Subject and Business Purpose are required.")
        if self.requested_amount not in (None, ""):
            try:
                amount = Decimal(str(self.requested_amount))
            except (InvalidOperation, ValueError):
                throw("Requested Amount must be a valid number.")
            if amount < 0:
                throw("Requested Amount cannot be negative.")
        if self.linked_transaction and not self.linked_transaction_doctype:
            throw("Linked Financial Transaction Type is required when a transaction is linked.")
        if not is_finance:
            employee = get_doc("Employee", self.requester, ignore_permissions=True)
            if employee.disabled or (employee.user_account or "").casefold() != str(session.user or "").casefold():
                throw("You may only submit a Finance request for your own active Employee account.")
            if self.request_status not in {None, "", "Submitted", "Waiting for Information", "Under Review"}:
                throw("Employees cannot review, approve, decline, convert or close Finance requests.")
            if self.assigned_to or self.approval_reference or self.resolution_notes or self.resolved_on or self.approved_amount:
                throw("Employees cannot change Finance assignment, approval or resolution fields.")
        else:
            if self.request_status in _FINAL and self.request_status in {"Declined", "Resolved", "Closed"} and not (self.resolution_notes or "").strip():
                throw("Resolution Notes are required before declining, resolving or closing a request.")
            if self.request_status == "Converted" and not (self.linked_transaction or "").strip():
                throw("A linked financial transaction is required before marking a request Converted.")
            if self.request_status in {"Resolved", "Closed", "Declined", "Converted"} and not self.resolved_on:
                self.resolved_on = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    def before_submit(self):
        # Submission records a request only; it does not create any financial entry.
        if self.request_status not in _ACTIVE | _FINAL:
            throw("Select a valid Finance request status.")
