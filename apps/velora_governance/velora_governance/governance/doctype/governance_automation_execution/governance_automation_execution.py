from velora import Document, throw


class GovernanceAutomationExecution(Document):
    def validate(self):
        if (self.attempts or 0) < 0:
            throw("Attempts cannot be negative.")
        if self.execution_status == "Completed" and not self.completed_at:
            # Completion timestamp is set by the runtime service; enforce consistency.
            throw("Completed execution requires Completed At.")
        if self.execution_status == "Running" and not self.started_at:
            throw("Running execution requires Started At.")
