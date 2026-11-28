from velora import Document, throw


class ClimateScenarioAnalysis(Document):
    """A completed analysis must carry what IFRS S2 paragraph 22 asks an entity to disclose about it."""

    def validate(self):
        names = [r.scenario_name for r in (self.scenarios or [])]
        if len(names) != len(set(names)):
            throw("Each scenario can be listed once.")
        for row in self.impacts or []:
            if row.scenario_name not in names:
                throw(f"Estimated effect refers to scenario '{row.scenario_name}', which is not in the scenario list.")
            if row.low_amount is not None and row.high_amount is not None and float(row.low_amount) > float(row.high_amount):
                throw("An effect range needs low estimate <= high estimate.")
            if row.low_amount is None and row.high_amount is None and not (row.not_quantified_reason or "").strip():
                throw(f"'{row.risk_or_opportunity}': give an estimate, or explain why it is not quantified.")
        if self.analysis_status != "Completed":
            return
        problems = []
        if len(names) < 2:
            problems.append("at least two scenarios (S2.22(b)(i)(2) asks whether a diverse range was used)")
        if not self.diverse_range:
            problems.append("confirm a diverse range of scenarios was used, or keep the analysis In Progress")
        if not any(r.aligned_with_latest_agreement for r in (self.scenarios or [])):
            problems.append("a scenario aligned with the latest international climate agreement (S2.22(b)(i)(4)); if you used none, record that in notes and leave the analysis In Progress")
        if not any(r.scenario_type in ("Transition", "Transition and physical") for r in (self.scenarios or [])) or not any(r.scenario_type in ("Physical", "Transition and physical") for r in (self.scenarios or [])):
            problems.append("cover both transition and physical risks, or explain why not in notes")
        for field, label in (("relevance_rationale", "relevance rationale"), ("time_horizons", "time horizons"), ("operations_covered", "scope of operations"),
                             ("policy_assumptions", "policy assumptions"), ("macro_assumptions", "macroeconomic assumptions"), ("regional_assumptions", "regional assumptions"),
                             ("energy_assumptions", "energy assumptions"), ("technology_assumptions", "technology assumptions"), ("strategy_implications", "strategy implications"),
                             ("uncertainties", "areas of uncertainty"), ("performed_on", "performed-on date")):
            if not getattr(self, field, None) or (isinstance(getattr(self, field), str) and not getattr(self, field).strip()):
                problems.append(label)
        if problems:
            throw("A completed Climate Scenario Analysis needs: " + "; ".join(problems) + ".")
