from velora import Document, throw, get_list
from datetime import date
class AttendanceDeviceUserMapping(Document):
    def validate(self):
        if self.integration and self.external_user_id:
            self.mapping_key=f"{self.integration}:{self.device or '*'}:{str(self.external_user_id).strip()}"
            rows=get_list("Attendance Device User Mapping",filters=[["mapping_key","=",self.mapping_key]],fields=["name"],limit=5,ignore_permissions=True)
            if any(x.get("name")!=getattr(self,"name",None) for x in rows): throw("This external user identifier is already mapped for this integration/device.")
        a=date.fromisoformat(str(self.effective_from)[:10]) if self.effective_from else None
        b=date.fromisoformat(str(self.effective_to)[:10]) if self.effective_to else None
        if a and b and b<a: throw("Mapping end date cannot precede its start date.")
