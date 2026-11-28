from velora import Document, throw

class BoardEvaluationTemplate(Document):
    def validate(self):
        sequences=set()
        for row in self.questions or []:
            if row.sequence in sequences:
                throw("Evaluation Question Sequence must be unique.")
            sequences.add(row.sequence)
            if float(row.weight or 0)<=0:
                throw("Evaluation Question Weight must be greater than zero.")
