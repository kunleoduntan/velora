"""Employee property custody and return validation."""
from datetime import date
from velora import Document, throw
from velora.permissions import get_session


def _date(value):
    if not value:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


class EmployeeAssetAssignment(Document):
    def validate(self):
        if not (self.asset_reference or "").strip() or not (self.asset_description or "").strip():
            throw("Asset Reference and Asset Description are required.")
        assigned = _date(self.assigned_on)
        expected = _date(self.expected_return_date)
        returned = _date(self.returned_on)
        if expected and assigned and expected < assigned:
            throw("Expected Return Date cannot be earlier than Assigned On.")
        if self.assignment_status in {"Issued", "Returned", "Lost", "Written Off"}:
            if not assigned or not (self.issued_by or "").strip():
                throw("Issued assets require an Assigned On date and Issued By.")
            if not self.employee_acknowledged:
                throw("Employee acknowledgement is required before an asset can be issued.")
        if self.assignment_status == "Returned":
            if not returned or returned < assigned:
                throw("A returned asset requires a valid Returned On date not earlier than Assigned On.")
            if not self.condition_on_return or not (self.received_by or "").strip():
                throw("Condition on Return and Received By are required to complete an asset return.")
        if self.assignment_status in {"Lost", "Written Off"}:
            if not (self.return_notes or "").strip():
                throw("A documented reason is required for Lost or Written Off assets.")
