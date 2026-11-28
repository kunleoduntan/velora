from velora import Document, throw


class XBRLExportSetting(Document):
    def validate(self):
        if not (self.schema_ref or "").lower().startswith(("http://", "https://")):
            throw("The taxonomy entry point must be an http(s) URL.")
        for line in (self.extra_namespaces or "").splitlines():
            if line.strip() and ("=" not in line or not line.split("=", 1)[0].strip().isidentifier()):
                throw(f"Namespace line '{line}' must look like prefix=uri.")
