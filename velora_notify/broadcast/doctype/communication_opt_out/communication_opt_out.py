from velora import Document, get_list, throw
from velora.document.document import now

from velora_notify import channels, gateways


class CommunicationOptOut(Document):
    def validate(self):
        raw = (self.address or "").strip()
        if "@" in raw:
            if not channels.valid_email(raw.lower()):
                throw(f"{raw!r} is not a valid email address.")
            self.address = raw.lower()
            if self.channel in ("SMS", "WhatsApp"):
                throw("An email address cannot opt out of SMS or WhatsApp.")
        else:
            number = gateways.normalize_phone(raw)
            if not number:
                throw(f"{raw!r} is neither an email address nor a phone number.")
            self.address = number
            if self.channel == "Email":
                throw("A phone number cannot opt out of email.")
        if not self.opted_out_on:
            self.opted_out_on = now()
        for r in get_list("Communication Opt-Out", filters=[["address", "=", self.address], ["channel", "=", self.channel], ["name", "!=", self.name or ""]], fields=["name"], limit=1, ignore_permissions=True):
            throw(f"{self.address} is already on the list ({r['name']}).")
