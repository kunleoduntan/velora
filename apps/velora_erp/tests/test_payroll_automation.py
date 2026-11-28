"""Payroll sets itself up: rent relief from a verified declaration, profiles and assignments created, a draft run built, problems listed."""
from datetime import date
from decimal import Decimal

import velora
from velora import get_doc, get_list, new_doc
from velora.permissions import Session, session_as
from velora_erp.setup import after_install

ADMIN = Session(user="Administrator", roles=frozenset({"System Manager"}))


def _setup(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'pa.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    year = date.today().year
    new_doc("Financial Year", year_name=f"FY-{year}", start_date=date(year, 1, 1), end_date=date(year, 12, 31), status="Open", is_current=1).insert(ignore_permissions=True)
    new_doc("Financial Period", period_name=f"FY-{year}-OPEN", financial_year=f"FY-{year}", period_number=1, start_date=date(year, 1, 1), end_date=date(year, 12, 31), status="Open").insert(ignore_permissions=True)
    for code, label, root in [("LIA", "Liabilities", "Liability"), ("EXP", "Expenses", "Expense")]:
        new_doc("Account Group", group_code=code, group_name=label, root_type=root, is_group=0).insert(ignore_permissions=True)
    mk = lambda c, n, g, k: new_doc("Account", account_code=c, account_name=n, account_group=g, account_type=k).insert(ignore_permissions=True)  # noqa: E731
    payable, tax_payable, expense = mk("2100", "Salary Payable", "LIA", "PAYROLL_PAYABLE"), mk("2110", "PAYE Payable", "LIA", "TAX_PAYABLE"), mk("5000", "Salary Expense", "EXP", "OPERATING_EXPENSE")
    j = new_doc("Payroll Tax Jurisdiction", jurisdiction_code="NG", jurisdiction_name="Nigeria", country_code="NG", currency="NGN", tax_year_start_month=1, tax_year_start_day=1, enabled=1).insert(ignore_permissions=True)
    rule = new_doc("Payroll Tax Rule", rule_code="NG-PAYE", rule_name="Nigeria PAYE", jurisdiction=j.name, effective_from=date(year, 1, 1), calculation_basis="Annualised Period Income",
                   bands=[{"band_sequence": 1, "lower_limit": 0, "upper_limit": 800000, "rate": 0}, {"band_sequence": 2, "lower_limit": 800000, "upper_limit": 3000000, "rate": 15},
                          {"band_sequence": 3, "lower_limit": 3000000, "rate": 18}], annual_relief=0, rounding_precision=2, approval_status="Pending").insert(ignore_permissions=True)
    rule.submit(ignore_permissions=True)
    basic = new_doc("Salary Component", component_code="BASIC", component_name="Basic", component_type="Earning", calculation_type="Percentage of Base", rate=100, sequence=1, taxable=1, account=expense.name).insert(ignore_permissions=True)
    paye = new_doc("Salary Component", component_code="PAYE", component_name="PAYE", component_type="Deduction", calculation_type="Progressive Tax", tax_rule=rule.name, periods_per_year=12, sequence=2, account=tax_payable.name).insert(ignore_permissions=True)
    structure = new_doc("Salary Structure", structure_name="Monthly Staff", pay_frequency="Monthly", currency="NGN",
                        components=[{"salary_component": basic.name}, {"salary_component": paye.name}], approval_status="Pending").insert(ignore_permissions=True)
    structure.submit(ignore_permissions=True)
    new_doc("Payroll Automation Settings", settings_name="Payroll Automation", default_jurisdiction=j.name, default_tax_rule=rule.name, default_salary_structure=structure.name,
            basic_percent_of_gross=100, payroll_payable_account=payable.name, expect_pension=0, expect_nhf=0, expect_nsitf=0, auto_prepare_on_employee_save=0).insert(ignore_permissions=True)
    return year


def test_rent_relief_is_twenty_percent_capped_and_reaches_the_tax_profile(tmp_path):
    year = _setup(tmp_path)
    try:
        from velora_erp.finance.payroll_automation import rent_relief_amount
        assert rent_relief_amount(1_000_000) == Decimal("200000.00") and rent_relief_amount(5_000_000) == Decimal("500000.00")   # capped
        emp = new_doc("Employee", employee_code="E1", employee_name="Ada Obi", gross_pay=500000, tax_id="TIN1", bank_name="GTB", bank_account_no="0123").insert(ignore_permissions=True)
        rd = new_doc("Employee Rent Declaration", employee=emp.name, tax_year=year, annual_rent=1_200_000).insert(ignore_permissions=True)
        assert Decimal(str(rd.rent_relief)) == Decimal("240000.00")
        from velora_erp.finance.payroll_automation import prepare
        out = prepare(date(year, 11, 1), date(year, 11, 30))
        prof = get_list("Employee Tax Profile", filters=[["employee", "=", emp.name], ["docstatus", "=", 1]], fields=["annual_relief"], ignore_permissions=True)
        assert prof and Decimal(str(prof[0]["annual_relief"])) == 0                       # draft declaration gives no relief
        rd.status = "Verified"; rd.save(ignore_permissions=True)                          # verifying feeds the profile at once
        prof = get_list("Employee Tax Profile", filters=[["employee", "=", emp.name], ["docstatus", "=", 1]], fields=["annual_relief"], ignore_permissions=True)
        assert len(prof) == 1 and Decimal(str(prof[0]["annual_relief"])) == Decimal("240000.00"), prof
        assert get_doc("Employee Rent Declaration", rd.name, ignore_permissions=True).verified_by
        out = prepare(date(year, 11, 1), date(year, 11, 30))
        run = get_doc("Payroll Run", out["payroll_run"], ignore_permissions=True)
        import json
        lines = run.employees[0].calculation_lines
        lines = json.loads(lines) if isinstance(lines, str) else lines
        paye = next(l for l in lines if l["component_code"] == "PAYE")
        # 500,000 x 12 = 6,000,000 less 240,000 rent relief = 5,760,000: 0% to 800k, 15% to 3m (330,000), 18% above (496,800) = 826,800 a year
        assert Decimal(str(paye["amount"])) == Decimal("68900.00"), paye
    finally:
        velora.shutdown()


def test_preparation_builds_the_run_and_lists_who_needs_attention(tmp_path):
    year = _setup(tmp_path)
    try:
        ok = new_doc("Employee", employee_code="E1", employee_name="Ada Obi", gross_pay=500000, tax_id="TIN1", bank_name="GTB", bank_account_no="0123").insert(ignore_permissions=True)
        nopay = new_doc("Employee", employee_code="E2", employee_name="Bola Eze").insert(ignore_permissions=True)
        prep = new_doc("Payroll Preparation", period_start=date(year, 11, 1), period_end=date(year, 11, 30), pay_frequency="Monthly").insert(ignore_permissions=True)
        assert prep.status == "Prepared" and prep.payroll_run and prep.employees_included == 1
        run = get_doc("Payroll Run", prep.payroll_run, ignore_permissions=True)
        assert [r.employee for r in run.employees] == [ok.name] and run.docstatus == 0
        assert Decimal(str(run.total_gross)) == Decimal("500000.00")
        flagged = {(i.employee, i.area) for i in prep.issues}
        assert (nopay.name, "Salary") in flagged
        assert (ok.name, "Bank") not in flagged
        again = get_doc("Payroll Preparation", prep.name, ignore_permissions=True); again.save(ignore_permissions=True)   # safe to repeat: same run, no duplicates
        assert again.payroll_run == prep.payroll_run
        assert len(get_list("Payroll Run", fields=["name"], ignore_permissions=True)) == 1
        assert len(get_list("Employee Tax Profile", fields=["name"], ignore_permissions=True)) == 1
    finally:
        velora.shutdown()


def _attendance_setup(tmp_path):
    year = _setup(tmp_path)
    basic = get_list("Salary Component", filters=[["component_code", "=", "BASIC"]], fields=["name"], ignore_permissions=True)[0]["name"]
    paye = get_list("Salary Component", filters=[["component_code", "=", "PAYE"]], fields=["name"], ignore_permissions=True)[0]["name"]
    pb = new_doc("Salary Component", component_code="BASICP", component_name="Basic (attendance)", component_type="Earning", calculation_type="Percentage of Base", rate=100,
                 sequence=1, taxable=1, prorate_by_attendance=1, account=get_doc("Salary Component", basic, ignore_permissions=True).account).insert(ignore_permissions=True)
    st = new_doc("Salary Structure", structure_name="Factory Staff", pay_frequency="Monthly", currency="NGN",
                 components=[{"salary_component": pb.name}, {"salary_component": paye}], approval_status="Pending").insert(ignore_permissions=True)
    st.submit(ignore_permissions=True)
    cfg = get_doc("Payroll Automation Settings", get_list("Payroll Automation Settings", fields=["name"], ignore_permissions=True)[0]["name"], ignore_permissions=True)
    cfg.default_salary_structure = st.name
    cfg.save(ignore_permissions=True)
    return year, cfg


def _days(emp, year, month, spec):
    for day, status in spec.items():
        new_doc("Attendance", employee=emp, attendance_date=date(year, month, day), status=status, approval_status="Approved").insert(ignore_permissions=True)


def test_pay_basis_follows_employee_then_category_then_default(tmp_path):
    year, cfg = _attendance_setup(tmp_path)
    try:
        from velora_erp.finance.payroll_automation import ATTENDANCE, FIXED, pay_basis_for, settings
        cat = new_doc("Employee Classification Category", category_code="STAFF", category_name="Staff Type").insert(ignore_permissions=True)
        fw = new_doc("Employee Classification Value", value_code="FACTORY", value_name="Factory Workers", category=cat.name).insert(ignore_permissions=True)
        cfg.append("pay_basis_rules", {"classification_value": fw.name, "pay_basis": ATTENDANCE})
        cfg.save(ignore_permissions=True)
        s = settings()
        assert s["default_pay_basis"] == FIXED
        mk = lambda code, **kw: new_doc("Employee", employee_code=code, employee_name=code, gross_pay=300000, tax_id="T", bank_name="B", bank_account_no="1", **kw).insert(ignore_permissions=True)  # noqa: E731
        office = mk("OFF")
        worker = mk("FAC", categories=[{"category_name": cat.name, "category_value": fw.name}])
        opted_out = mk("FAC2", pay_basis="Fixed Monthly", categories=[{"category_name": cat.name, "category_value": fw.name}])
        d = lambda e: get_doc("Employee", e.name, ignore_permissions=True).as_dict() | {"name": e.name}  # noqa: E731
        assert pay_basis_for(d(office), s) == FIXED
        assert pay_basis_for(d(worker), s) == ATTENDANCE
        assert pay_basis_for(d(opted_out), s) == FIXED                      # the employee's own choice wins
        cfg.default_pay_basis = ATTENDANCE; cfg.save(ignore_permissions=True)
        assert pay_basis_for(d(office), settings()) == ATTENDANCE            # company default applies to everyone without a rule
    finally:
        velora.shutdown()


def test_attendance_based_pay_is_prorated_and_fixed_pay_is_not(tmp_path):
    year, cfg = _attendance_setup(tmp_path)
    try:
        from velora_erp.finance.payroll_automation import prepare
        mk = lambda code, **kw: new_doc("Employee", employee_code=code, employee_name=code, gross_pay=300000, tax_id="T", bank_name="B", bank_account_no="1", **kw).insert(ignore_permissions=True)  # noqa: E731
        fixed, att, none = mk("FIX"), mk("ATT", pay_basis="Attendance Based"), mk("NOREC", pay_basis="Attendance Based")
        # October has 31 days: 20 present, 2 half days (1 day), 4 weekly off/holiday, 2 absent, 3 unrecorded -> 25 credited
        spec = {d: "Present" for d in range(1, 21)}
        spec.update({21: "Half Day", 22: "Half Day", 23: "Weekly Off", 24: "Weekly Off", 25: "Holiday", 26: "Holiday", 27: "Absent", 28: "Absent"})
        _days(att.name, year, 10, spec)
        out = prepare(date(year, 10, 1), date(year, 10, 31))
        run = get_doc("Payroll Run", out["payroll_run"], ignore_permissions=True)
        by = {r.employee: r for r in run.employees}
        assert float(by[fixed.name].days_worked) == 31.0 and int(by[fixed.name].days_in_period) == 31      # fixed pay: the whole period
        assert float(by[att.name].days_worked) == 25.0 and int(by[att.name].days_in_period) == 31
        assert none.name not in by                                                         # no attendance: left out and listed, never paid zero silently
        assert any(i["employee"] == none.name and i["blocking"] for i in out["issues"])
        assert any(i["employee"] == att.name and "3 day(s)" in i["problem"] for i in out["issues"])
        import json
        def basic(r):
            ls = json.loads(r.calculation_lines) if isinstance(r.calculation_lines, str) else r.calculation_lines
            return Decimal(str(next(l for l in ls if l["component_code"] == "BASICP")["amount"]))
        assert basic(by[att.name]) == (Decimal("300000") * 25 / 31).quantize(Decimal("0.01"))
        assert basic(by[fixed.name]) == Decimal("300000.00")
    finally:
        velora.shutdown()
