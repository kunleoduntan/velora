"""Payroll that sets itself up. Three small jobs, each safe to repeat:

* rent relief   - from the employee's verified Rent Declaration, min(rate x annual rent, cap)
* setup         - a tax profile and a salary assignment for every employee who lacks one
* preparation   - a draft Payroll Run for the period, with a plain list of anyone who needs attention and how to fix it

Nothing here skips a control: profiles and assignments still go through their own approval (none when no workflow is set), and a payroll
run still validates every line. An employee whose line cannot be validated is left out of the run and listed, so one problem never blocks the rest.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from velora import get_doc, get_list, new_doc

D = lambda v: Decimal(str(v if v not in (None, "") else 0))  # noqa: E731
TWO = Decimal("0.01")


SETTING_FIELDS = ["name", "default_jurisdiction", "default_tax_rule", "rent_relief_rate", "rent_relief_cap", "default_salary_structure", "basic_percent_of_gross",
                  "payroll_payable_account", "expect_pension", "expect_nhf", "expect_nsitf", "auto_prepare_on_employee_save", "default_pay_basis", "only_approved_attendance"]
EMPLOYEE_FIELDS = ["name", "employee_name", "disabled", "employment_status", "date_of_joining", "gross_pay", "tax_id", "pension_pin", "nhf_number",
                   "salary_mode", "bank_name", "bank_account_no", "pay_basis"]
FIXED, ATTENDANCE = "Fixed Monthly", "Attendance Based"
# What counts as a day paid. Half Day counts half; Absent counts nothing.
CREDIT = {"Present": 1, "Work From Home": 1, "Outdoor Duty": 1, "Holiday": 1, "Weekly Off": 1, "On Leave": 1, "Half Day": 0.5, "Absent": 0}


def settings() -> dict:
    rows = get_list("Payroll Automation Settings", fields=SETTING_FIELDS, limit=1, ignore_permissions=True)
    return rows[0] if rows else {}


def rent_relief_amount(annual_rent, cfg: dict | None = None) -> Decimal:
    cfg = cfg if cfg is not None else settings()
    rate = D(cfg.get("rent_relief_rate") if cfg.get("rent_relief_rate") not in (None, "") else 20)
    cap = D(cfg.get("rent_relief_cap") if cfg.get("rent_relief_cap") not in (None, "") else 500000)
    return min((D(annual_rent) * rate / 100).quantize(TWO), cap)


def _tax_year(jurisdiction: str | None, on: date) -> tuple[int, date]:
    """(tax year, the day it started) for a date, using the jurisdiction's own start month."""
    month, day = 1, 1
    if jurisdiction:
        j = get_doc("Payroll Tax Jurisdiction", jurisdiction, ignore_permissions=True)
        month, day = int(j.tax_year_start_month or 1), int(j.tax_year_start_day or 1)
    try:
        start = date(on.year, month, day)
    except ValueError:
        start = date(on.year, month, 28)
    if on < start:
        try:
            start = date(on.year - 1, month, day)
        except ValueError:
            start = date(on.year - 1, month, 28)
    return start.year, start


def rent_relief_for(employee: str, tax_year: int, cfg: dict | None = None) -> Decimal:
    rows = get_list("Employee Rent Declaration", filters=[["employee", "=", employee], ["tax_year", "=", tax_year], ["status", "=", "Verified"]],
                    fields=["annual_rent"], limit=50, ignore_permissions=True)
    if not rows:
        return Decimal("0")
    return rent_relief_amount(max(D(r["annual_rent"]) for r in rows), cfg)


def _issue(issues, employee, area, problem, fix, blocking=False):
    issues.append({"employee": employee, "area": area, "problem": problem, "how_to_fix": fix, "blocking": 1 if blocking else 0})


