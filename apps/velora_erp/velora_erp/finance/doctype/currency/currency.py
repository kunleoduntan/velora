from velora import Document, throw


class Currency(Document):
    def validate(self):
        self.currency_code = (self.currency_code or "").strip().upper()
        if len(self.currency_code) != 3 or not self.currency_code.isalpha():
            throw("Currency code must be three letters, such as USD or EUR.")
        if self.decimal_places is None or int(self.decimal_places) < 0 or int(self.decimal_places) > 6:
            throw("Decimal places must be between 0 and 6.")
