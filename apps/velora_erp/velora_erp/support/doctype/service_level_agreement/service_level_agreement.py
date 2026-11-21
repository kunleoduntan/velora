from velora import Document, throw

from velora_erp.support.sla import parse_hhmm


class ServiceLevelAgreement(Document):
    def validate(self):
        seen = set()
        for row in self.targets or []:
            if row.priority in seen:
                throw(f"{row.priority} appears twice in the targets.")
            seen.add(row.priority)
            if float(row.first_response_hours or 0) <= 0 or float(row.resolution_hours or 0) <= 0:
                throw("Targets must be more than zero hours.")
            if float(row.first_response_hours) > float(row.resolution_hours):
                throw(f"{row.priority}: the first response cannot be due after the resolution.")
        if not seen:
            throw("Add at least one priority target.")
        if not 1 <= int(self.warn_at_percent or 80) <= 100:
            throw("The warning point must be between 1 and 100 per cent.")
        if not self.round_the_clock:
            for label, value in (("starts", self.work_start), ("ends", self.work_end)):
                try:
                    h, m = (value or "").split(":")
                    int(h), int(m)
                except Exception:  # noqa: BLE001
                    throw(f"The day {label} must be written HH:MM, for example 08:00.")
            if parse_hhmm(self.work_end, "17:00") <= parse_hhmm(self.work_start, "08:00"):
                throw("The working day must end after it starts.")
        if self.is_default and (self.customer or self.category):
            throw("The default agreement cannot be limited to a customer or category.")
        if self.is_default and self.enabled:
            from velora import get_list
            for row in get_list("Service Level Agreement", filters=[["is_default", "=", 1], ["enabled", "=", 1], ["name", "!=", self.name or ""]], fields=["name"], limit=1, ignore_permissions=True):
                throw(f"{row['name']} is already the default agreement.")
