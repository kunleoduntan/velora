from velora import Document, throw


class TreasurySettings(Document):
    def validate(self):
        for f in ("repayment_warning_days", "expiry_warning_days", "forecast_weeks"):
            if int(getattr(self, f) or 0) < 0:
                throw("Day and week counts cannot be negative.")
        if int(self.forecast_weeks or 0) < 1 or int(self.forecast_weeks) > 52:
            throw("The liquidity forecast covers between 1 and 52 weeks.")
