from velora import Document, throw

class SustainabilityInitiative(Document):
    def validate(self):
        if self.start_date and self.end_date and self.end_date<self.start_date:
            throw("Initiative End Date cannot precede Start Date.")
        progress=float(self.progress_percent or 0)
        if progress<0 or progress>100:throw("Initiative Progress Percent must be between 0 and 100.")
        if self.initiative_status=="Completed":self.progress_percent=100
