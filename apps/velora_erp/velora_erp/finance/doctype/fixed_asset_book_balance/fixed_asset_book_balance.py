from decimal import Decimal, ROUND_HALF_UP
from velora import Document, throw, get_doc, get_list
D=lambda x: Decimal(str(x or 0))
M=lambda x: D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
class FixedAssetBookBalance(Document):
    def validate(self):
        asset=get_doc("Fixed Asset",self.asset,ignore_permissions=True)
        book=get_doc("Fixed Asset Depreciation Book",self.depreciation_book,ignore_permissions=True)
        if book.disabled: throw("The selected depreciation book is disabled.")
        if book.book_type == "Financial": throw("The Financial book is maintained by the Fixed Asset register. Use the asset's main financial balances instead.")
        duplicates=get_list("Fixed Asset Book Balance",filters={"asset":self.asset,"depreciation_book":self.depreciation_book},fields=["name"],limit=10,ignore_permissions=True)
        if any(r["name"] != self.name for r in duplicates): throw("An asset can have only one balance record per depreciation book.")
        if D(self.acquisition_cost)<0 or D(self.residual_value)<0 or D(self.accumulated_depreciation)<0 or D(self.accumulated_impairment)<0:
            throw("Book cost, residual value, accumulated depreciation and impairment cannot be negative.")
        if D(self.residual_value)>D(self.acquisition_cost): throw("Book residual value cannot exceed book acquisition cost.")
        if int(self.useful_life_months or 0)<=0: throw("Book useful life must be greater than zero.")
        if self.depreciation_method == "Reducing Balance" and not (0 < float(self.depreciation_rate or 0) <= 100): throw("Reducing Balance Rate must be greater than zero and not exceed 100%.")
        if self.depreciation_method == "Units of Production" and D(self.total_units_of_production)<=0: throw("Estimated total production units must be greater than zero.")
        expected=M(D(self.acquisition_cost)-D(self.accumulated_depreciation)-D(self.accumulated_impairment))
        if expected < D(self.residual_value): throw("Book carrying amount cannot be below residual value.")
        self.carrying_amount=expected
