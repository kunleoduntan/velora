from velora import Document, throw

from velora_erp.engagement.branding import HEX


class EngagementSettings(Document):
    def validate(self):
        if self.brand_colour and not HEX.match(self.brand_colour):
            throw("Brand colour must be a hex colour such as #0f6cbd.")
        if self.logo_url and not self.logo_url.startswith("https://"):
            throw("The logo address must start with https://.")
        for f in ("winback_customer_days", "winback_supplier_days", "winback_repeat_days"):
            if int(self.get(f) or 0) < 7:
                throw("Quiet periods must be at least 7 days.")
