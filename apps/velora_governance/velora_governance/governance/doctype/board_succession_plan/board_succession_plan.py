from velora import Document, throw

class BoardSuccessionPlan(Document):
    def validate(self):
        seen=set()
        for row in self.candidates or []:
            key=(row.position,row.candidate)
            if key in seen: throw("A candidate can only appear once for the same succession position.")
            seen.add(key)
            if row.incumbent and row.incumbent==row.candidate:
                throw("The incumbent cannot be listed as their own succession candidate.")
