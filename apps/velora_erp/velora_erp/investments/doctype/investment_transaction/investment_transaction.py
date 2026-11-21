from velora import Document, get_doc, throw

from velora_erp.finance.source_documents import ensure_approved, validate_approval_transition
from velora_erp.investments import posting
from velora_erp.investments.settings import get_settings


class InvestmentTransaction(Document):
    def validate(self):
        inv = get_doc("Investment", self.investment, ignore_permissions=True)
        self.investment_name, self.currency, self.exchange_rate = inv.investment_name, inv.currency, inv.exchange_rate
        if self.transaction_type not in posting.NO_APPROVAL:
            validate_approval_transition(self)
        if int(self.docstatus or 0) == 0:
            posting.plan(inv, self)                            # fills the defaults and shows the effect; nothing is posted yet

    def before_submit(self):
        if self.transaction_type not in posting.NO_APPROVAL:
            ensure_approved(self, required=True)

    def on_submit(self):
        posting.post_transaction(self)

    def before_cancel(self):
        from velora import get_list
        later = [t["name"] for t in get_list("Investment Transaction", filters={"investment": self.investment, "docstatus": 1}, fields=["name", "transaction_date", "creation"], limit=100000, ignore_permissions=True)
                 if (str(t["transaction_date"]), str(t["creation"])) > (str(self.transaction_date), str(self.creation)) and t["name"] != self.name]
        if later:
            throw(f"Cancel the later transactions first ({', '.join(later[:3])}).")

    def on_cancel(self):
        posting.recompute(self.investment)             # the position is rebuilt from what is still posted

    def before_delete(self):
        if int(self.docstatus or 0) == 1:
            throw("A submitted investment transaction cannot be deleted.")
