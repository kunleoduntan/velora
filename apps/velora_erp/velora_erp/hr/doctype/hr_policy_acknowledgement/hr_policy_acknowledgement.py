"""Exact-version acknowledgement integrity."""
from velora import Document, throw

class HRPolicyAcknowledgement(Document):
    def validate(self):
        if not self.policy_document or not self.policy_version or not self.employee:
            throw("Policy, Policy Version and Employee are required.")
        if self.acknowledgement_status in {"Acknowledged","Declined"} and not self.acknowledged_on:
            throw("A resolved acknowledgement must retain its timestamp.")
