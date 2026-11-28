from velora import Document, throw


class TaxonomyConceptMap(Document):
    def validate(self):
        if self.element_qname:
            prefix, _, name = self.element_qname.partition(":")
            if not prefix.isidentifier() or not name or not name.replace("_", "").replace("-", "").replace(".", "").isalnum():
                throw("Element QName must look like prefix:ElementName.")
        if (self.decimals or "0") != "INF" and not str(self.decimals or "0").lstrip("-").isdigit():
            throw("Decimals must be a whole number or INF.")
        src = self.source or "GHG inventory"
        if src == "Data point" and not self.source_metric:
            throw("A fact fed by a data point needs a Sustainability Metric.")
        if src == "Report section text":
            if not self.source_disclosure:
                throw("A text-block fact needs the Disclosure whose report-section text it carries.")
            self.fact_type = "Text block"
        elif self.fact_type == "Text block":
            throw("Only report-section text can be a text block.")
        if self.fact_type == "Monetary" and not (self.unit_measure or "").strip():
            throw("A monetary fact needs a unit measure, e.g. iso4217:NGN (the currency code from the taxonomy's unit registry).")
        if self.scale and not str(self.scale).lstrip("-").isdigit():
            throw("Scale must be a whole number such as -2.")
