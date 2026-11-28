from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I

CHECKS = [("Customer", "Email", "email"), ("Customer", "Phone", "phone"), ("Supplier", "Email", "email"), ("Supplier", "Phone", "phone"),
          ("Employee", "Personal email", "personal_email"), ("Employee", "Mobile", "mobile"), ("Employee", "Date of birth", "date_of_birth"), ("Employee", "Date of joining", "date_of_joining")]


def execute(filters):
    rb = ReportBuilder("Data Quality Scorecard", [Column("entity", "Records"), Column("field", "Detail"), Column("total", "Records", "Int"), Column("filled", "Filled", "Int"), Column("missing", "Missing", "Int"), Column("score", "Complete", "Percent"), Column("grade", "Grade")])
    cache, scores = {}, []
    for entity, label, field in CHECKS:
        if entity not in cache:
            try:
                cache[entity] = get_list(entity, fields=["name"] + sorted({f for e, _, f in CHECKS if e == entity}), limit=200000, ignore_permissions=True)
            except Exception:  # noqa: BLE001 - an app without this form simply has nothing to score
                cache[entity] = None
        rows = cache[entity]
        if rows is None:
            continue
        filled = sum(1 for r in rows if str(r.get(field) or "").strip())
        score = I.pct(filled, len(rows)) if rows else 100.0
        scores.append(score)
        rb.row({"entity": entity, "field": label, "total": len(rows), "filled": filled, "missing": len(rows) - filled, "score": score, "grade": "Excellent" if score >= 95 else "Good" if score >= 80 else "Needs attention" if score >= 50 else "Poor"})
    avg = round(sum(scores) / len(scores), 1) if scores else 0
    return rb.build(summary=[{"label": "Overall completeness (%)", "value": avg, "fieldtype": "Float"}, {"label": "Gaps to fix", "value": sum(r.values["missing"] for r in rb.rows), "fieldtype": "Int"}])
