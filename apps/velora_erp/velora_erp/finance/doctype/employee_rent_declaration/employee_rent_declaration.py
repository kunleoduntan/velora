from velora import Document, get_list, throw
from velora.permissions import get_session


class EmployeeRentDeclaration(Document):
    def validate(self):
        from velora_erp.finance.payroll_automation import rent_relief_amount
        if float(self.annual_rent or 0) <= 0:
            throw("Annual Rent must be more than zero.")
        if not 2000 <= int(self.tax_year or 0) <= 2100:
            throw("Enter the tax year as four digits, e.g. 2026.")
        dup = get_list("Employee Rent Declaration", filters=[["employee", "=", self.employee], ["tax_year", "=", self.tax_year]], fields=["name"], limit=5, ignore_permissions=True)
        if any(d["name"] != self.name for d in dup):
            throw(f"{self.employee} already has a Rent Declaration for {self.tax_year}. Open that one instead.")
        self.rent_relief = rent_relief_amount(self.annual_rent)
        if self.status == "Verified":
            old = getattr(self, "_old", None) or {}
            if old.get("status") != "Verified" or old.get("annual_rent") != self.annual_rent:
                self.verified_by = get_session().user
        else:
            self.verified_by = None

    def on_update(self):
        if self.status == "Verified":                    # the relief reaches PAYE straight away
            from velora_erp.finance.payroll_automation import set_up_employee
            from datetime import date
            try:
                set_up_employee(self.employee, date(int(self.tax_year), 12, 1) if date.today().year != int(self.tax_year) else date.today())
            except Exception:  # noqa: BLE001
                pass
