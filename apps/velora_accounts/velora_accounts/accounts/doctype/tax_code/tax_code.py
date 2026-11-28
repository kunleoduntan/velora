from velora import Document, throw

from .... import common as c


class TaxCode(Document):
    def validate(self):
        if self.rate is None or not 0 <= self.rate <= 100:
            throw("Rate must be between 0 and 100")
        info = c.accounts_info([self.account]).get(self.account)
        c.check_postable(info, self.account, "Tax account")
        if info["account_type"] != "Tax":
            throw(f"{self.account} is not a Tax account")
