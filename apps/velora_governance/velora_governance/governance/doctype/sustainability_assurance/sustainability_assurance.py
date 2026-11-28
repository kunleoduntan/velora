from datetime import datetime, timezone

from velora import Document, get_list, throw
from velora.permissions import get_session

from velora_governance.governance.services.assurance_lock import ASSURANCE_LEVELS

RELEASERS = {"System Manager", "Governance Administrator"}


class SustainabilityAssurance(Document):
    def validate(self):
        reports = get_list("Sustainability Report", filters=[["name", "=", self.report]], fields=["governance_entity", "reporting_period"], limit=1)
        if not reports:
            throw("The selected Sustainability Report could not be found.")
        if self.governance_entity and self.governance_entity != reports[0].get("governance_entity"):
            throw("Assurance Entity must match the Sustainability Report Entity.")
        self.governance_entity = reports[0].get("governance_entity")
        if self.reporting_period:
            periods = get_list("Sustainability Reporting Period", filters=[["name", "=", self.reporting_period]], fields=["governance_entity"], limit=1)
            if not periods or periods[0].get("governance_entity") != self.governance_entity:
                throw("The Reporting Period must belong to the same entity as the report.")
        if self.assurance_status == "Completed":
            if not self.assurance_date or not self.report_reference:
                throw("Completed Assurance records require an Assurance Date and Report Reference.")
            if self.assurance_type in (None, "", "None"):
                throw("A completed assurance engagement must say whether it was limited or reasonable assurance.")
            missing = [label for label, value in (("Provider", self.provider), ("Standard", self.assurance_standard), ("Opinion", self.opinion), ("Reporting Period", self.reporting_period)) if not value]
            if missing:
                throw("Completed assurance needs: " + ", ".join(missing) + ".")
            if self.opinion in ("Adverse", "Disclaimer") and not self.conclusion:
                throw("Explain the basis for an adverse opinion or disclaimer in the Conclusion.")
        self._handle_lock_release()

    def _handle_lock_release(self):
        """Releasing the lock needs a reason and an authorised user; who and when are stamped. It cannot be undone on this record."""
        if self.locks_period_data:
            return
        if self.is_new():
            self.locks_period_data = 1
            return
        if not self.lock_release_reason or len(self.lock_release_reason.strip()) < 10:
            throw("Give the reason for releasing the lock (at least a sentence).")
        if not self.lock_released_by:
            if not (RELEASERS & set(get_session().roles or ())):
                throw("Only a Governance Administrator can release the lock on assured data.")
            self.lock_released_by = get_session().user
            self.lock_released_on = datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
