"""Controlled, auditable bulk assignment of a leave policy to eligible employees."""
from datetime import date, datetime, timezone
import json
from velora import Document, get_doc, get_list, new_doc, throw
from velora_erp.finance.doctype._utils import db_update
from velora.permissions import get_session


def _date(value):
    if not value:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _rows(value):
    return list(value or [])


def _value(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _normal(value):
    return str(value if value is not None else "").strip().casefold()


def _matches(rule, context):
    field = _value(rule, "field_name")
    operator = _value(rule, "operator", "Equals")
    expected = _value(rule, "value", "")
    if field == "Employee Category":
        category = _normal(_value(rule, "category_name"))
        values = [_normal(x.get("category_value")) for x in context.get("categories", [])
                  if _normal(x.get("category_name")) == category]
        actual = ";".join(values)
        expected = _value(rule, "category_value") or expected
    else:
        actual = context.get({
            "Employee Type": "employee_type", "Department": "department",
            "Designation": "designation", "Employee Grade": "grade",
            "Branch": "branch", "Business Unit": "default_business_unit",
            "Gender": "gender", "Job Grade": "job_grade",
            "Job Band": "job_band", "Work Location": "work_location",
            "Reports To": "reports_to",
        }.get(field, ""), "")
    present = bool(str(actual or "").strip())
    if operator == "Is Set":
        return present
    if operator == "Is Not Set":
        return not present
    actual_values = [_normal(x) for x in str(actual or "").split(";") if str(x).strip()]
    expected_values = [_normal(x) for x in str(expected or "").split(";") if str(x).strip()]
    if operator == "Equals":
        return _normal(expected) in actual_values
    if operator == "Not Equals":
        return _normal(expected) not in actual_values
    if operator == "In":
        return any(x in expected_values for x in actual_values)
    if operator == "Not In":
        return not any(x in expected_values for x in actual_values)
    return False


def employee_matches_eligibility(context, rules):
    """OR across rule groups; AND across all rules within each group."""
    rules = _rows(rules)
    if not rules:
        return True
    groups = {}
    for rule in rules:
        groups.setdefault(int(_value(rule, "rule_group", 1) or 1), []).append(rule)
    def matches_at_date(rule):
        if "_by_date" not in context:
            return _matches(rule, context)
        selected = _value(rule, "effective_on", "Leave Period Start")
        return _matches(rule, context["_by_date"].get(selected, context))
    return any(all(matches_at_date(rule) for rule in group) for group in groups.values())


def _employee_context(employee, as_of):
    context = {key: getattr(employee, key, None) for key in (
        "employee_type", "department", "designation", "grade", "branch",
        "default_business_unit", "employee_code", "date_of_joining"
    )}
    context["categories"] = []
    for row in _rows(getattr(employee, "categories", None)):
        start, end = _date(_value(row, "effective_from")), _date(_value(row, "effective_to"))
        if start and start > as_of:
            continue
        if end and end < as_of:
            continue
        context["categories"].append({
            "category_name": _value(row, "category_name"),
            "category_value": _value(row, "category_value"),
        })
    try:
        profile = get_doc("Employee HR Profile", employee.name, ignore_permissions=True)
        context["gender"] = getattr(profile, "gender", None)
    except Exception:
        context["gender"] = None
    assignments = get_list("Reporting Assignment", filters={
        "employee": employee.name, "assignment_status": "Approved", "is_primary": 1
    }, fields=["department", "designation", "job_grade", "job_band", "work_location", "reports_to", "effective_from", "effective_to"], limit=100, ignore_permissions=True)
    applicable = []
    for row in assignments:
        start, end = _date(row.get("effective_from")), _date(row.get("effective_to"))
        if start and start <= as_of and (not end or end >= as_of):
            applicable.append(row)
    if applicable:
        assignment = sorted(applicable, key=lambda x: str(x.get("effective_from") or ""), reverse=True)[0]
        for key in ("department", "designation", "job_grade", "job_band", "work_location", "reports_to"):
            if assignment.get(key):
                context[key] = assignment[key]
    return context


def _eligible_employees(policy, selection_mode, selected_rows, as_of, override=False, assignment_date=None, period_end=None):
    if selection_mode == "Selected Employees":
        names = list(dict.fromkeys(_value(row, "employee") for row in _rows(selected_rows) if _value(row, "employee")))
        employees = [get_doc("Employee", name, ignore_permissions=True) for name in names]
    else:
        rows = get_list("Employee", filters={"disabled": 0}, fields=["name"], limit=5000, ignore_permissions=True)
        employees = [get_doc("Employee", row["name"], ignore_permissions=True) for row in rows]
    eligible = []
    for employee in employees:
        if getattr(employee, "disabled", 0):
            continue
        joined = _date(getattr(employee, "date_of_joining", None))
        if joined and period_end and joined > period_end:
            continue
        assignment_as_of = assignment_date or as_of
        context = {"_by_date": {
            "Assignment Date": _employee_context(employee, assignment_as_of),
            "Leave Period Start": _employee_context(employee, as_of),
        }}
        if override or employee_matches_eligibility(context, policy.eligibility_rules):
            eligible.append(employee)
    return eligible


def _prorated_days(entitlement, method, employee, period_start, period_end):
    amount = float(entitlement or 0)
    joined = _date(getattr(employee, "date_of_joining", None))
    if not joined or joined <= period_start or method == "Full Entitlement":
        return round(amount, 2)
    if joined > period_end:
        return 0.0
    if method == "Calendar Days":
        total = (period_end - period_start).days + 1
        eligible = (period_end - max(joined, period_start)).days + 1
        return round(amount * eligible / total, 2)
    # Completed calendar months only: a partial joining month is not counted.
    cursor_year, cursor_month = joined.year, joined.month
    if joined.day != 1:
        cursor_month += 1
        if cursor_month == 13:
            cursor_year += 1; cursor_month = 1
    months = 0
    while (cursor_year, cursor_month) <= (period_end.year, period_end.month):
        months += 1
        cursor_month += 1
        if cursor_month == 13:
            cursor_year += 1; cursor_month = 1
    period_months = (period_end.year - period_start.year) * 12 + period_end.month - period_start.month + 1
    return round(amount * min(months, period_months) / 12, 2)


def _carry_forward_balance(employee, leave_type, period_start, entitlement, existing_allocations=None):
    if not _value(entitlement, "allow_carry_forward", 0):
        return 0.0
    rows = existing_allocations
    if rows is None:
        rows = get_list("Leave Allocation", filters={"employee": employee.name, "leave_type": leave_type, "allocation_status": "Approved"},
            fields=["name", "employee", "leave_type", "period_end", "available_days"], limit=1000, ignore_permissions=True)
    prior = [row for row in rows if row.get("employee") == employee.name and row.get("leave_type") == leave_type
             and _date(row.get("period_end")) and _date(row.get("period_end")) < period_start]
    if not prior:
        return 0.0
    latest = sorted(prior, key=lambda row: str(row.get("period_end") or ""), reverse=True)[0]
    available = max(0.0, float(latest.get("available_days") or 0))
    cap = float(_value(entitlement, "maximum_carry_forward_days", 0) or 0)
    if not cap:
        leave_doc = get_doc("Leave Type", leave_type, ignore_permissions=True)
        cap = float(getattr(leave_doc, "maximum_carry_forward_days", 0) or 0)
    return round(min(available, cap), 2) if cap > 0 else round(available, 2)


class LeavePolicyAssignment(Document):
    def validate(self):
        as_of = _date(self.assignment_date)
        if not self.policy or not as_of or not self.leave_period:
            throw("Policy, Assignment Date and Leave Period are required.")
        leave_period = get_doc("Leave Period", self.leave_period, ignore_permissions=True)
        if leave_period.period_status != "Open":
            throw("Only an Open Leave Period can receive policy allocations.")
        start, end = _date(leave_period.from_date), _date(leave_period.to_date)
        self.period_start, self.period_end = start, end
        policy = get_doc("Leave Policy", self.policy, ignore_permissions=True)
        if policy.status != "Active":
            throw("Only an Active Leave Policy can be assigned.")
        pstart, pend = _date(policy.effective_from), _date(policy.effective_to)
        if as_of < pstart or (pend and as_of > pend):
            throw("Assignment Date falls outside the Leave Policy effective period.")
        if start < pstart or (pend and end > pend):
            throw("Leave Period must fall within the Leave Policy effective period.")
        if self.selection_mode == "Selected Employees" and not self.selected_employees:
            throw("Select at least one employee for a Selected Employees assignment.")
        if self.override_eligibility:
            if not str(self.override_reason or "").strip():
                throw("A reason is required when overriding Leave Policy eligibility.")
        employees = _eligible_employees(policy, self.selection_mode, self.selected_employees, start, bool(self.override_eligibility), as_of, end)
        self.preview_employee_count = len(employees)
        if len(employees) > 1000:
            throw("A single policy assignment is limited to 1,000 employees. Split larger populations into controlled assignments.")
        if not employees:
            throw("No active employees match this Leave Policy and selection.")

    def before_submit(self):
        self.validate()

    def on_submit(self):
        policy = get_doc("Leave Policy", self.policy, ignore_permissions=True)
        as_of, period_start, period_end = _date(self.assignment_date), _date(self.period_start), _date(self.period_end)
        employees = _eligible_employees(policy, self.selection_mode, self.selected_employees, period_start, bool(self.override_eligibility), as_of, period_end)
        generated, skipped, details = 0, 0, []
        employee_names = [employee.name for employee in employees]
        existing_allocations = get_list("Leave Allocation", filters=[["employee", "in", employee_names]],
            fields=["name", "employee", "leave_type", "period_start", "period_end", "available_days", "allocation_status"],
            limit=100000, ignore_permissions=True) if employee_names else []
        for employee in employees:
            for entitlement in _rows(policy.entitlements):
                leave_type = _value(entitlement, "leave_type")
                existing = [row for row in existing_allocations if row.get("employee") == employee.name and row.get("leave_type") == leave_type]
                conflict = False
                for row in existing:
                    a, b = _date(row.get("period_start")), _date(row.get("period_end"))
                    if a and b and period_start <= b and period_end >= a:
                        conflict = True; break
                if conflict:
                    skipped += 1
                    details.append({"employee": employee.name, "leave_type": leave_type, "result": "Skipped - overlapping allocation exists"})
                    continue
                days = _prorated_days(_value(entitlement, "annual_entitlement_days"),
                    _value(entitlement, "proration_method", "Full Entitlement"), employee, period_start, period_end)
                if days <= 0:
                    skipped += 1
                    details.append({"employee": employee.name, "leave_type": leave_type, "result": "Skipped - no entitlement after proration"})
                    continue
                prior_rows = [row for row in existing if row.get("allocation_status") == "Approved"]
                carry_forward = _carry_forward_balance(employee, leave_type, period_start, entitlement, prior_rows)
                allocation = new_doc("Leave Allocation", employee=employee.name, leave_type=leave_type,
                    period_start=period_start, period_end=period_end, allocated_days=days,
                    carry_forward_days=carry_forward, adjustment_days=0, allocation_status="Approved",
                    leave_policy=self.policy, leave_policy_assignment=self.name,
                    policy_version=policy.policy_version, allocation_source="Leave Policy Assignment",
                    approval_notes=f"Generated from Leave Policy {policy.policy_code} v{policy.policy_version} via {self.name}")
                allocation.insert(ignore_permissions=True)
                generated += 1
                details.append({"employee": employee.name, "leave_type": leave_type, "allocation": allocation.name, "days": days, "carry_forward_days": carry_forward, "result": "Created"})
        status = "Completed with Exceptions" if skipped else "Completed"
        session = get_session()
        db_update(self, generated_allocation_count=generated, skipped_allocation_count=skipped,
                  result_details=json.dumps(details, default=str), assignment_status=status,
                  submitted_by=session.user, submitted_on=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"))