def ensure_tax_profile(employee, period_start: date, period_end: date, cfg: dict, issues: list) -> dict | None:
    """Make sure a submitted Employee Tax Profile covers the period with the right relief. Returns it, or None (and an issue says why)."""
    name = employee["name"]
    if not cfg.get("default_jurisdiction") or not cfg.get("default_tax_rule"):
        _issue(issues, name, "PAYE", "No default Tax Jurisdiction / Tax Rule in Payroll Automation Settings.", "Open Payroll Automation Settings and choose them.", True)
        return None
    year, year_start = _tax_year(cfg["default_jurisdiction"], period_end)
    relief = rent_relief_for(name, year, cfg)
    profiles = [p for p in get_list("Employee Tax Profile", filters=[["employee", "=", name], ["docstatus", "=", 1]],
                                    fields=["name", "effective_from", "effective_to", "annual_relief", "tax_exempt"], limit=100, ignore_permissions=True)
                if str(p["effective_from"])[:10] <= str(period_end)[:10] and (not p.get("effective_to") or str(p["effective_to"])[:10] >= str(period_start)[:10])]
    if profiles:
        p = profiles[0]
        if p.get("tax_exempt") or D(p.get("annual_relief")) == relief:
            return p
        try:                                                    # the relief changed (a rent declaration was verified or corrected): replace the profile
            get_doc("Employee Tax Profile", p["name"], ignore_permissions=True).cancel(ignore_permissions=True)
        except Exception as exc:  # noqa: BLE001
            _issue(issues, name, "PAYE", f"Rent relief is now {relief:,.2f} but tax profile {p['name']} has {D(p.get('annual_relief')):,.2f} and could not be replaced ({exc}).",
                   f"Cancel Employee Tax Profile {p['name']}; a new one is created on the next preparation.", True)
            return None
    start = min(year_start, period_start)
    try:
        prof = new_doc("Employee Tax Profile", employee=name, jurisdiction=cfg["default_jurisdiction"], tax_rule=cfg["default_tax_rule"],
                       tax_identifier=employee.get("tax_id") or None, effective_from=start, annual_relief=relief, approval_status="Pending")
        prof.insert(ignore_permissions=True)
        prof.submit(ignore_permissions=True)
        return {"name": prof.name, "annual_relief": relief}
    except Exception as exc:  # noqa: BLE001 - waiting for approval, or a setting is wrong: say which
        _issue(issues, name, "PAYE", f"Tax profile could not be completed: {str(exc)[:200]}",
               "If it is waiting for approval, approve it in Employee Tax Profile; otherwise correct the setting named.", True)
        return None


def ensure_assignment(employee, period_start: date, period_end: date, cfg: dict, issues: list) -> dict | None:
    name = employee["name"]
    covering = [a for a in get_list("Salary Structure Assignment", filters=[["employee", "=", name], ["docstatus", "=", 1]],
                                    fields=["name", "base_salary", "effective_from", "effective_to", "salary_structure"], limit=100, ignore_permissions=True)
                if str(a["effective_from"])[:10] <= str(period_end)[:10] and (not a.get("effective_to") or str(a["effective_to"])[:10] >= str(period_start)[:10])]
    gross, pct = D(employee.get("gross_pay")), cfg.get("basic_percent_of_gross")
    if covering:
        a = covering[0]
        if gross > 0 and pct not in (None, "", 0) and D(a["base_salary"]) != (gross * D(pct) / 100).quantize(TWO):
            _issue(issues, name, "Salary", f"Gross Pay on the employee is {gross:,.2f} but the assignment {a['name']} has Base Salary {D(a['base_salary']):,.2f} "
                   f"(expected {(gross * D(pct) / 100).quantize(TWO):,.2f}).", "If this is a pay change, add a new Salary Structure Assignment from the change date.", False)
        return a
    if gross <= 0:
        _issue(issues, name, "Salary", "No Gross Pay on the employee and no salary assignment.", "Enter Gross Pay on the Employee.", True)
        return None
    if not cfg.get("default_salary_structure") or pct in (None, "", 0):
        _issue(issues, name, "Salary", "No salary assignment, and Default Salary Structure / Base Salary % are not set.", "Set them in Payroll Automation Settings, or add the assignment by hand.", True)
        return None
    joined = employee.get("date_of_joining")
    start = max(period_start, date.fromisoformat(str(joined)[:10])) if joined else period_start
    try:
        structure = get_doc("Salary Structure", cfg["default_salary_structure"], ignore_permissions=True)
        a = new_doc("Salary Structure Assignment", employee=name, salary_structure=structure.name, effective_from=start, currency=structure.currency,
                    base_salary=(gross * D(pct) / 100).quantize(TWO), approval_status="Pending")
        a.insert(ignore_permissions=True)
        a.submit(ignore_permissions=True)
        return {"name": a.name, "base_salary": a.base_salary}
    except Exception as exc:  # noqa: BLE001
        _issue(issues, name, "Salary", f"Salary assignment could not be completed: {str(exc)[:200]}",
               "If it is waiting for approval, approve it in Salary Structure Assignment; otherwise correct the setting named.", True)
        return None


