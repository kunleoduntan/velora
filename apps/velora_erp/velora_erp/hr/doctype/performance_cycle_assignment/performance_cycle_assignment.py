from velora import Document, throw

class PerformanceCycleAssignment(Document):
    def validate(self):
        if not self.cycle or not self.employee:
            throw('Performance Cycle and Employee are required.')
        if self.self_review_due and self.manager_review_due and str(self.manager_review_due) < str(self.self_review_due):
            throw('Manager Review Due cannot precede Self Review Due.')
