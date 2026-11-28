from velora import Document, throw

from velora_notify import templating


class MessageTemplate(Document):
    def validate(self):
        for label, src in (("subject", self.subject), ("message", self.body)):
            try:
                templating.validate(src or "", templating.MAX_BROADCAST)
            except templating.TemplateError as exc:
                throw(f"The {label}: {exc}")
        if self.channel != "Email":
            self.subject = None
