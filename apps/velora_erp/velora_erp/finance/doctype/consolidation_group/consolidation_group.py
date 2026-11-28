from velora import Document, throw


class ConsolidationGroup(Document):
    def validate(self):
        self.group_name = (self.group_name or "").strip()
        if not self.group_name:
            throw("Give the consolidation group a name")
        if not self.presentation_currency:
            throw("Choose the currency the group reports in")
        seen = set()
        for m in self.members or []:
            cid = (m.company_id or "").strip()
            if not cid:
                throw("Every member needs a company")
            if cid in seen:
                throw(f"{cid} is listed twice; each company can be a member once")
            seen.add(cid)
            pct = float(m.ownership_percent or 0)
            if not 0 < pct <= 100:
                throw(f"Ownership of {cid} must be more than 0 and at most 100")
            for rate in ("closing_rate", "average_rate", "equity_rate", "opening_rate"):
                if float(getattr(m, rate) or 0) < 0:
                    throw(f"A rate for {cid} cannot be negative")
        names = seen
        for r in self.eliminations or []:
            if r.company_one not in names or r.company_two not in names:
                throw(f"Elimination “{r.description}” names a company that is not a member of this group")
            if r.basis == "Fixed amount" and float(r.fixed_amount or 0) <= 0:
                throw(f"Elimination “{r.description}” needs a fixed amount")
        for m in self.mappings or []:
            if m.company_id not in names:
                throw(f"The mapping for {m.account} names a company that is not a member of this group")
