from velora import Document, throw

class Candidate(Document):
    def validate(self):
        if self.consent_status == "Granted" and not self.consent_date:
            throw("Record the consent date when candidate data processing consent is granted.")
        if self.converted_employee and self.candidate_status != "Hired":
            throw("A converted candidate must have Hired status.")
        if self.candidate_status == "Hired" and not self.converted_employee:
            throw("Link the Employee record before marking a candidate as Hired.")
