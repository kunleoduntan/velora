from velora import Document, get_list, throw

class SustainabilityTarget(Document):
    def validate(self):
        metrics=get_list("Sustainability Metric",filters=[["name","=",self.metric]],fields=["default_unit","data_type"],limit=1)
        if not metrics:throw("The selected Sustainability Metric could not be found.")
        if metrics[0].get("data_type") not in ("Numeric","Percentage","Currency"):
            throw("Targets can only be defined for Numeric, Percentage or Currency Metrics.")
        if metrics[0].get("default_unit") and self.unit!=metrics[0].get("default_unit"):
            throw("Target Unit must match the Metric Default Unit.")
        if int(self.target_year or 0)<=int(self.baseline_year or 0):
            throw("Target Year must be later than Baseline Year.")
        if self.current_value is not None:
            baseline=float(self.baseline_value);target=float(self.target_value);current=float(self.current_value)
            if self.target_direction=="Reduce":
                progress=100 if baseline==target and current<=target else 0 if baseline==target else (baseline-current)/(baseline-target)*100
            elif self.target_direction=="Increase":
                progress=100 if baseline==target and current>=target else 0 if baseline==target else (current-baseline)/(target-baseline)*100
            else:
                progress=100 if current==target else 0
            self.progress_percent=round(max(0,min(100,progress)),2)
            if self.progress_percent>=100:self.target_status="Achieved"
        for row in self.progress_history or []:
            if row.actual_value is not None:
                baseline=float(self.baseline_value);target=float(self.target_value);actual=float(row.actual_value)
                progress=100 if baseline==target and ((self.target_direction=="Reduce" and actual<=target) or (self.target_direction=="Increase" and actual>=target) or actual==target) else 0 if baseline==target else (baseline-actual)/(baseline-target)*100 if self.target_direction=="Reduce" else (actual-baseline)/(target-baseline)*100 if self.target_direction=="Increase" else 100 if actual==target else 0
                row.progress_percent=round(max(0,min(100,progress)),2)
        if self.climate_target:
            missing=[label for f,label in (("objective","objective"),("entity_part_covered","part of the entity covered"),("target_basis","absolute or intensity"),("milestones","milestones")) if not (getattr(self,f,None) or "").strip()]
            if self.ghg_target:
                missing+=[label for f,label in (("gases_covered","gases covered"),("scopes_covered","scopes covered"),("gross_or_net","gross or net"),("sectoral_decarbonisation","sectoral approach yes/no")) if not (getattr(self,f,None) or "").strip()]
                if self.gross_or_net=="Net" and not (self.gross_target_if_net or "").strip():
                    missing.append("the associated gross target (a net target must show it)")
            if missing and self.target_status not in ("Draft","Cancelled"):
                throw("A climate-related target needs, under IFRS S2 paragraphs 33 and 36: "+", ".join(missing)+". Keep it as Draft until these are known.")
