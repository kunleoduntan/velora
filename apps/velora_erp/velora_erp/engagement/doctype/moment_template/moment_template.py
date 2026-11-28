import re

from velora import Document, throw

from velora_erp.engagement.branding import HEX

KEYS = {"first_name", "full_name", "company", "occasion", "years_text", "days_text"}


class MomentTemplate(Document):
    def validate(self):
        for label, text in (("subject", self.subject), ("heading", self.heading), ("message", self.body)):
            for key in re.findall(r"\{\{\s*(\w+)\s*\}\}", text or ""):
                if key not in KEYS:
                    throw(f"The {label} uses {{{{ {key} }}}}, which is not a known placeholder. Use: " + ", ".join("{{ %s }}" % k for k in sorted(KEYS)) + ".")
        if self.accent_colour and not HEX.match(self.accent_colour):
            throw("Accent colour must be a hex colour such as #0f6cbd.")
        if self.button_url and not self.button_url.startswith(("https://", "http://", "mailto:")):
            throw("The button address must start with https://, http:// or mailto:. Leave it empty to use the website or reply-to address from Engagement Settings.")
