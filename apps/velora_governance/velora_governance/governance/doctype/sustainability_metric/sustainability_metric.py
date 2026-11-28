from velora import Document, throw

class SustainabilityMetric(Document):
    def validate(self):
        seen=set()
        for row in self.frameworks or []:
            key=(row.framework,row.standard,row.disclosure)
            if key in seen:throw("Duplicate Metric Framework Mapping.")
            seen.add(key)
