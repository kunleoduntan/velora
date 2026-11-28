from velora import Document, throw

class SustainabilityReport(Document):
    def validate(self):
        framework_names=set()
        for row in self.frameworks or []:
            if row.framework in framework_names:throw("A Framework can only be included once in a Report.")
            framework_names.add(row.framework)
        sequences=set();completed=0
        for row in self.sections or []:
            if row.sequence in sequences:throw("Report Section Sequence must be unique.")
            sequences.add(row.sequence)
            if row.section_status in ("Completed","Not Applicable"):completed+=1
        total=len(self.sections or [])
        self.readiness_percent=round(completed*100/total,2) if total else 0
        self.missing_sections=total-completed
        if self.report_status=="Published" and (not self.file_reference or not self.published_date or self.readiness_percent<100):
            throw("Published Reports require a file reference, Published Date and 100% section readiness.")
