"""Persistence helpers for Governance Exception using native Frappe documents."""
import hashlib
from velora_governance.governance.services.governance_exception_centre import classify_exception, route_exception, transition_exception

ALLOWED_SOURCE_DOCTYPES = {
    "Board Action", "Governance Obligation", "Corporate Filing", "Annual Return",
    "Regulatory Correspondence", "Sustainability Data Collection Task"
}

def exception_key(source_doctype, source_name, exception_type):
    raw = "|".join([str(source_doctype), str(source_name), str(exception_type)])
    return "GEX-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def normalize_exception_payload(payload, routing_config=None, configuration=None):
    payload = dict(payload or {})
    source_doctype = str(payload.get("source_doctype") or "").strip()
    source_name = str(payload.get("source_name") or "").strip()
    exception_type = str(payload.get("exception_type") or "Governance Exception").strip()
    title = str(payload.get("title") or "").strip()
    if source_doctype not in ALLOWED_SOURCE_DOCTYPES:
        return {"valid": False, "errors": ["source_doctype_not_allowed"]}
    if not source_name or not title:
        return {"valid": False, "errors": ["source_name_and_title_required"]}
    if configuration:
        from velora_governance.governance.services.governance_exception_configuration import classify_with_configuration
        classification = classify_with_configuration(due_date=payload.get("due_date"), risk_score=payload.get("risk_score"), exception_type=exception_type, configuration=configuration)
        routing_config = routing_config or configuration.get("routes")
    else:
        classification = classify_exception(due_date=payload.get("due_date"), risk_score=payload.get("risk_score"), exception_type=exception_type)
    routing = route_exception(severity=classification["severity"], routing_config=routing_config)
    return {"valid": True, "normalized": {
        "idempotency_key": exception_key(source_doctype, source_name, exception_type),
        "source_doctype": source_doctype, "source_name": source_name,
        "exception_type": exception_type, "title": title,
        "description": str(payload.get("description") or ""),
        "due_date": payload.get("due_date"), "risk_score": payload.get("risk_score"),
        "severity": classification["severity"], "overdue_days": classification["overdue_days"],
        "route": routing["route"],
        "routing_status": "Configured" if routing["routing_status"] == "configured" else "Unconfigured"
    }}


def upsert_exception(payload, *, frappe_api, routing_config=None, configuration=None):
    """Create or refresh an exception idempotently; caller must enforce permissions."""
    result = normalize_exception_payload(payload, routing_config=routing_config, configuration=configuration)
    if not result["valid"]:
        raise ValueError("; ".join(result["errors"]))
    values = result["normalized"]
    matches = frappe_api.get_list("Governance Exception", filters={"idempotency_key": values["idempotency_key"]},
                                fields=["name"], limit_page_length=1)
    if matches:
        doc = frappe_api.get_doc("Governance Exception", matches[0]["name"])
        # Preserve lifecycle/assignment; refresh only source-derived intelligence.
        for field in ("title", "description", "due_date", "risk_score", "severity", "overdue_days", "route", "routing_status"):
            setattr(doc, field, values[field])
        doc.save(ignore_permissions=False)
        return {"name": doc.name, "created": False, "severity": doc.severity, "status": doc.status}
    doc = frappe_api.get_doc({"doctype": "Governance Exception", **values, "status": "Open"})
    doc.insert(ignore_permissions=False)
    return {"name": doc.name, "created": True, "severity": doc.severity, "status": doc.status}


def transition_persisted_exception(doc, target, *, actor=None, evidence=None, evidence_required=True, now=None):
    result = transition_exception(doc.status, target, actor=actor, evidence=evidence, evidence_required=evidence_required)
    if not result["valid"]:
        raise ValueError(result["reason"])
    doc.status = target
    if target in ("Resolved", "Closed"):
        doc.resolution_evidence = str(evidence or "").strip()
    if target == "Resolved":
        doc.resolved_by = actor
        doc.resolved_on = now
    if target == "Closed":
        doc.closed_by = actor
        doc.closed_on = now
    doc.save(ignore_permissions=False)
    return {"name": doc.name, "status": target}