def category_rules() -> dict:
    """{classification value: pay basis} from the settings table."""
    doc = get_doc("Payroll Automation Settings", settings().get("name"), ignore_permissions=True) if settings() else None
    return {r.classification_value: r.pay_basis for r in (doc.pay_basis_rules or [])} if doc else {}


def pay_basis_for(employee: dict, cfg: dict, rules: dict | None = None, categories: list | None = None) -> str:
    """Employee's own choice, else the staff-category rule, else the company default (Fixed Monthly when nothing is set)."""
    own = employee.get("pay_basis")
    if own in (FIXED, ATTENDANCE):
        return own
    rules = category_rules() if rules is None else rules
    if rules:
        if categories is None:
            categories = [r["category_value"] for r in get_list("Employee Category Row", filters=[["parent", "=", employee["name"]]], fields=["category_value"], limit=200, ignore_permissions=True)]
        hit = {rules[c] for c in categories if c in rules}
        if len(hit) == 1:
            return hit.pop()
        if ATTENDANCE in hit:       # two categories disagree: the careful reading is to follow attendance
            return ATTENDANCE
    return cfg.get("default_pay_basis") or FIXED


def attendance_days(employee: str, ps: date, pe: date, cfg: dict) -> tuple[Decimal, int, int]:
    """(days credited, days in period, calendar days with no attendance record)."""
    filters = [["employee", "=", employee], ["attendance_date", ">=", ps], ["attendance_date", "<=", pe]]
    if cfg.get("only_approved_attendance", 1):
        filters.append(["approval_status", "=", "Approved"])
    rows = get_list("Attendance", filters=filters, fields=["attendance_date", "status"], limit=1000, ignore_permissions=True)
    per_day: dict = {}
    for r in rows:
        per_day[str(r["attendance_date"])[:10]] = max(per_day.get(str(r["attendance_date"])[:10], 0), CREDIT.get(r["status"], 0))
    total = (pe - ps).days + 1
    return D(sum(per_day.values())), total, total - len(per_day)


def attendance_lines(lines, employees, ps, pe, cfg, issues, structure_prorates: dict):
    """Fill days worked / days in period: attendance-based people get what was recorded; fixed people get the whole period (so a prorating component pays in full)."""
    rules, by_name = category_rules(), {e["name"]: e for e in employees}
    cats: dict = {}
    if rules:
        for r in get_list("Employee Category Row", filters=[["parent", "in", list(by_name)]], fields=["parent", "category_value"], limit=100000, ignore_permissions=True):
            cats.setdefault(r["parent"], []).append(r["category_value"])
    kept = []
    for ln in lines:
        e = by_name[ln["employee"]]
        if pay_basis_for(e, cfg, rules, cats.get(e["name"], [])) != ATTENDANCE:
            kept.append({**ln, "days_worked": (pe - ps).days + 1, "days_in_period": (pe - ps).days + 1})      # fixed pay = the whole period
            continue
        worked, total, missing = attendance_days(e["name"], ps, pe, cfg)
        if not structure_prorates.get(ln["salary_assignment"], True):
            _issue(issues, e["name"], "Pay basis", "Paid on attendance, but no salary component is marked 'Prorate by Attendance', so absence changes nothing.",
                   "Tick 'Prorate by Attendance' on the earning components that should follow attendance (Salary Structure).", False)
        if worked == 0:
            _issue(issues, e["name"], "Attendance", "Paid on attendance but no attendance is recorded" + (" and approved" if cfg.get("only_approved_attendance", 1) else "") + " for this period.",
                   "Record or approve the attendance, or set the employee's Pay Basis to Fixed Monthly.", True)
            continue
        if missing:
            _issue(issues, e["name"], "Attendance", f"{missing} day(s) in the period have no attendance record; they are counted as not worked.",
                   "Record the missing days (Present, Absent, Holiday...) and prepare again.", False)
        kept.append({**ln, "days_worked": float(worked), "days_in_period": total})
    return kept


