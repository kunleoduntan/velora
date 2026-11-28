"""Append-only governance exception activity helpers."""
import hashlib
from datetime import datetime


def activity_key(exception_name, activity_type, actor=None, details=None, evidence_reference=None, source_key=None):
    material = "|".join(str(x or "") for x in (exception_name, activity_type, actor, details, evidence_reference, source_key))
    return "GEA-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def append_activity(exception_name, activity_type, *, actor=None, details=None, evidence_reference=None,
                   source_key=None, api=None, now=None):
    """Append idempotent activity; API can be injected for deterministic tests."""
    if api is None:
        from velora_governance.runtime import host as api
    key = activity_key(exception_name, activity_type, actor, details, evidence_reference, source_key)
    existing = api.get_list("Governance Exception Activity", filters={"idempotency_key": key},
                           fields=["name"], limit_page_length=1)
    if existing:
        return {"name": existing[0]["name"], "created": False}
    doc = api.get_doc({"doctype": "Governance Exception Activity", "exception": exception_name,
        "activity_type": activity_type, "actor": actor, "details": details,
        "evidence_reference": evidence_reference, "idempotency_key": key,
        "activity_datetime": now or datetime.now()})
    doc.insert(ignore_permissions=True)
    return {"name": doc.name, "created": True}
