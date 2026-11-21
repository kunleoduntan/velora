from velora import Document, throw
class CompetencyFramework(Document):
    def validate(self):
        scope_fields={"Department":"department","Designation":"designation","Job Grade":"job_grade","Job Position":"job_position","Employee":"employee"}
        scope_field=scope_fields.get(self.applies_to)
        if scope_field and not getattr(self,scope_field,None): throw(f"Select {self.applies_to} for this competency framework.")
        rows=list(getattr(self,"competencies",None) or [])
        if not rows: throw("Add at least one competency to the framework.")
        seen=set(); total=0
        for row in rows:
            code=str(getattr(row,"competency","") or "").casefold()
            if not code or code in seen: throw("Each competency must appear only once in a framework.")
            seen.add(code); level=int(getattr(row,"required_level",0) or 0)
            if level < 1 or level > 5: throw("Required proficiency level must be between 1 and 5.")
            weight=float(getattr(row,"weight",0) or 0)
            if weight < 0 or weight > 100: throw("Competency weight must be between 0 and 100%.")
            total += weight
        if any(float(getattr(r,"weight",0) or 0)>0 for r in rows) and round(total,2)!=100:
            throw(f"If competency weights are used, they must total 100%. Current total: {total:.2f}%.")
        start,end=self.effective_from,self.effective_to
        if start and end and str(end)<str(start): throw("Framework Effective To cannot precede Effective From.")
