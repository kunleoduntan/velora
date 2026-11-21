from velora import Document, throw

class SuccessionCandidate(Document):
    def validate(self):
        score = self.readiness_score
        if score not in (None, '') and not 0 <= float(score) <= 100:
            throw('Readiness Score must be between 0 and 100.')
        if not self.critical_position or not self.employee:
            throw('Critical Position and Successor Candidate are required.')
