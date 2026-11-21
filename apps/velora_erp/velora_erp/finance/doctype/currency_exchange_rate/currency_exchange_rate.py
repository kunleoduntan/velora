from decimal import Decimal
from velora import Document, throw


class CurrencyExchangeRate(Document):
    def validate(self):
        self.from_currency = str(self.from_currency or "").upper(); self.to_currency = str(self.to_currency or "").upper()
        if len(self.from_currency) != 3 or len(self.to_currency) != 3:
            throw("Currencies must be three-letter ISO codes.")
        if self.from_currency == self.to_currency:
            throw("From and To currency must differ.")
        if Decimal(str(self.rate or 0)) <= 0:
            throw("Exchange rate must be greater than zero.")
