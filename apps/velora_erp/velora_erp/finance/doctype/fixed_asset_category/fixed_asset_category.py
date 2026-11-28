from velora import Document, throw
from velora_erp.finance.validation import row
class FixedAssetCategory(Document):
    def validate(self):
        if not self.category_name: throw("Category Name is required.")
        for a in (self.asset_account,self.accumulated_depreciation_account):
            r=row("Account",a,"name","disabled","root_type")
            if not r or r["disabled"] or r["root_type"]!="Asset": throw(f"Select an active Asset account: {a}.")
        if self.depreciation_expense_account:
            r=row("Account",self.depreciation_expense_account,"name","disabled","root_type")
            if not r or r["disabled"] or r["root_type"]!="Expense": throw("Depreciation Expense Account must be an active Expense account.")
        if int(self.default_useful_life_months or 0)<=0: throw("Default Useful Life must be greater than zero.")
        if not self.default_depreciation_method: self.default_depreciation_method = "Straight Line"
        if self.default_depreciation_method == "Reducing Balance" and not (0 < float(self.default_reducing_balance_rate or 0) <= 100): throw("Default Reducing Balance Rate must be greater than 0 and not exceed 100%.")
        for account, root in ((self.impairment_account, "Asset"), (self.impairment_expense_account, "Expense"), (self.impairment_reversal_account, "Income"), (self.revaluation_surplus_account, "Equity")):
            if account:
                r=row("Account",account,"name","disabled","root_type")
                if not r or r["disabled"] or r["root_type"] != root: throw(f"Impairment account {account} must be an active {root} account.")
