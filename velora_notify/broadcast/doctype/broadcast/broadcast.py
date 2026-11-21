from velora import Document, throw

from velora_notify import channels, templating

LOCKED = ("Sending", "Sent", "Partly Sent", "Cancelled")


class Broadcast(Document):
    def validate(self):
        old = self._old or {}
        if old.get("status") in LOCKED:
            for f in ("channel", "subject", "message", "audience_source"):
                if old.get(f) != getattr(self, f):
                    throw("A broadcast that has gone out cannot be changed. Duplicate it to send again.")
        if self.template and not (self.message or "").strip():
            from velora import get_doc
            t = get_doc("Message Template", self.template, ignore_permissions=True)
            if t.channel != self.channel:
                throw(f"{t.name} is a {t.channel} template; this broadcast is by {self.channel}.")
            self.message = t.body
            if self.channel == "Email" and not (self.subject or "").strip():
                self.subject = t.subject
        for label, src in (("subject", self.subject), ("message", self.message)):
            try:
                templating.validate(src or "", templating.MAX_BROADCAST)
            except templating.TemplateError as exc:
                throw(f"The {label}: {exc}")
        for label, value in (("copy (CC)", self.cc), ("blind copy (BCC)", self.bcc), ("reply-to", self.reply_to)):
            for a in [x.strip() for x in str(value or "").replace(";", ",").split(",") if x.strip()]:
                if not channels.valid_email(a.lower()):
                    throw(f"{a!r} is not a valid email address ({label}).")
        if self.channel != "Email" and (self.cc or self.bcc or self.reply_to):
            throw("Copies and reply-to are for email only.")
        if int(self.send_rate_per_minute or 0) < 1:
            self.send_rate_per_minute = 120
