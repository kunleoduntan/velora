from velora import Document, get_list, throw

class DisclosureApplicability(Document):
    def validate(self):
        disclosures=get_list("Sustainability Disclosure",filters=[["name","=",self.disclosure]],fields=["framework","disclosure_title"],limit=1)
        if not disclosures: throw("The selected Disclosure could not be found.")
        if not self.applicable and not self.rationale:
            throw("Not Applicable disclosures require a rationale.")
        if self.disclosure_status=="Completed" and self.applicable and not self.evidence:
            throw("Completed applicable disclosures require supporting evidence.")
