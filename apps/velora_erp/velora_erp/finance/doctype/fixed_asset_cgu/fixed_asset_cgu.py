from decimal import Decimal
from velora import Document, throw, get_list

D=lambda v: Decimal(str(v if v not in (None, "") else 0))

class FixedAssetCGU(Document):
    def validate(self):
        if not self.cgu_name:
            throw("CGU Name are required.")
        seen=set()
        for i,item in enumerate(self.other_assets or [],1):
            ref=(item.reference_code or "").strip()
            if not ref or ref in seen:
                throw(f"Other CGU asset row {i}: Asset Reference must be populated and unique.")
            seen.add(ref)
            if D(item.opening_carrying_amount)<0 or D(item.opening_revaluation_surplus)<0:
                throw(f"Other CGU asset {ref}: opening balances cannot be negative.")
            if D(item.opening_revaluation_surplus)>D(item.opening_carrying_amount):
                throw(f"Other CGU asset {ref}: opening revaluation surplus cannot exceed opening carrying amount.")
            if D(item.individual_recoverable_floor)<0 or D(item.individual_recoverable_floor)>D(item.opening_carrying_amount):
                throw(f"Other CGU asset {ref}: individual recoverable amount floor must be between zero and opening carrying amount.")
            if not getattr(self, "_old", None) or not item.name:
                item.carrying_amount=D(item.opening_carrying_amount)
                item.revaluation_surplus=D(item.opening_revaluation_surplus)
                item.impairment_ceiling_carrying_amount=D(item.opening_carrying_amount)
            elif item.name:
                stored=get_list("Fixed Asset CGU Other Asset",filters={"name":item.name,"parent":self.name,"parenttype":"Fixed Asset CGU","parentfield":"other_assets"},fields=["reference_code","asset_type","opening_carrying_amount","opening_revaluation_surplus","carrying_amount","accumulated_impairment","revaluation_surplus","impairment_ceiling_carrying_amount","impairment_against_revaluation_surplus","impairment_charged_to_expense","impairment_account","impairment_expense_account","impairment_reversal_account","revaluation_surplus_account","individual_recoverable_floor"],limit=1,ignore_permissions=True)
                if not stored:
                    item.carrying_amount=D(item.opening_carrying_amount)
                    item.revaluation_surplus=D(item.opening_revaluation_surplus)
                    item.impairment_ceiling_carrying_amount=D(item.opening_carrying_amount)
                else:
                    old=stored[0]
                    protected=("reference_code","asset_type","opening_carrying_amount","opening_revaluation_surplus","carrying_amount","accumulated_impairment","revaluation_surplus","impairment_ceiling_carrying_amount","impairment_against_revaluation_surplus","impairment_charged_to_expense","impairment_account","impairment_expense_account","impairment_reversal_account","revaluation_surplus_account","individual_recoverable_floor")
                    monetary={"opening_carrying_amount","opening_revaluation_surplus","carrying_amount","accumulated_impairment","revaluation_surplus","impairment_ceiling_carrying_amount","impairment_against_revaluation_surplus","impairment_charged_to_expense","individual_recoverable_floor"}
                    incoming={k:getattr(item,k,None) for k in protected}
                    changed=False
                    for key in protected:
                        if key in monetary:
                            changed = changed or D(incoming[key]) != D(old.get(key))
                        else:
                            changed = changed or str(incoming[key] or "") != str(old.get(key) or "")
                    if changed:
                        throw(f"CGU other asset {ref} has financial balances or account mappings protected after creation. Use a controlled impairment or revaluation transaction.")
