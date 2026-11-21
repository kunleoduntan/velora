from datetime import date
from velora import Document, get_doc, throw
from velora.permissions import get_session


def _date(value):
    if not value:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _rows(value):
    return list(value or [])


_SYSTEM_KEYS = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "parent", "parenttype", "parentfield"}


def _signature(rows):
    """Business content of child rows, ignoring bookkeeping columns, so an unchanged re-save is not mistaken for an edit."""
    out = []
    for row in rows or []:
        data = row.as_dict() if hasattr(row, "as_dict") else dict(row)
        out.append(tuple(sorted((k, str(v) if v not in (None, "") else "") for k, v in data.items() if k not in _SYSTEM_KEYS)))
    return sorted(out)


class LeavePolicy(Document):
    def validate(self):
        start, end = _date(self.effective_from), _date(self.effective_to)
        if not self.policy_code or not self.policy_name:
            throw("Policy Code and Policy Name are required.")
        if int(self.policy_version or 0) < 1:
            throw("Policy Version must be at least 1.")
        if not start or (end and end < start):
            throw("Enter a valid Leave Policy effective date range.")
        if not self.entitlements:
            throw("A Leave Policy must contain at least one leave entitlement.")
        seen = set()
        for row in _rows(self.entitlements):
            if not row.leave_type or row.leave_type in seen:
                throw("Each Leave Policy must contain a unique Leave Type.")
            seen.add(row.leave_type)
            if float(row.annual_entitlement_days or 0) < 0:
                throw("Annual entitlement days cannot be negative.")
            if float(row.maximum_carry_forward_days or 0) < 0:
                throw("Maximum carry-forward days cannot be negative.")
            leave_type = get_doc("Leave Type", row.leave_type, ignore_permissions=True)
            if leave_type.disabled:
                throw(f"Leave Type {row.leave_type} is disabled.")
            if row.allow_carry_forward and not leave_type.carry_forward_allowed:
                throw(f"{row.leave_type} does not permit carry-forward in its Leave Type setup.")
            if row.allow_carry_forward and leave_type.maximum_carry_forward_days and float(row.maximum_carry_forward_days or 0) > float(leave_type.maximum_carry_forward_days):
                throw(f"The policy carry-forward cap for {row.leave_type} exceeds the Leave Type maximum.")
        for rule in _rows(self.eligibility_rules):
            if int(rule.rule_group or 0) < 1:
                throw("Eligibility rule groups must be numbered from 1.")
            if rule.field_name == "Employee Category":
                if not rule.category_name or not rule.category_value:
                    throw("Classification Category and Classification Value are required for Employee Category eligibility rules.")
                category = get_doc("Employee Classification Category", rule.category_name, ignore_permissions=True)
                value = get_doc("Employee Classification Value", rule.category_value, ignore_permissions=True)
                if category.disabled or value.disabled or value.category != rule.category_name:
                    throw("Eligibility Classification Value must be active and belong to the selected Category.")
            elif rule.operator not in {"Is Set", "Is Not Set"} and not str(rule.value or "").strip():
                throw("A value is required for this eligibility rule.")
        old = getattr(self, "_old", None) or {}
        if old.get("status") == "Active" and self.status == "Active":
            for field in ("policy_code", "policy_name", "policy_version", "effective_from", "effective_to"):
                if str(old.get(field) or "")[:10] != str(getattr(self, field, None) or "")[:10]:
                    throw("An active Leave Policy is immutable. Create a new policy version and retire the old version instead.")
            stored = get_doc("Leave Policy", self.name, ignore_permissions=True)
            for table in ("eligibility_rules", "entitlements"):
                if _signature(getattr(stored, table, None)) != _signature(getattr(self, table, None)):
                    throw("An active Leave Policy is immutable. Create a new policy version and retire the old version instead.")
