"""Tenant-scoped persistence facade for core ProjectOne business documents.

The facade maps stable ProjectOne DocType names to the injected Velora document
engine. All persistence, permission checks, audit events and idempotency are
performed through host ports; no local fallback repository is provided.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any

from .host_contracts import AuthenticatedActor

# Explicit allowlist: no caller-controlled DocType names reach the host engine.
CORE_DOCUMENTS = {
    "Project": {"permission": "projectone.project", "project_link": None},
    "Project Portfolio": {"permission": "projectone.portfolio", "project_link": None},
    "Project Programme": {"permission": "projectone.programme", "project_link": None},
    "Project Task": {"permission": "projectone.task", "project_link": "project"},
    "Task Dependency": {"permission": "projectone.task_dependency", "project_link": "project"},
    "Resource Calendar": {"permission": "projectone.resource_calendar", "project_link": None},
    "Resource Profile": {"permission": "projectone.resource_profile", "project_link": None},
    "Resource Availability Exception": {"permission": "projectone.resource_availability_exception", "project_link": None},
    "Project Resource Allocation": {"permission": "projectone.resource_allocation", "project_link": "project"},
    "Project WBS": {"permission": "projectone.wbs", "project_link": "project"},
    "Project Milestone": {"permission": "projectone.milestone", "project_link": "project"},
    "Project Baseline": {"permission": "projectone.baseline", "project_link": "project"},
    "Project Risk": {"permission": "projectone.risk", "project_link": "project"},
    "Project Issue": {"permission": "projectone.issue", "project_link": "project"},
    "Project Change Request": {"permission": "projectone.change_request", "project_link": "project"},
    "Project Deliverable": {"permission": "projectone.deliverable", "project_link": "project"},
    "Project Charter": {"permission": "projectone.charter", "project_link": "project"},
    "Project Business Case": {"permission": "projectone.business_case", "project_link": "project"},
    "Project Document Register": {"permission": "projectone.document_register", "project_link": "project"},
    "Project Closure": {"permission": "projectone.closure", "project_link": "project"},
    "Project Meeting": {"permission": "projectone.meeting", "project_link": "project"},
    "Project Stage Gate": {"permission": "projectone.stage_gate", "project_link": "project"},
    "Project Benefit": {"permission": "projectone.benefit", "project_link": "project"},
    "Project Decision Log": {"permission": "projectone.decision_log", "project_link": "project"},
    "Project Performance Obligation": {"permission": "projectone.performance_obligation", "project_link": "project"},
    "Project Revenue Recognition": {"permission": "projectone.revenue_recognition", "project_link": "project"},
    "Project Budget": {"permission": "projectone.budget", "project_link": "project"},
    "Project Quality Inspection": {"permission": "projectone.quality_inspection", "project_link": "project"},
    "Project Sprint": {"permission": "projectone.sprint", "project_link": "project"},
    "Project User Story": {"permission": "projectone.user_story", "project_link": "project"},
    "Project Timesheet": {"permission": "projectone.timesheet", "project_link": "project"},
}

READ_ONLY_DOCUMENTS = {"Resource Profile", "Resource Availability Exception", "Project Budget",
                       "Project Quality Inspection", "Project Sprint", "Project User Story",
                       "Project Timesheet", "Project Benefit"}

# Fields whose values are controlled by the host workflow or governed command
# services. Generic CRUD must never be able to bypass approval or schedule rules.
PROTECTED_FIELDS = {
    "Project": {"status"},
    "Project Portfolio": {"status"},
    "Project Programme": {"status"},
    "Project Task": {"planned_start", "planned_finish", "status"},
    "Project Milestone": {"status"},
    "Project Deliverable": {"status"},
    "Project Risk": {"status"},
    "Project Issue": {"status"},
    "Project Baseline": {"approval_status", "approved_by", "approved_on", "is_current"},
    "Project Change Request": {"approval_status", "requested_by", "schedule_change_payload", "schedule_applied"},
    "Project Charter": {"approval_status", "approved_by", "approved_on"},
    "Project Business Case": {"approval_status", "approved_by", "approved_on"},
    "Project Document Register": {"approval_status", "approved_by", "approved_on"},
    "Project Closure": {"closure_approval", "approved_by", "approved_on"},
    "Project Stage Gate": {"gate_status", "approved_by", "approved_on"},
    "Project Performance Obligation": {"status", "approved_by", "approved_on", "approval_reference"},
    "Project Revenue Recognition": {"approval_status", "approved_by", "approved_on", "approval_reference"},
}
CREATE_PROTECTED_FIELDS = {
    "Project": {"status"}, "Project Portfolio": {"status"},
    "Project Programme": {"status"}, "Project Task": {"status"},
    "Project Milestone": {"status"}, "Project Deliverable": {"status"},
    "Project Risk": {"status"}, "Project Issue": {"status"},
    "Project Baseline": {"approval_status", "approved_by", "approved_on", "is_current"},
    "Project Change Request": {"approval_status", "schedule_change_payload", "schedule_applied"},
    "Project Charter": {"approval_status", "approved_by", "approved_on"},
    "Project Business Case": {"approval_status", "approved_by", "approved_on"},
    "Project Document Register": {"approval_status", "approved_by", "approved_on"},
    "Project Closure": {"closure_approval", "approved_by", "approved_on"},
    "Project Stage Gate": {"gate_status", "approved_by", "approved_on"},
    "Project Performance Obligation": {"status", "approved_by", "approved_on", "approval_reference"},
    "Project Revenue Recognition": {"approval_status", "approved_by", "approved_on", "approval_reference"},
}
TRUSTED_CREATE_FIELDS = {
    "Project Change Request": {"schedule_change_payload", "schedule_applied"},
}
SERVER_COMPUTED_CREATE_FIELDS = {
    "Project Revenue Recognition": {
        "transaction_price", "recognition_method", "recognition_over_time",
        "control_transfer_confirmed", "progress_percent", "cumulative_actual_cost",
        "forecast_total_cost", "prior_cumulative_revenue", "cumulative_revenue",
        "current_period_revenue", "cumulative_cost", "current_period_cost",
        "cumulative_profit", "current_period_profit", "forecast_total_profit",
        "forecast_margin_percent", "potential_onerous_contract_loss", "source_watermark",
    },
}
TRUSTED_CREATE_FIELDS["Project Revenue Recognition"] = SERVER_COMPUTED_CREATE_FIELDS["Project Revenue Recognition"]

INITIAL_STATE_VALUES = {
    (doctype, field): "Draft" for doctype, field in (
        ("Project", "status"), ("Project Portfolio", "status"),
        ("Project Programme", "status"), ("Project Task", "status"),
        ("Project Milestone", "status"), ("Project Deliverable", "status"),
        ("Project Risk", "status"), ("Project Issue", "status"),
        ("Project Baseline", "approval_status"),
        ("Project Change Request", "approval_status"),
        ("Project Charter", "approval_status"), ("Project Business Case", "approval_status"),
        ("Project Document Register", "approval_status"), ("Project Closure", "closure_approval"),
        ("Project Stage Gate", "gate_status"),
        ("Project Performance Obligation", "status"),
        ("Project Revenue Recognition", "approval_status"),
    )
}
INITIAL_STATE_VALUES[("Project Revenue Recognition", "approval_status")] = "Pending Review"



class NativeDocumentRepository:
    """Generic core-document repository that fails closed without host services."""
    def __init__(self, *, document_engine, transaction_manager, authorization,
                 audit_service, idempotency_store):
        self.engine = document_engine
        self.uow = transaction_manager
        self.authorization = authorization
        self.audit = audit_service
        self.idempotency = idempotency_store
        for obj, methods, label in (
            (self.engine, ("get", "list", "insert", "update_if_version"), "document engine"),
            (self.uow, ("transaction",), "transaction manager"),
            (self.authorization, ("assert_permission", "get_permitted_fields"), "authorization service"),
            (self.audit, ("append", "list_for_project"), "audit service"),
            (self.idempotency, ("execute",), "idempotency store"),
        ):
            missing = [m for m in methods if not callable(getattr(obj, m, None))]
            if missing:
                raise TypeError(f"{label} missing: {', '.join(missing)}")

    @staticmethod
    def _actor(actor):
        if not isinstance(actor, AuthenticatedActor):
            raise PermissionError("Trusted Velora actor is required.")
        return actor

    @staticmethod
    def _doctype(doctype):
        if doctype not in CORE_DOCUMENTS:
            raise ValueError("Document type is not enabled for native ProjectOne persistence.")
        return CORE_DOCUMENTS[doctype]

    def _authorize(self, actor, doctype, action, project_id=None):
        cfg = self._doctype(doctype)
        self.authorization.assert_permission(actor, f"{cfg['permission']}.{action}",
                                              company_id=actor.company_id,
                                              project_id=project_id)

    def _permitted_fields(self, actor, doctype, action, project_id=None):
        """Resolve fields from DocField.permlevel and the user's DocType permissions.

        The host adapter must use Frappe-style permission metadata. Field type is
        deliberately irrelevant: Link, Data, Currency, Table and all other field
        types follow the same permlevel calculation.
        """
        fields = self.authorization.get_permitted_fields(
            actor, doctype, action, company_id=actor.company_id,
            project_id=project_id)
        if not isinstance(fields, (set, frozenset)) or any(not isinstance(f, str) for f in fields):
            raise RuntimeError("Permission adapter must return a set of permitted field names.")
        return set(fields)

    def _assert_permlevel_access(self, actor, doctype, fields, action, project_id=None,
                                 trusted_fields=None):
        trusted = set(trusted_fields or ())
        denied = set(fields) - self._permitted_fields(actor, doctype, action, project_id) - trusted
        if denied:
            raise PermissionError("Permission level does not allow access to fields: " + ", ".join(sorted(denied)))

    def _filter_readable_fields(self, actor, doctype, document, project_id=None):
        readable = self._permitted_fields(actor, doctype, "read", project_id)
        # Preserve framework-managed identity fields needed by the UI and audit;
        # actual host adapter should include them only when Frappe permits them.
        return {key: deepcopy(value) for key, value in document.items() if key in readable}

    @staticmethod
    def _audit_anchor(doctype, name, document):
        cfg = CORE_DOCUMENTS[doctype]
        link = cfg["project_link"]
        return (document or {}).get(link) if link else name

    def get_for_workflow(self, actor, doctype, name):
        """Internal raw read for lifecycle validation; never returned to clients."""
        actor = self._actor(actor)
        cfg = self._doctype(doctype)
        self._authorize(actor, doctype, "read", name if doctype == "Project" else None)
        with self.uow.transaction() as session:
            row = self.engine.get(session, doctype, name, actor.company_id)
        if row is None:
            return None
        parent = row.get(cfg["project_link"]) if cfg["project_link"] else None
        if parent:
            self._authorize(actor, doctype, "read", parent)
        return deepcopy(row)

    def get(self, actor, doctype, name):
        actor = self._actor(actor)
        self._authorize(actor, doctype, "read", name if doctype == "Project" else None)
        with self.uow.transaction() as session:
            row = self.engine.get(session, doctype, name, actor.company_id)
        if row is None:
            return None
        cfg = CORE_DOCUMENTS[doctype]
        parent = row.get(cfg["project_link"]) if cfg["project_link"] else None
        if parent and doctype != "Project":
            self._authorize(actor, doctype, "read", parent)
        return self._filter_readable_fields(actor, doctype, row, parent)

    def list(self, actor, doctype, *, filters=None, limit=100, offset=0):
        actor = self._actor(actor)
        self._authorize(actor, doctype, "read")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be zero or greater.")
        safe_filters = filters or {}
        if not isinstance(safe_filters, dict) or len(safe_filters) > 20:
            raise ValueError("filters must be an object containing at most 20 entries.")
        forbidden = {"owner", "creation", "modified", "docstatus"}
        if forbidden.intersection(safe_filters):
            raise ValueError("System fields cannot be supplied as filters.")
        with self.uow.transaction() as session:
            rows = self.engine.list(session, doctype, actor.company_id,
                                    safe_filters, limit, offset)
        cfg = CORE_DOCUMENTS[doctype]
        link = cfg["project_link"]
        if link:
            # Defence in depth; host query must already enforce company scope.
            for row in rows:
                parent = row.get(link)
                if parent:
                    self._authorize(actor, doctype, "read", parent)
        return [self._filter_readable_fields(actor, doctype, row,
                row.get(link) if link else None) for row in rows]

    def insert(self, actor, doctype, document, *, idempotency_key, trusted_fields=None):
        actor = self._actor(actor)
        cfg = self._doctype(doctype)
        if doctype in READ_ONLY_DOCUMENTS:
            raise PermissionError(f"{doctype} is an authoritative read-only resource record.")
        self._authorize(actor, doctype, "create")
        if not isinstance(document, dict) or not document:
            raise ValueError("A non-empty document object is required.")
        safe = deepcopy(document)
        if doctype == "Project Performance Obligation":
            safe.setdefault("status", "Draft")
        if doctype == "Project Revenue Recognition":
            safe.setdefault("approval_status", "Pending Review")
        trusted_fields = trusted_fields or {}
        if not isinstance(trusted_fields, dict):
            raise ValueError("trusted_fields must be an object.")
        computed_supplied = SERVER_COMPUTED_CREATE_FIELDS.get(doctype, set()).intersection(safe)
        if computed_supplied:
            raise ValueError("Calculated financial fields can only be supplied by the trusted recognition service: " + ", ".join(sorted(computed_supplied)))
        protected = CREATE_PROTECTED_FIELDS.get(doctype, set())
        supplied_protected = protected.intersection(safe)
        invalid_initial = {field for field in supplied_protected
                           if safe.get(field) != INITIAL_STATE_VALUES.get((doctype, field))}
        if invalid_initial:
            raise ValueError("Workflow-controlled fields can only be initialised in Draft through generic creation: " + ", ".join(sorted(invalid_initial)))
        if doctype == "Project Revenue Recognition":
            safe["approval_status"] = "Pending Review"
        if doctype == "Project Change Request":
            if safe.get("requested_by") not in (None, actor.actor_id):
                raise PermissionError("requested_by must match the authenticated actor.")
            safe["requested_by"] = actor.actor_id
            safe["approval_status"] = "Draft"
            safe["schedule_applied"] = 0
        trusted_allowed = TRUSTED_CREATE_FIELDS.get(doctype, set())
        if set(trusted_fields) - trusted_allowed:
            raise ValueError("Internal trusted field set contains unsupported fields.")
        if "schedule_applied" in trusted_fields and trusted_fields["schedule_applied"] not in (0, False):
            raise ValueError("A new schedule change request cannot be marked as applied.")
        safe.update(deepcopy(trusted_fields))
        safe.pop("name", None)
        safe.pop("owner", None)
        safe.pop("creation", None)
        safe.pop("modified", None)
        safe.pop("version", None)
        parent = safe.get(cfg["project_link"]) if cfg["project_link"] else None
        if cfg["project_link"] and not parent:
            raise ValueError(f"{doctype} requires a parent project.")
        if parent:
            self._authorize(actor, doctype, "create", parent)
        self._assert_permlevel_access(actor, doctype, set(safe), "create", parent,
                                       trusted_fields=set(trusted_fields))
        digest = sha256(json.dumps({"doctype": doctype, "document": safe}, sort_keys=True,
                                   default=str, separators=(",", ":")).encode()).hexdigest()
        if not idempotency_key or len(str(idempotency_key)) > 128:
            raise ValueError("A valid idempotency key (1-128 characters) is required.")
        with self.uow.transaction() as session:
            def operation():
                saved = self.engine.insert(session, doctype, safe, actor.actor_id)
                anchor = self._audit_anchor(doctype, saved.get("name"), saved)
                self.audit.append(session, company_id=actor.company_id,
                                  project_id=anchor, actor_id=actor.actor_id,
                                  action=f"{doctype.lower().replace(' ', '_')}.created",
                                  before=None, after=saved)
                return saved
            result = self.idempotency.execute(session, actor.company_id,
                                              f"projectone:{doctype}:{idempotency_key}", digest,
                                              operation)
        return deepcopy(result)

    def update(self, actor, doctype, name, document, *, expected_version):
        actor = self._actor(actor)
        cfg = self._doctype(doctype)
        if doctype in READ_ONLY_DOCUMENTS:
            raise PermissionError(f"{doctype} is an authoritative read-only resource record.")
        self._authorize(actor, doctype, "update", name if doctype == "Project" else None)
        if not isinstance(document, dict):
            raise ValueError("Document must be an object.")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
            raise ValueError("A positive expected_version is required.")
        with self.uow.transaction() as session:
            before = self.engine.get(session, doctype, name, actor.company_id)
            if before is None:
                raise KeyError(name)
            parent = before.get(cfg["project_link"]) if cfg["project_link"] else None
            if cfg["project_link"] and not parent:
                raise ValueError(f"Existing {doctype} has no parent project; repair it before updating.")
            if parent:
                self._authorize(actor, doctype, "update", parent)
            if before.get("version") != expected_version:
                from ..services.persistence import VersionConflict
                raise VersionConflict("Document changed; reload before updating.")
            state_fields = {
                "Project": "status", "Project Portfolio": "status", "Project Programme": "status",
                "Project Task": "status", "Project Milestone": "status", "Project Deliverable": "status",
                "Project Risk": "status", "Project Issue": "status", "Project Baseline": "approval_status",
                "Project Change Request": "approval_status", "Project Charter": "approval_status",
                "Project Business Case": "approval_status", "Project Document Register": "approval_status",
                "Project Closure": "closure_approval", "Project Stage Gate": "gate_status",
                "Project Performance Obligation": "status",
                "Project Revenue Recognition": "approval_status",
            }
            state_field = state_fields.get(doctype)
            if state_field and before.get(state_field) not in (None, "Draft"):
                raise ValueError(f"{doctype} is no longer editable through generic update after leaving Draft; use the governed workflow or amendment process.")
            safe = deepcopy(document)
            protected = PROTECTED_FIELDS.get(doctype, set()).intersection(safe)
            if protected:
                raise ValueError("Workflow-controlled fields cannot be changed through generic document update: " + ", ".join(sorted(protected)))
            safe.pop("name", None)
            safe.pop("owner", None)
            safe.pop("creation", None)
            safe.pop("modified", None)
            safe.pop("version", None)
            if cfg["project_link"] and safe.get(cfg["project_link"], parent) != parent:
                raise ValueError("A child document cannot be moved to another project by a generic update.")
            self._assert_permlevel_access(actor, doctype, set(safe), "write", parent)
            saved = self.engine.update_if_version(session, doctype, name,
                       actor.company_id, safe, expected_version, actor.actor_id)
            anchor = self._audit_anchor(doctype, name, saved)
            self.audit.append(session, company_id=actor.company_id,
                              project_id=anchor, actor_id=actor.actor_id,
                              action=f"{doctype.lower().replace(' ', '_')}.updated",
                              before=before, after=saved)
        return deepcopy(saved)
