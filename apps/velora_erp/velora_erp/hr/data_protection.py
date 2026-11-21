"""Default field protection for personal and statutory employee data.

Roles that need to *see an employee* (finance, audit, payroll) rarely need to see their identity documents, home
address, date of birth or bank account. These are ordinary field-access rules in the permission editor, installed only
where no rule exists yet, so an administrator can change or remove any of them from the GUI.
"""
from __future__ import annotations
from sqlalchemy import and_, insert, select

PERSONAL = ["date_of_birth", "national_id_number", "personal_email", "current_address", "permanent_address", "marital_status",
            "blood_group", "nationality", "emergency_contact_phone", "religion"]
STATUTORY = ["tax_id", "pension_pin", "nhf_number", "bank_name", "bank_account_name", "bank_account_no"]

DEFAULTS = {
    "Finance Manager": PERSONAL,
    "Accountant": PERSONAL + STATUTORY,
    "Auditor": PERSONAL + STATUTORY,
    "Payroll Officer": PERSONAL,
    "Payroll Manager": PERSONAL,
    "Employee Finance Officer": PERSONAL + STATUTORY,
    "Department Manager": PERSONAL + STATUTORY,          # a manager sees their staff's work details, not identity documents, home address or bank account
}


def apply_default_field_protection(doctype: str = "Employee") -> int:
    from velora import db
    from velora.db.system import role_field_permission as t
    from velora.meta.registry import registry
    meta = registry.get(doctype)
    known = {f.fieldname for f in meta.fields}
    added = 0
    with db.transaction() as c:
        for role, fields in DEFAULTS.items():
            for fieldname in fields:
                if fieldname not in known: continue
                if c.execute(select(t.c.role).where(and_(t.c.role == role, t.c.doctype == doctype, t.c.fieldname == fieldname))).first(): continue
                c.execute(insert(t).values(role=role, doctype=doctype, fieldname=fieldname, access="hidden")); added += 1
    return added


# Approval state is decided by the workflow engine, never typed in by the person who made the request.
EMPLOYEE_STATE_FIELDS = {
    "Leave Application": ["workflow_status", "approval_notes"], "Overtime Request": ["approval_status"],
    "Material Request": ["request_status"], "HR Service Request": ["request_status", "status"],
}


def apply_employee_state_protection() -> int:
    from velora import db
    from velora.db.system import role_field_permission as t
    from velora.meta.registry import registry
    added = 0
    with db.transaction() as c:
        for doctype, fields in EMPLOYEE_STATE_FIELDS.items():
            try: known = {f.fieldname for f in registry.get(doctype).fields}
            except Exception: continue
            for fieldname in fields:
                if fieldname not in known: continue
                if c.execute(select(t.c.role).where(and_(t.c.role == "Employee", t.c.doctype == doctype, t.c.fieldname == fieldname))).first(): continue
                c.execute(insert(t).values(role="Employee", doctype=doctype, fieldname=fieldname, access="read_only")); added += 1
    return added
