"""Framework persistence orchestration for sustainability reporting.

The pure reporting services remain responsible for deterministic calculations.
This adapter performs permission-aware framework reads/writes and keeps the
orchestration transaction bounded to one reporting period/run.
"""
from __future__ import annotations

from datetime import datetime

from .sustainability_reporting import (
    build_disclosure_data_requirements,
    create_collection_task_specs,
    assemble_report_package,
)

TASK_DOCTYPE = "Sustainability Data Collection Task"
ASSESSMENT_DOCTYPE = "Sustainability Disclosure Assessment"
RUN_DOCTYPE = "Sustainability Reporting Run"
CONTENT_DOCTYPE = "Sustainability Report Content Block"
LOG_DOCTYPE = "Sustainability Report Generation Log"


def _frappe():
    from velora_governance.runtime import host
    return host


def _get_records(frappe, doctype, filters, fields=None):
    fields = fields or ["name"]
    return frappe.get_list(doctype, filters=filters, fields=fields, limit_page_length=0)


def _framework_names(period_doc):
    names = []
    table = getattr(period_doc, "frameworks", None) or []
    for row in table:
        value = row.get("framework") if hasattr(row, "get") else getattr(row, "framework", None)
        if value and value not in names:
            names.append(value)
    return names


def _disclosures_for_period(frappe, period_doc, framework_names):
    rows = []
    for framework in framework_names:
        rows.extend(_get_records(frappe, "Sustainability Disclosure", {"framework": framework, "active": 1},
            ["name", "disclosure_code", "disclosure_title", "required_data", "guidance", "framework", "data_points_required", "evidence_required", "narrative_required"]))
    # Preserve order and remove duplicates when multiple standards map to a disclosure.
    seen = set(); unique = []
    for row in rows:
        key = row.get("name")
        if key not in seen:
            seen.add(key)
            row["disclosure"] = key
            row["disclosure_title"] = row.get("disclosure_title") or row.get("disclosure_code") or key
            # Required-data text is guidance, not a structured quantity. Default to
            # zero unless a future schema supplies an explicit count field.
            row["data_points_required"] = int(row.get("data_points_required") or 0)
            row["evidence_required"] = bool(row.get("evidence_required", 0))
            row["narrative_required"] = bool(row.get("narrative_required", 1))
            row["applicable"] = True
            unique.append(row)
    return unique


def _get_source_records(frappe, period_doc, disclosure_names):
    filters = {"reporting_period": period_doc.period_name}
    data_points = _get_records(frappe, "Sustainability Data Point", filters,
        ["name", "disclosure", "verification_status", "metric", "value", "unit", "data_date"])
    evidence = _get_records(frappe, "Sustainability Evidence", {"reporting_period": period_doc.name},
        ["name", "disclosure", "verified", "evidence_type", "document_reference"])
    # Source records can be disclosure-linked; period-only records are retained
    # and the pure service ignores unmatched disclosure references.
    return data_points, evidence


def _ensure_collection_tasks(frappe, period_doc, requirements):
    period_key = period_doc.name
    existing = _get_records(frappe, TASK_DOCTYPE, {"reporting_period": period_key}, ["name", "task_key"])
    existing_keys = {r.get("task_key") for r in existing if r.get("task_key")}
    specs = create_collection_task_specs(reporting_period=period_key,
        disclosure_requirements=requirements, existing_task_keys=existing_keys)
    created = 0
    for spec in specs:
        doc = frappe.get_doc({"doctype": TASK_DOCTYPE, **spec,
            "governance_entity": period_doc.governance_entity,
            "reporting_period": period_key,
            "responsible_owner": getattr(period_doc, "owner", None),
            "due_date": getattr(period_doc, "period_end", None)})
        doc.insert(ignore_permissions=False)
        created += 1
    return created


def _upsert_assessments(frappe, period_doc, assessments):
    created = updated = 0
    for row in assessments:
        filters = {"reporting_period": period_doc.name, "disclosure": row["disclosure"]}
        found = frappe.get_all(ASSESSMENT_DOCTYPE, filters=filters, fields=["name"], limit=1)
        payload = {"governance_entity": period_doc.governance_entity,
            "reporting_period": period_doc.name, "disclosure": row["disclosure"],
            "applicable": row["applicable"], "assessment_status": row["assessment_status"],
            "readiness_percent": row["readiness_percent"],
            "data_points_required": row.get("data_points_required", 0),
            "data_points_complete": row.get("complete_data_points", 0),
            "evidence_required": row.get("evidence_required", 0),
            "evidence_complete": row.get("evidence_complete", 0),
            "narrative_required": row.get("narrative_required", 0),
            "narrative_complete": row.get("narrative_complete", 0),
            "gap_summary": row.get("gap_summary", "")}
        if found:
            doc = frappe.get_doc(ASSESSMENT_DOCTYPE, found[0]["name"])
            for field, value in payload.items():
                doc.set(field, value)
            doc.save(ignore_permissions=False)
            updated += 1
        else:
            frappe.get_doc({"doctype": ASSESSMENT_DOCTYPE, **payload}).insert(ignore_permissions=False)
            created += 1
    return created, updated


