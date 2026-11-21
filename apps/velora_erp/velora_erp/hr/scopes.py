"""Who may see whose records: the record scopes behind the default row policies.

* ``own_employee``      - the signed-in person's own employee record(s).
* ``department_staff``  - the person plus everyone in the departments they head (sub-departments included) and
                          everyone who reports directly to them. This is what a Department Manager sees.
* ``managed_departments`` - the departments they head (for records that carry a department, such as a stock request).

HR Manager, HR Officer, System Manager and every other role that is granted a document and has no policy of its own
see everything: access is the union of what a person's roles allow. Policies are ordinary row policies, so an
administrator can change or remove any of them in the permission editor.
"""
from __future__ import annotations

SCOPES = frozenset({"own_employee", "department_staff", "managed_departments"})

# doctype -> the field that names the employee (or department) a record belongs to
EMPLOYEE_FIELD = {
    "Employee": "name", "Leave Application": "employee", "Leave Allocation": "employee", "Attendance": "employee",
    "Overtime Request": "employee", "Shift Assignment": "employee", "HR Service Request": "employee",
    "Career Development Plan": "employee", "Performance Cycle Assignment": "employee", "Reporting Assignment": "employee",
    "Employee Asset Assignment": "employee", "Salary Slip": "employee", "Finance Service Request": "requester",
    "Material Request": "requester",
}
DEPARTMENT_FIELD = {}   # Material Request is scoped by requester for employees and by department for managers (see MANAGER_FIELD)
MANAGER_FIELD = {"Material Request": "department"}
PERMISSIONS = ("read", "write", "create", "delete", "submit", "cancel", "amend")


def _employees(**filters):
    from velora import get_list
    return get_list("Employee", filters=filters or {}, fields=["name", "department", "reports_to", "user_account"], limit=100000, ignore_permissions=True)


def _mine(session):
    user = (getattr(session, "user", "") or "").strip().lower()
    if not user: return []
    return [e for e in _employees() if (e.get("user_account") or "").strip().lower() == user]


def _managed_departments(session):
    from velora import get_list
    mine = {e["name"] for e in _mine(session)}
    if not mine: return []
    departments = get_list("Department", fields=["name", "department_head", "parent_department"], limit=100000, ignore_permissions=True)
    managed = {d["name"] for d in departments if d.get("department_head") in mine}
    grew = True
    while grew:                                            # sub-departments belong to the manager of their parent
        grew = False
        for d in departments:
            if d["name"] not in managed and d.get("parent_department") in managed:
                managed.add(d["name"]); grew = True
    return sorted(managed)


def resolve_scope(name, session):
    if name == "own_employee":
        return [e["name"] for e in _mine(session)]
    if name == "managed_departments":
        return _managed_departments(session)
    if name == "department_staff":
        mine = {e["name"] for e in _mine(session)}
        if not mine: return []
        departments = set(_managed_departments(session))
        staff = set(mine)
        for e in _employees():
            if e.get("department") in departments or e.get("reports_to") in mine:
                staff.add(e["name"])
        return sorted(staff)
    raise KeyError(name)


def default_policies():
    """(role, doctype, permission, conditions) rows installed where no policy exists yet."""
    rows = []
    for doctype, field in EMPLOYEE_FIELD.items():
        for permission in PERMISSIONS:
            rows.append(("Employee", doctype, permission, [{"field": field, "operator": "in_scope", "value": "own_employee"}]))
            if doctype in MANAGER_FIELD:
                rows.append(("Department Manager", doctype, permission, [{"field": MANAGER_FIELD[doctype], "operator": "in_scope", "value": "managed_departments"}]))
            elif doctype != "Finance Service Request":
                rows.append(("Department Manager", doctype, permission, [{"field": field, "operator": "in_scope", "value": "department_staff"}]))
    return rows


def apply_default_scopes() -> int:
    from sqlalchemy import and_, insert, select
    from velora import db
    from velora.db.system import row_policy as t
    added = 0
    with db.transaction() as c:
        for role, doctype, permission, conditions in default_policies():
            if c.execute(select(t.c.role).where(and_(t.c.role == role, t.c.doctype == doctype, t.c.permission == permission))).first(): continue
            c.execute(insert(t).values(role=role, doctype=doctype, permission=permission, conditions=conditions, is_active=True, updated_by="system")); added += 1
    return added
