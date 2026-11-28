from velora import Document, throw
from urllib.parse import urlparse
class AttendanceIntegration(Document):
    def validate(self):
        if self.page_size and (int(self.page_size)<1 or int(self.page_size)>500): throw("Page size must be between 1 and 500.")
        if self.transport=="REST API Pull":
            p=urlparse(str(self.api_base_url or ""))
            if p.scheme!="https" or not p.hostname or p.username or p.password: throw("REST API Base URL must be HTTPS and must not contain embedded credentials.")
            if not self.credential_env or not str(self.credential_env).replace("_", "").isalnum(): throw("Provide the environment variable name holding the provider token.")
        if getattr(self,"provider",None)=="ZKTeco BioTime" and self.transport!="REST API Pull": throw("ZKTeco BioTime uses its documented REST API pull connector in this release.")
