from datetime import timedelta

from velora import Document, get_list, throw

from velora_erp.finance.source_documents import ensure_approved, validate_approval_transition
from velora_erp.investments import calculations as calc
from velora_erp.investments import posting
from velora_erp.investments.settings import get_settings

D, money = calc.D, calc.money


def _base_currency():
    rows = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
    return (rows[0].get("base_currency") if rows else None) or ""


class Investment(Document):
    def validate(self):
        validate_approval_transition(self)
        if int(self.docstatus or 0) != 0:
            return
        s = get_settings()
        cls = self.investment_class
        group, fixed, method, mode, measurement, wht_default = calc.CLASSES[cls] if cls in calc.CLASSES else calc.CLASSES["Other"]
        fresh = not getattr(self, "_old", None)
        self.asset_group = group
        if not self.currency:
            self.currency = _base_currency()
        if fresh:                                            # class defaults apply when the investment is first saved; after that the user's choices stand
            if fixed:
                self.interest_method = self.interest_method or method
                if mode and not self.payment_mode:
                    self.payment_mode = mode
            self.measurement = measurement if self.measurement in (None, "", "Amortised cost / Cost") else self.measurement
            self.wht_applicable = 1 if wht_default and self.wht_applicable in (None, 1) else 0
        if self.wht_applicable and not D(self.wht_rate):
            self.wht_rate = s.get("default_wht_rate") or 0
        if not self.wht_applicable:
            self.wht_rate = 0
        if self.currency == _base_currency():
            self.exchange_rate = 1
        elif D(self.exchange_rate) <= 0:
            throw("Enter the exchange rate.")
        if fixed:
            self._fixed_income_terms()
        else:
            self._holding_terms()

    def _fixed_income_terms(self):
        if not self.start_date:
            throw("Enter the start date.")
        start = self.start_date
        old = getattr(self, "_old", None) or {}
        derived = start + timedelta(days=int(self.tenor_days)) if self.tenor_days else None
        if self.maturity_date and (not self.tenor_days or (derived != self.maturity_date and str(self.maturity_date) != str(old.get("maturity_date")))):
            self.tenor_days = (self.maturity_date - start).days          # the maturity date was typed (or changed): it wins
        elif derived:
            self.maturity_date = derived
        if not self.maturity_date or self.maturity_date <= start:
            throw("Give a tenor in days, or a maturity date after the start date.")
        self.tenor_days = (self.maturity_date - start).days
        days, convention = int(self.tenor_days), self.day_count or "Actual/365"
        method = self.interest_method or "Simple Interest"
        if method == "Discount (T-Bill)":
            if not D(self.face_value):
                throw("A discount instrument needs its face value.")
            if D(self.interest_rate) and not D(self.principal):
                self.principal = calc.discount_price(self.face_value, self.interest_rate, days, convention)
            elif D(self.principal) and not D(self.interest_rate):
                self.interest_rate = float(calc.money((D(self.face_value) - D(self.principal)) / D(self.face_value) * D(calc.basis(convention)) / D(days) * 100))
            if D(self.principal) >= D(self.face_value):
                throw("The cost must be below the face value of a discount instrument.")
        if D(self.principal) <= 0:
            throw("Enter the amount invested.")
        if self.payment_mode == "Periodic" and not self.payment_frequency:
            throw("Choose how often the income is paid.")
        if method == "Coupon (Bond)" and not D(self.face_value):
            self.face_value = self.principal
        gross = calc.total_gross_income(method, self.principal, self.face_value, self.interest_rate, days, convention)
        wht = money(gross * D(self.wht_rate) / 100) if self.wht_applicable else calc.money(0)
        fee = money(gross * D(self.management_fee_percent) / 100)
        self.expected_gross_income, self.expected_wht, self.expected_net_income = gross, wht, money(gross - wht - fee)
        self.maturity_value = money(D(self.principal) + gross)
        self.effective_yield = float(calc.effective_yield(gross, self.principal, days, convention))
        rows = calc.build_schedule(start, self.maturity_date, gross, self.payment_mode or "At Maturity", self.payment_frequency, self.wht_rate if self.wht_applicable else 0, self.management_fee_percent, convention)
        self.set("schedule", rows)
        self._link_children()

    def _holding_terms(self):
        if not self.start_date:
            throw("Enter the purchase date.")
        if D(self.units) and D(self.unit_cost) and not D(self.principal):
            self.principal = money(D(self.units) * D(self.unit_cost))
        if D(self.principal) <= 0:
            throw("Enter the amount invested, or the units and the cost per unit.")
        self.set("schedule", [])
        self.expected_gross_income = self.expected_wht = self.expected_net_income = self.maturity_value = 0
        self.effective_yield = 0
        if self.investment_class == "Real Estate" and D(self.expected_annual_rent) > 0:
            self.effective_yield = float(money(D(self.expected_annual_rent) / D(self.principal) * 100))

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        posting.post_purchase(self)

    def before_delete(self):
        if int(self.docstatus or 0) == 1:
            throw("A submitted investment cannot be deleted.")
