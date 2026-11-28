from velora import Document, throw, get_list
class AttendanceDevice(Document):
    def validate(self):
        if self.serial_number:
            rows=get_list("Attendance Device",filters=[["serial_number","=",self.serial_number]],fields=["name"],limit=5,ignore_permissions=True)
            if any(x.get("name")!=getattr(self,"name",None) for x in rows): throw("A device with this serial number is already registered.")
