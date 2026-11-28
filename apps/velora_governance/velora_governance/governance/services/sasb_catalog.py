"""SASB industry metrics: structure, Excel import, and the entity's responses.

The SASB Standards are IFRS Foundation licensed content, so this software ships no SASB industries or metrics. You load the
industries and metrics you are licensed to use from an Excel workbook (template provided), choose the industries that apply to the entity, and
answer each metric for each period. Metrics linked to a Sustainability Metric are filled from the entity's data point.
"""
from __future__ import annotations

import io

from velora import get_list, new_doc, throw

INDUSTRY_COLS = ["industry_code", "industry_name", "sector", "standard_version"]
METRIC_COLS = ["metric_code", "industry_code", "topic", "metric_name", "metric_category", "unit_of_measure", "linked_metric_code"]
CATEGORIES = {"Quantitative", "Discussion and analysis", "Activity metric"}


def template_workbook() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active; ws.title = "Industries"; ws.append(INDUSTRY_COLS)
    ws2 = wb.create_sheet("Metrics"); ws2.append(METRIC_COLS)
    ws3 = wb.create_sheet("Read me")
    for line in ["Fill Industries and Metrics from the SASB Standard you are licensed to use. Nothing is pre-loaded.",
                 "metric_category: Quantitative, Discussion and analysis, or Activity metric.",
                 "linked_metric_code (optional): the metric_code of one of your Sustainability Metrics; its data point then fills the response.",
                 "Re-importing the same codes updates the rows; it never deletes."]:
        ws3.append([line])
    for sheet in (ws, ws2):
        for c in sheet[1]:
            c.font = Font(bold=True)
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


def _rows(ws, cols):
    it = ws.iter_rows(values_only=True)
    head = [str(h or "").strip() for h in next(it, [])]
    missing = [c for c in cols if c not in head and c not in ("sector", "standard_version", "topic", "unit_of_measure", "linked_metric_code", "metric_category")]
    if missing:
        throw(f"Sheet '{ws.title}' is missing column(s): {', '.join(missing)}.")
    for i, r in enumerate(it, start=2):
        d = {h: ("" if v is None else str(v).strip()) for h, v in zip(head, r)}
        if any(d.values()):
            yield i, d


def import_workbook(data: bytes) -> dict:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        throw("That file is not a readable Excel workbook (.xlsx).")
    for need in ("Industries", "Metrics"):
        if need not in wb.sheetnames:
            throw(f"The workbook needs a sheet named '{need}'. Use the template.")
    res = {"industries_created": 0, "industries_updated": 0, "metrics_created": 0, "metrics_updated": 0, "errors": []}
    inds = {r["industry_code"]: r["name"] for r in get_list("SASB Industry", fields=["name", "industry_code"], limit=100000, ignore_permissions=True)}
    for i, d in _rows(wb["Industries"], INDUSTRY_COLS):
        if not d.get("industry_code") or not d.get("industry_name"):
            res["errors"].append(f"Industries row {i}: industry_code and industry_name are required."); continue
        vals = {k: d.get(k, "") for k in ("industry_name", "sector", "standard_version")}
        if d["industry_code"] in inds:
            doc = __import__("velora").get_doc("SASB Industry", inds[d["industry_code"]], ignore_permissions=True)
            doc.update(vals); doc.save(ignore_permissions=True); res["industries_updated"] += 1
        else:
            doc = new_doc("SASB Industry", industry_code=d["industry_code"], active=1, **vals).insert(ignore_permissions=True)
            inds[d["industry_code"]] = doc.name; res["industries_created"] += 1
    mets = {r["metric_code"]: r["name"] for r in get_list("SASB Metric", fields=["name", "metric_code"], limit=100000, ignore_permissions=True)}
    own = {r["metric_code"]: r["name"] for r in get_list("Sustainability Metric", fields=["name", "metric_code"], limit=100000, ignore_permissions=True)}
    for i, d in _rows(wb["Metrics"], METRIC_COLS):
        if not d.get("metric_code") or not d.get("metric_name") or not d.get("industry_code"):
            res["errors"].append(f"Metrics row {i}: metric_code, industry_code and metric_name are required."); continue
        if d["industry_code"] not in inds:
            res["errors"].append(f"Metrics row {i} ({d['metric_code']}): industry '{d['industry_code']}' is not in the Industries sheet or the system."); continue
        cat = d.get("metric_category") or "Quantitative"
        if cat not in CATEGORIES:
            res["errors"].append(f"Metrics row {i} ({d['metric_code']}): category must be one of {', '.join(sorted(CATEGORIES))}."); continue
        link = d.get("linked_metric_code") or ""
        if link and link not in own:
            res["errors"].append(f"Metrics row {i} ({d['metric_code']}): linked metric '{link}' is not a Sustainability Metric."); continue
        vals = dict(industry=inds[d["industry_code"]], topic=d.get("topic", ""), metric_name=d["metric_name"], metric_category=cat, unit_of_measure=d.get("unit_of_measure", ""), source_metric=own.get(link))
        if d["metric_code"] in mets:
            doc = __import__("velora").get_doc("SASB Metric", mets[d["metric_code"]], ignore_permissions=True)
            doc.update(vals); doc.save(ignore_permissions=True); res["metrics_updated"] += 1
        else:
            doc = new_doc("SASB Metric", metric_code=d["metric_code"], active=1, **vals).insert(ignore_permissions=True)
            mets[d["metric_code"]] = doc.name; res["metrics_created"] += 1
    return res


