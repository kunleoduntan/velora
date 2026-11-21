from sqlalchemy import select
from velora import Document, throw, db, get_doc
from velora.db.tables import get_table
from velora_erp.finance.validation import row


class Employee(Document):
    def validate(self):
        self.employee_code = (self.employee_code or "").strip().upper()
        self.employee_name = (self.employee_name or "").strip()
        if not self.employee_name:
            self.employee_name = " ".join(str(x).strip() for x in (self.first_name, self.middle_name, self.last_name) if x and str(x).strip())
        self._check_personal_and_employment()
        if not self.employee_code or not self.employee_name:
            throw("Employee Code and Employee Name are required.")
        if self.employee_type not in ("Permanent", "Contract", "Temporary", "Director", "Other"):
            throw("Select a valid Employee Type.")
        category_keys = set()
        for category in (getattr(self, "categories", None) or []):
            category_name = str(getattr(category, "category_name", "") or "").strip()
            category_value = str(getattr(category, "category_value", "") or "").strip()
            if not category_name or not category_value:
                throw("Every Employee Category row requires both Classification Category and Value.")
            value_doc = get_doc("Employee Classification Value", category_value, ignore_permissions=True)
            if value_doc.disabled or value_doc.category != category_name:
                throw("Employee Classification Value must be active and belong to the selected Classification Category.")
            category_doc = get_doc("Employee Classification Category", category_name, ignore_permissions=True)
            if category_doc.disabled:
                throw("Disabled Employee Classification Categories cannot be assigned.")
            key = (category_name.casefold(), category_value.casefold())
            if key in category_keys:
                throw("Duplicate Employee Category and Value combinations are not permitted.")
            category_keys.add(key)
            start = getattr(category, "effective_from", None)
            end = getattr(category, "effective_to", None)
            if start and end and str(end)[:10] < str(start)[:10]:
                throw("Employee Category Effective To cannot precede Effective From.")
        for field, label in (("default_payable_account", "Employee Payable"), ("advance_account", "Employee Advance"), ("loan_account", "Employee Loan")):
            account_name = getattr(self, field, None)
            if not account_name:
                continue
            account = row("Account", account_name, "name", "root_type", "requires_party", "disabled")
            if not account or account["disabled"] or not account["requires_party"] or account["root_type"] not in ("Asset", "Liability"):
                throw(f"{label} Account must be an active party-tracked Asset or Liability account.")

    def _check_personal_and_employment(self):
        from datetime import date
        d = lambda v: str(v)[:10] if v else None
        dob, joined, confirmed, contract_end = d(self.date_of_birth), d(self.date_of_joining), d(self.date_of_confirmation), d(self.contract_end_date)
        resigned, relieved = d(self.resignation_date), d(self.relieving_date)
        if dob and dob > date.today().isoformat():
            throw("Date of Birth cannot be in the future.")
        if dob and joined and joined <= dob:
            throw("Date of Joining must be after the Date of Birth.")
        if joined and confirmed and confirmed < joined:
            throw("Date of Confirmation cannot be before the Date of Joining.")
        if joined and contract_end and contract_end < joined:
            throw("Contract End Date cannot be before the Date of Joining.")
        if joined and relieved and relieved < joined:
            throw("Relieving Date cannot be before the Date of Joining.")
        if resigned and relieved and relieved < resigned:
            throw("Relieving Date cannot be before the resignation letter date.")
        if self.employment_status == "Left" and not relieved:
            throw("Enter the Relieving Date for an employee whose status is Left.")
        if int(self.notice_period_days or 0) < 0:
            throw("Notice Period cannot be negative.")
        if self.reports_to:
            if self.reports_to == self.name or self.reports_to == self.employee_code:
                throw("An employee cannot report to themselves.")
            seen, current = {self.employee_code}, self.reports_to
            for _ in range(25):                      # walk up the chain: a reporting loop would make the hierarchy unusable
                if current in seen:
                    throw("Reports To would create a reporting loop.")
                seen.add(current)
                boss = row("Employee", current, "name", "reports_to")
                if not boss:
                    throw(f"Reports To employee {current} does not exist.")
                current = boss.get("reports_to")
                if not current:
                    break
        if self.photo:
            from velora.files import list_attachments
            files = [f for f in list_attachments("Employee", self.name)] if self.name and not self.is_new() else []
            match = [f for f in files if f.get("id") == self.photo]
            if self.name and not self.is_new() and (not match or not str(match[0].get("content_type") or "").startswith("image/")):
                throw("The photo must be an image attached to this employee.")

    def before_delete(self):
        ledger = get_table("Account Ledger Record")
        with db.transaction() as conn:
            used = conn.execute(select(ledger.c.name).where(ledger.c.party_type == "Employee", ledger.c.party == self.name).limit(1)).first()
        if used:
            throw("This Employee has financial ledger activity and cannot be deleted; disable the record instead.")
