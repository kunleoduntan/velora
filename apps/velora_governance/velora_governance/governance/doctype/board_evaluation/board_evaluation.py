from velora import Document, get_doc, get_list, throw

class BoardEvaluation(Document):
    def validate(self):
        templates=get_list("Board Evaluation Template",filters=[["name","=",self.template]],fields=["evaluation_type"],limit=1)
        if not templates: throw("The Evaluation Template could not be found.")
        evaluation_type=templates[0].get("evaluation_type")
        if evaluation_type=="Board" and not self.board: throw("Board Evaluations require a Board.")
        if evaluation_type=="Committee" and not self.committee: throw("Committee Evaluations require a Committee.")
        if evaluation_type=="Individual Director" and not self.board_member: throw("Individual Director Evaluations require a Board Member.")
        if self.committee:
            committees=get_list("Board Committee",filters=[["name","=",self.committee]],fields=["board","governance_entity"],limit=1)
            if committees:
                if self.board and self.board!=committees[0].get("board"): throw("Evaluation Committee must belong to the selected Board.")
                self.board=committees[0].get("board")
                if self.governance_entity and self.governance_entity!=committees[0].get("governance_entity"): throw("Evaluation Committee must belong to the selected Entity.")
                self.governance_entity=committees[0].get("governance_entity")
        template=get_doc("Board Evaluation Template",self.template)
        questions={row.sequence:row for row in template.questions or []}
        mandatory={row.sequence for row in template.questions or [] if row.mandatory}
        seen=set(); total_weight=0.0; weighted=0.0
        for row in self.responses or []:
            if row.sequence in seen: throw("Evaluation Response Question Sequence must be unique.")
            if row.sequence not in questions: throw("A Response references a Question not included in the selected Template.")
            seen.add(row.sequence); question=questions[row.sequence]
            if int(row.rating)<1 or int(row.rating)>5: throw("Evaluation Rating must be between 1 and 5.")
            row.category=question.category; row.question_text=question.question; row.weight=float(question.weight)
            total_weight+=float(question.weight); weighted+=int(row.rating)*float(question.weight)
        if self.evaluation_status=="Completed":
            if not self.evaluation_date or not self.evaluator: throw("Completed Evaluations require an Evaluation Date and Evaluator.")
            if not mandatory<=seen: throw("All mandatory evaluation questions must be answered before completion.")
        self.overall_score=round(weighted/total_weight,2) if total_weight else 0