def employee_checks(employee, structure, cfg, issues):
    name = employee["name"]
    if (employee.get("salary_mode") or "Bank") == "Bank" and not (employee.get("bank_account_no") and employee.get("bank_name")):
        _issue(issues, name, "Bank", "No bank name / account number.", "Fill the Bank section on the Employee.", False)
    if not employee.get("tax_id"):
        _issue(issues, name, "PAYE", "No Tax ID.", "Fill Tax ID on the Employee (Statutory tab).", False)
    if cfg.get("expect_pension") and structure and not employee.get("pension_pin"):
        _issue(issues, name, "Pension", "No pension PIN.", "Fill Pension PIN and Pension Fund Administrator on the Employee.", False)
    if cfg.get("expect_nhf") and structure and not employee.get("nhf_number"):
        _issue(issues, name, "NHF", "No NHF number.", "Fill NHF Number on the Employee, or ignore if the employee is exempt.", False)


def structure_checks(structure_name, cfg, issues):
    """The salary structure must carry the statutory lines. NHF, NSITF and pension are components, so a missing one means a missing deduction."""
    if not structure_name:
        return None
    s = get_doc("Salary Structure", structure_name, ignore_permissions=True)
    text = [" ".join(str(getattr(c, f, "") or "") for f in ("component_code", "component_name", "statutory_scheme")).upper() for c in s.components]
    kinds = [str(getattr(c, "calculation_type", "")) for c in s.components]
    if "Progressive Tax" not in kinds:
        _issue(issues, None, "Structure", f"{s.name} has no Progressive Tax (PAYE) component.", "Add the PAYE component to the Salary Structure.", False)
    for flag, key, label in (("expect_pension", "PENSION", "Pension"), ("expect_nhf", "NHF", "NHF"), ("expect_nsitf", "NSITF", "NSITF")):
        if cfg.get(flag) and not any(key in t for t in text):
            _issue(issues, None, "Structure", f"{s.name} has no {label} component, so {label} is not being deducted/contributed.",
                   f"Add a {label} Salary Component to the structure (or untick it in Payroll Automation Settings).", False)
    return s


def set_up_employee(employee_name: str, on: date | None = None) -> list:
    """Create what is missing for one employee (used when an Employee is saved). Returns the issues, never raises."""
    cfg, issues = settings(), []
    if not cfg:
        return issues
    on = on or date.today()
    emp = get_doc("Employee", employee_name, ignore_permissions=True).as_dict()
    emp["name"] = employee_name
    start = date(on.year, on.month, 1)
    end = (date(on.year + (on.month == 12), on.month % 12 + 1, 1) - timedelta(days=1))
    ensure_tax_profile(emp, start, end, cfg, issues)
    ensure_assignment(emp, start, end, cfg, issues)
    return issues


def employee_saved(doc, method=None):
    """Employee on_update hook: set up quietly. A problem never blocks saving the employee; it shows up in the next Payroll Preparation."""
    try:
        cfg = settings()
        if cfg.get("auto_prepare_on_employee_save") and not doc.disabled and doc.employment_status in ("Active", "Probation", "On Leave", "Notice Period"):
            set_up_employee(doc.name)
    except Exception:  # noqa: BLE001
        pass


ACTIVE = ("Active", "Probation", "On Leave", "Notice Period")


