import math

from velora import Document, get_list, throw


def _band(value, label):
    if value in (None, ""):
        return None
    value = int(value)
    if not 1 <= value <= 5:
        throw(f"{label} must be between 1 and 5.")
    return value


def impact_score(row):
    """Severity of an impact on a 1-5 scale from scale, scope and (for negative impacts) irremediable character."""
    scale, scope, irr = _band(row.scale, "Scale"), _band(row.scope_of_impact, "Scope"), _band(row.irremediability, "Irremediable character")
    if scale is None or scope is None:
        return None
    parts = [scale, scope] + ([irr] if (row.direction or "Negative") == "Negative" and irr is not None else [])
    return round(sum(parts) / len(parts), 2)


def financial_score(row):
    """Magnitude x likelihood on the 5x5 matrix, mapped back to 1-5."""
    mag, lik = _band(row.financial_magnitude, "Financial magnitude"), _band(row.financial_likelihood, "Financial likelihood")
    if mag is None or lik is None:
        return None
    return math.ceil(mag * lik / 5)


class MaterialityAssessment(Document):
    """Impact and financial materiality are judged separately and a topic is material if either is (the double-materiality rule).
    Structured criteria compute the scores; the entity's thresholds decide; an override needs a reason; completing needs sign-off."""

    def validate(self):
        settings_rows = get_list("Sustainability Settings", fields=["name", "impact_materiality_threshold", "financial_materiality_threshold"], limit=1, ignore_permissions=True)
        settings = settings_rows[0] if settings_rows else {}
        impact_threshold = int(self.impact_threshold or settings.get("impact_materiality_threshold") or 3)
        financial_threshold = int(self.financial_threshold or settings.get("financial_materiality_threshold") or 3)
        likelihood_threshold = int(self.likelihood_threshold or 3)
        if not 1 <= impact_threshold <= 5 or not 1 <= financial_threshold <= 5 or not 1 <= likelihood_threshold <= 5:
            throw("Materiality thresholds must be between 1 and 5.")
        seen = set()
        for row in self.topics or []:
            key = (row.topic, row.iro_type or "")
            if key in seen:
                throw("A topic can be assessed once per impact/risk/opportunity type in an assessment.")
            seen.add(key)
            for field in ("impact_score", "financial_score"):
                _band(getattr(row, field, None), field.replace("_", " ").title())
            _band(row.impact_likelihood, "Impact likelihood")
            computed_impact, computed_fin = impact_score(row), financial_score(row)
            if computed_impact is not None:
                row.impact_score = round(computed_impact)
            if computed_fin is not None:
                row.financial_score = computed_fin
            impact = float(row.impact_score or 0)
            financial = float(row.financial_score or 0)
            impact_hit = impact >= impact_threshold
            if impact_hit and (row.nature or "Actual") == "Potential" and not row.human_rights:
                impact_hit = int(row.impact_likelihood or 0) >= likelihood_threshold      # severity decides for human rights; otherwise likelihood counts
            fin_hit = financial >= financial_threshold
            if self.methodology == "Impact":
                fin_hit = False
            elif self.methodology == "Financial":
                impact_hit = False
            row.impact_material = int(impact_hit); row.financial_material = int(fin_hit)
            row.materiality_score = round(max(impact, financial) if self.methodology == "Double Materiality" else (impact if self.methodology == "Impact" else financial), 2)
            row.material = int(impact_hit or fin_hit)
            row.material_basis = "Both" if impact_hit and fin_hit else "Impact" if impact_hit else "Financial" if fin_hit else "Neither"
            if row.override:
                if not (row.override_reason or "").strip():
                    throw("A management override needs a written reason.")
                row.material = int(row.override == "Material")
                row.material_basis = f"Override ({row.override})"
        if self.assessment_status == "Completed":
            problems = []
            if not self.topics:
                problems.append("topics")
            if not self.completed_on:
                problems.append("Completed On date")
            if self.methodology == "Double Materiality" and not (self.stakeholder_engagement or "").strip():
                problems.append("stakeholder engagement")
            if not (self.approved_by or "").strip() or not self.approved_on:
                problems.append("approval by the board or its committee (name and date)")
            unexplained = [r.topic for r in (self.topics or []) if not r.material and not (r.rationale or "").strip()]
            if unexplained:
                problems.append("a rationale for each topic judged not material (" + ", ".join(unexplained[:5]) + ")")
            unscored = [r.topic for r in (self.topics or []) if not r.override and not (r.impact_score or r.financial_score)]
            if unscored:
                problems.append("scores for every topic (" + ", ".join(unscored[:5]) + ")")
            if problems:
                throw("A completed Materiality Assessment needs: " + "; ".join(problems) + ".")
