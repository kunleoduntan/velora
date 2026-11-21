from velora import Document, throw
class PerformanceReviewTemplate(Document):
    def validate(self):
        rows=list(getattr(self,"criteria",None) or [])
        if not rows: throw("Add at least one assessment criterion.")
        codes=set(); total=0
        for row in rows:
            code=str(getattr(row,"criterion_code","") or "").strip().casefold()
            if not code or code in codes: throw("Each criterion must have a unique Criterion Code.")
            codes.add(code); weight=float(getattr(row,"weight",0) or 0)
            if weight < 0 or weight > 100: throw("Criterion weights must be between 0 and 100.")
            total += weight
        if self.rating_method == "Weighted Average" and round(total,2) != 100:
            throw(f"Weighted assessment criteria must total 100%. Current total: {total:.2f}%.")