def prepare(period_start, period_end, pay_frequency="Monthly", posting_date=None, existing_run: str | None = None) -> dict:
    """Set everyone up, build the draft Payroll Run, and list what needs attention."""
    from velora.exceptions import ValidationError
    ps, pe = date.fromisoformat(str(period_start)[:10]), date.fromisoformat(str(period_end)[:10])
    cfg, issues = settings(), []
    if not cfg:
        raise ValidationError("Open Payroll Automation Settings and save it once before preparing payroll.")
    if ps > pe:
        raise ValidationError("Period Start cannot be after Period End.")
    employees = get_list("Employee", filters=[["disabled", "=", 0]], fields=EMPLOYEE_FIELDS, limit=100000, ignore_permissions=True)
    employees = [e for e in employees if e.get("employment_status") in ACTIVE and (not e.get("date_of_joining") or str(e["date_of_joining"])[:10] <= str(pe))]
    structure = structure_checks(cfg.get("default_salary_structure"), cfg, issues)
    lines, flagged = [], set()
    for e in employees:
        before = len(issues)
        employee_checks(e, structure, cfg, issues)
        assignment = ensure_assignment(e, ps, pe, cfg, issues)
        profile = ensure_tax_profile(e, ps, pe, cfg, issues) if assignment else None      # no tax profile for someone who cannot be paid yet
        if profile and assignment:
            lines.append({"employee": e["name"], "salary_assignment": assignment["name"]})
        if len(issues) > before:
            flagged.add(e["name"])
    if lines:
        prorates = {}
        for sa in {ln["salary_assignment"] for ln in lines}:
            st = get_doc("Salary Structure", get_doc("Salary Structure Assignment", sa, ignore_permissions=True).salary_structure, ignore_permissions=True)
            prorates[sa] = any(c.prorate_by_attendance for c in st.components)
        lines = attendance_lines(lines, employees, ps, pe, cfg, issues, prorates)
    run_name, built = None, 0
    if not cfg.get("payroll_payable_account"):
        _issue(issues, None, "Payroll Run", "No Payroll Payable Account in Payroll Automation Settings.", "Choose it in Payroll Automation Settings.", True)
    elif lines:
        run_name, built, lines = _build_run(lines, ps, pe, pay_frequency, posting_date, cfg, issues, existing_run, structure)
    elif not employees:
        _issue(issues, None, "Payroll Run", "There are no active employees for this period.", "Check the Employee list.", True)
    left_out = {i["employee"] for i in issues if i["blocking"] and i["employee"]}
    return {"payroll_run": run_name, "employees_included": built, "employees_flagged": len(flagged | left_out), "issues": issues,
            "summary": f"{built} of {len(employees)} active employees are in the run" + (f"; {len(issues)} item(s) need attention." if issues else "; nothing needs attention.")}


def _build_run(lines, ps, pe, freq, posting_date, cfg, issues, existing_run, structure):
    from velora.exceptions import ValidationError
    currency = structure.currency if structure else get_doc("Salary Structure", get_doc("Salary Structure Assignment", lines[0]["salary_assignment"], ignore_permissions=True).salary_structure, ignore_permissions=True).currency
    lines = list(lines)
    title = f"Payroll {ps:%d/%m/%Y} to {pe:%d/%m/%Y}"
    for _ in range(len(lines) + 1):
        if not lines:
            return None, 0, []
        try:
            if existing_run:
                run = get_doc("Payroll Run", existing_run, ignore_permissions=True)
                if run.docstatus != 0:
                    _issue(issues, None, "Payroll Run", f"{existing_run} is already submitted.", "Open a new Payroll Preparation for another period.", True)
                    return existing_run, len(run.employees or []), lines
                run.employees = []
                for ln in lines:
                    run.append("employees", dict(ln))
                run.save(ignore_permissions=True)
            else:
                run = new_doc("Payroll Run", run_title=title, pay_frequency=freq, period_start=ps, period_end=pe, posting_date=posting_date or pe, currency=currency,
                              payroll_payable_account=cfg["payroll_payable_account"], employees=[dict(ln) for ln in lines], approval_status="Pending")
                run.insert(ignore_permissions=True)
            return run.name, len(lines), lines
        except ValidationError as exc:
            m = re.search(r"Payroll line (\d+)", str(exc))
            if not m or not (1 <= int(m.group(1)) <= len(lines)):
                _issue(issues, None, "Payroll Run", str(exc)[:300], "Correct the setting named, then save the preparation again.", True)
                return None, 0, []
            bad = lines.pop(int(m.group(1)) - 1)
            _issue(issues, bad["employee"], "Payroll Run", str(exc)[:300], "Correct what is named, then save the preparation again.", True)
    return None, 0, []
