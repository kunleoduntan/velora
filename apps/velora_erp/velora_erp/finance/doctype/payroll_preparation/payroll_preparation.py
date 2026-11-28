from velora import Document, throw


class PayrollPreparation(Document):
    def validate(self):
        from velora_erp.finance.payroll_automation import prepare
        if str(self.period_start)[:10] > str(self.period_end)[:10]:
            throw("Period Start cannot be after Period End.")
        out = prepare(self.period_start, self.period_end, self.pay_frequency or "Monthly", self.posting_date, existing_run=self.payroll_run or None)
        self.payroll_run = out["payroll_run"]
        self.employees_included = out["employees_included"]
        self.employees_flagged = out["employees_flagged"]
        self.summary = out["summary"]
        self.issues = []
        for i in out["issues"]:
            self.append("issues", i)
        for row in self.issues:
            row._prepare()
        self._link_children()                    # rows added here need their names and parent link
        self.status = "Prepared" if out["payroll_run"] else "Draft"