def _upsert_content_blocks(frappe, period_doc, report_doc, blocks, framework_names):
    created = updated = 0
    for block in blocks:
        filters = {"reporting_period": period_doc.name, "block_type": block["block_type"],
                  "title": block.get("title") or "", "sequence": block["sequence"]}
        found = frappe.get_all(CONTENT_DOCTYPE, filters=filters, fields=["name"], limit=1)
        payload = {"report": report_doc.name if report_doc else None,
            "reporting_period": period_doc.name, "framework": framework_names[0] if framework_names else None,
            "disclosure": block.get("disclosure"), "sequence": block["sequence"],
            "block_type": block["block_type"], "title": block.get("title"),
            "generated_content": block.get("generated_content", ""),
            "content_status": "Generated", "last_generated": datetime.now()}
        if found:
            doc = frappe.get_doc(CONTENT_DOCTYPE, found[0]["name"])
            for field, value in payload.items():
                doc.set(field, value)
            doc.save(ignore_permissions=False); updated += 1
        else:
            frappe.get_doc({"doctype": CONTENT_DOCTYPE, **payload}).insert(ignore_permissions=False); created += 1
    return created, updated



def orchestrate_and_persist(reporting_period_name):
    """Create/update assessment, collection tasks, report content, and run log.

    Caller must be authenticated and authorized to manage the selected period.
    Writes are performed through the framework document API so permissions,
    validations, naming, and audit hooks are retained.
    """
    frappe = _frappe()
    period = frappe.get_doc("Sustainability Reporting Period", reporting_period_name)
    period.check_permission("write")
    frameworks = _framework_names(period)
    disclosures = _disclosures_for_period(frappe, period, frameworks)
    data_points, evidence = _get_source_records(frappe, period, {d["name"] for d in disclosures})
    requirements = build_disclosure_data_requirements(disclosures)
    task_created = _ensure_collection_tasks(frappe, period, requirements)
    report = frappe.get_doc("Sustainability Report", period.report) if getattr(period, "report", None) else None
    package = assemble_report_package(entity_name=period.governance_entity,
        period_name=period.period_name, frameworks=frameworks, disclosure_rows=disclosures,
        datapoints=data_points, evidence=evidence, narratives={})
    assessment_created, assessment_updated = _upsert_assessments(frappe, period, package["disclosure_assessments"])
    content_created, content_updated = _upsert_content_blocks(frappe, period, report,
        package["content_blocks"], frameworks)
    run = frappe.get_doc({"doctype": RUN_DOCTYPE,
        "governance_entity": period.governance_entity,
        "reporting_period": period.name,
        "sustainability_report": report.name if report else None,
        "run_status": "Completed" if package["report_status"] == "Ready for Review" else "Completed with Gaps", "frameworks": frameworks,
        "disclosure_assessments": package["disclosure_assessments"],
        "readiness_percent": package["summary"]["readiness_percent"],
        "disclosures_ready": package["summary"]["ready"],
        "disclosures_with_gaps": package["summary"]["not_ready"],
        "missing_disclosures": package["summary"]["missing_disclosures"],
        "content_blocks_generated": len(package["content_blocks"]),
        "generated_at": datetime.now()})
    run.insert(ignore_permissions=False)
    log = frappe.get_doc({"doctype": LOG_DOCTYPE,
        "report": report.name if report else None, "reporting_period": period.name,
        "generation_type": "Full Report Refresh", "started_at": datetime.now(),
        "completed_at": datetime.now(), "result": "Success",
        "disclosures_assessed": package["summary"]["total_disclosures"],
        "disclosures_ready": package["summary"]["ready"],
        "gaps_found": package["summary"]["not_ready"],
        "generated_blocks": len(package["content_blocks"]),
        "summary": f"Reporting run completed. {task_created} tasks created; {assessment_created} assessments created, {assessment_updated} updated; {content_created} blocks created, {content_updated} updated."})
    log.insert(ignore_permissions=False)
    frappe.db.commit()
    return {"run": run.name, "reporting_period": period.name,
        "readiness_percent": package["summary"]["readiness_percent"],
        "disclosures_ready": package["summary"]["ready"],
        "disclosures_with_gaps": package["summary"]["not_ready"],
        "collection_tasks_created": task_created,
        "assessments_created": assessment_created, "assessments_updated": assessment_updated,
        "content_blocks_created": content_created, "content_blocks_updated": content_updated,
        "report_status": package["report_status"]}


def run_reporting_period(reporting_period_name):
    """Whitelisted API entry point for users with reporting-period write access."""
    frappe = _frappe()
    try:
        from frappe import whitelist  # type: ignore
        # Decorator is applied dynamically to avoid import dependency in test envs.
    except ImportError:
        whitelist = None
    return orchestrate_and_persist(reporting_period_name)
