from velora import Document, throw


class GWPSet(Document):
    def validate(self):
        names = [v.gas.strip() for v in (self.get("values") or []) if v.gas]
        if len(names) != len(set(names)):
            throw("Each gas can appear only once in a GWP Set.")
        for v in self.get("values") or []:
            if float(v.gwp or 0) <= 0:
                throw(f"The GWP of {v.gas} must be greater than zero.")