def generate_responses(entity, period_name) -> dict:
    """One response per active metric of each industry the entity has adopted. Existing responses are kept; data points fill linked metrics."""
    adopted = [a["industry"] for a in get_list("SASB Adoption", filters=[["governance_entity", "=", entity], ["active", "=", 1]], fields=["industry"], limit=1000, ignore_permissions=True)]
    if not adopted:
        throw("Record which SASB industries apply to this entity (SASB Adoption) first.")
    have = {r["sasb_metric"] for r in get_list("SASB Metric Response", filters=[["governance_entity", "=", entity], ["reporting_period", "=", period_name]], fields=["sasb_metric"], limit=100000, ignore_permissions=True)}
    created = filled = 0
    for ind in adopted:
        for m in get_list("SASB Metric", filters=[["industry", "=", ind], ["active", "=", 1]], fields=["name", "source_metric"], limit=100000, ignore_permissions=True):
            if m["name"] in have:
                continue
            vals = dict(governance_entity=entity, reporting_period=period_name, sasb_metric=m["name"], response_status="Not started")
            if m.get("source_metric"):
                dp = [d for d in get_list("Sustainability Data Point", filters=[["governance_entity", "=", entity], ["metric", "=", m["source_metric"]], ["reporting_period", "=", period_name]],
                                          fields=["name", "value", "verification_status"], limit=5, ignore_permissions=True) if d.get("verification_status") != "Rejected" and d.get("value") is not None]
                if dp:
                    vals.update(data_point=dp[0]["name"], value=dp[0]["value"], response_status="Reported"); filled += 1
            new_doc("SASB Metric Response", **vals).insert(ignore_permissions=True)
            created += 1
    return {"created": created, "filled_from_data_points": filled, "industries": len(adopted)}


def summary(entity, period_name) -> dict:
    rows = get_list("SASB Metric Response", filters=[["governance_entity", "=", entity], ["reporting_period", "=", period_name]], fields=["response_status", "industry"], limit=100000, ignore_permissions=True)
    c = {"Not started": 0, "Reported": 0, "Omitted": 0, "Not applicable": 0}
    for r in rows:
        c[r["response_status"] or "Not started"] = c.get(r["response_status"] or "Not started", 0) + 1
    answered = c["Reported"] + c["Omitted"] + c["Not applicable"]
    return {"total": len(rows), **c, "answered_percent": round(100.0 * answered / len(rows), 1) if rows else 0.0}


def signal(entity, period_name):
    """(ok, detail) for the IFRS S2.32 industry-based metrics requirement."""
    s = summary(entity, period_name)
    if not s["total"]:
        return False, "No SASB metric responses for this period (adopt an industry, then generate responses)"
    if s["Not started"]:
        return False, f"{s['Not started']} of {s['total']} SASB metrics still not answered"
    return True, f"All {s['total']} SASB metrics answered ({s['Reported']} reported, {s['Omitted']} omitted, {s['Not applicable']} not applicable)"
