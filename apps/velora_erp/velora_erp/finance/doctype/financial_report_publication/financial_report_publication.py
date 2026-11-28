from datetime import datetime, timezone
import hashlib
import json

from velora import Document, db, throw
from velora.permissions import get_session
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, approval_required

INPUT_FIELDS = (
    "report_layout", "from_date", "to_date", "as_of_date", "budget_name",
    "cost_centre", "branch", "business_unit", "project", "department",
)


def _snapshot_payload(doc):
    from velora.reporting.layouts import get_layout, execute_statement
    layout = get_layout(doc.report_layout)
    filters = {field: getattr(doc, field, None) for field in INPUT_FIELDS if field != "report_layout" and getattr(doc, field, None) not in (None, "")}
    result = execute_statement(layout["definition"], filters)
    result["name"] = layout["name"]
    return {
        "schema_version": 1,
        "layout_id": layout["id"],
        "layout_name": layout["name"],
        "layout_definition": layout["definition"],
        "filters": filters,
        "result": result,
    }


def _canonical_hash(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), raw


class FinancialReportPublication(Document):
    """Generate once, independently approve, then publish an immutable financial statement."""

    def validate(self):
        validate_approval_transition(self)
        if not self.report_layout:
            throw("Select a saved Financial Report Layout.")
        if self.from_date and self.to_date and str(self.from_date) > str(self.to_date):
            throw("From Date cannot be later than To Date.")

        old = getattr(self, "_old", None) or {}
        if not old or not old.get("report_snapshot"):
            payload = _snapshot_payload(self)
            digest, raw = _canonical_hash(payload)
            self.report_snapshot = raw
            self.snapshot_hash = digest
            self.report_title = payload["layout_name"]
            self.generated_by = get_session().user
            self.generated_on = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            # Once generated, the report definition, parameters and system-generated snapshot metadata are immutable.
            changed = [field for field in INPUT_FIELDS if getattr(self, field, None) != old.get(field)]
            protected = [field for field in ("report_title", "report_snapshot", "snapshot_hash", "generated_by", "generated_on")
                         if getattr(self, field, None) != old.get(field)]
            if changed:
                throw("A generated financial report snapshot cannot be changed. Create a new publication for revised parameters: " + ", ".join(changed))
            if protected:
                throw("System-generated report snapshot fields cannot be changed: " + ", ".join(protected))
            if approval_required(self.doctype) and old.get("approval_status") == "Approved" and self.approval_status == "Approved" and self.review_notes != old.get("review_notes"):
                throw("Review Notes are locked after approval. Reset approval before making a change.")
            try:
                payload = json.loads(self.report_snapshot or "{}")
            except (TypeError, ValueError):
                throw("The financial report snapshot is not valid JSON.")
            digest, _ = _canonical_hash(payload)
            if digest != self.snapshot_hash or old.get("snapshot_hash") != self.snapshot_hash:
                throw("The financial report snapshot has been altered. Its immutable fingerprint does not match.")

        if self.approval_status == "Approved":
            expected, _ = _canonical_hash(json.loads(self.report_snapshot))
            if self.approval_hash and self.approval_hash != expected:
                throw("The approved report snapshot fingerprint does not match its content.")
            if not old or old.get("approval_status") != "Approved":
                self.approval_hash = expected
        else:
            self.approval_hash = None

        if self.approval_status == "Approved":
            self.publication_status = "Approved"
        elif self.approval_status == "Rejected":
            self.publication_status = "Rejected"
        else:
            self.publication_status = "Draft"

    def before_submit(self):
        ensure_approved(self, required=True)
        try:
            payload = json.loads(self.report_snapshot or "{}")
        except (TypeError, ValueError):
            throw("A valid generated report snapshot is required before publication.")
        digest, _ = _canonical_hash(payload)
        if digest != self.snapshot_hash or digest != self.approval_hash:
            throw("The report snapshot changed after approval. Reset approval and create a new publication.")

    def on_submit(self):
        db_update(self, publication_status="Published")

def before_delete(self):
        if self.docstatus == 1:
            throw("A published financial report is retained permanently for audit.")
