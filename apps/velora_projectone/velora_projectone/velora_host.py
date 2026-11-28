"""Binds ProjectOne to Velora itself: documents, permissions, transactions, audit, idempotency, workflow and source data.

ProjectOne's services are written against small ports (see ``projectone/integrations``). This module is the one place
that connects those ports to the framework, so every read and write goes through Velora's own permission, field-access,
row-policy and link checks under the signed-in user's session; ProjectOne keeps no second database and no second set of rules.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

from velora import db, get_doc, get_list, new_doc, registry
from velora.exceptions import DoesNotExistError, PermissionDenied, ValidationError
from velora.permissions import field_access, get_session, has_permission

from .host_programmes import VeloraProgrammeData, submit_intervention
from .projectone.integrations.host_contracts import AuthenticatedActor
from .projectone.integrations.native_bridge import (
    NativeIntegrationCapabilities, NativeVeloraBridge, native_integration_registry)
from .projectone.integrations.native_documents import CORE_DOCUMENTS
from .projectone.services.persistence import VersionConflict

# Velora keeps one database per site, so ProjectOne's "scope" is a fixed label and is never stored on a record.
SCOPE = "site"
SYSTEM_FIELDS = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "version"}
MANAGER_ROLES = {"System Manager", "Project Manager"}

_BY_KEY = {cfg["permission"].split(".", 1)[1]: doctype for doctype, cfg in CORE_DOCUMENTS.items()}
_ACTION_TO_PTYPE = {"read": "read", "create": "create", "update": "write", "delete": "delete"}


def _version(modified) -> int:
    if isinstance(modified, datetime):
        return int(modified.timestamp() * 1_000_000)
    return int(hashlib.sha1(str(modified).encode()).hexdigest()[:12], 16)


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return float(value) if isinstance(value, Decimal) else value


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _json_safe(value):
    return json.loads(json.dumps(value, default=_json_default)) if value is not None else None


def _row(values: dict) -> dict:
    out = {k: _plain(v) for k, v in values.items()}
    out["version"] = _version(values.get("modified"))
    return out


def _snake(doctype: str) -> str:
    return doctype.lower().replace(" ", "_")


class VeloraDocuments:
    """Document engine port. Velora enforces permissions, field access, row policies and links on every call."""

    def get(self, session, doctype, name, company):
        try:
            return _row(get_doc(doctype, name).as_dict())
        except DoesNotExistError:
            return None

    def list(self, session, doctype, company, filters, limit, offset):
        meta = registry.get(doctype)
        fields = ["name", "owner", "creation", "modified"] + [
            f.fieldname for f in meta.value_fields if field_access(doctype, f.fieldname) != "hidden"]
        flt = [[k, "=", v] for k, v in (filters or {}).items()]
        rows = get_list(doctype, filters=flt, fields=list(dict.fromkeys(fields)), order_by="modified desc",
                        limit=limit, offset=offset)
        return [_row(r) for r in rows]

    def insert(self, session, doctype, document, actor_id):
        values = {k: v for k, v in document.items() if k not in SYSTEM_FIELDS}
        return _row(new_doc(doctype, **values).insert().as_dict())

    def update_if_version(self, session, doctype, name, company, document, expected_version, actor_id):
        doc = get_doc(doctype, name)
        if _version(doc.get("modified")) != expected_version:
            raise VersionConflict(f"{doctype} {name} was changed by someone else; reload and try again.")
        for key, value in document.items():
            if key not in SYSTEM_FIELDS:
                doc.set(key, value)
        doc.save()
        return _row(doc.as_dict())


class VeloraTransactions:
    def transaction(self):
        return db.transaction()


class VeloraAuthorization:
    """Maps ProjectOne permission names onto Velora DocPerm rows and field access."""

    @staticmethod
    def _doctype_for(permission: str):
        parts = permission.split(".")
        if parts[0] == "projectone" and len(parts) >= 2 and parts[1] in _BY_KEY:
            return _BY_KEY[parts[1]], (parts[2] if len(parts) > 2 else "read")
        for doctype in CORE_DOCUMENTS:
            if _snake(doctype) == parts[0]:
                return doctype, ".".join(parts[1:])
        return None, None

    def assert_permission(self, actor, permission, *, company_id, project_id=None):
        doctype, action = self._doctype_for(permission)
        if doctype is None:
            if permission.startswith("projectone.workflow.inbox") or permission.endswith(".audit.read"):
                doctype, action = "Project", "read"
            elif get_session().roles & MANAGER_ROLES:
                return
            else:
                raise PermissionDenied(f"You may not do this: {permission}")
        ptype = _ACTION_TO_PTYPE.get(action, "write")
        if not has_permission(registry.get(doctype), ptype):
            raise PermissionDenied(f"You may not {ptype} {doctype}")

    def get_permitted_fields(self, actor, doctype, action, *, company_id, project_id=None):
        meta = registry.get(doctype)
        writing = action in ("create", "update")
        names = set(SYSTEM_FIELDS)
        for f in meta.value_fields:
            access = field_access(doctype, f.fieldname, None, "write" if writing else "read")
            if access == "editable" or (not writing and access != "hidden"):
                names.add(f.fieldname)
        return names


class VeloraAudit:
    def append(self, session, *, company_id, project_id, actor_id, action, before, after):
        new_doc("Project Audit Event", project=str(project_id), action=action, actor=actor_id,
                before=_json_safe(before), after=_json_safe(after)).insert(ignore_permissions=True)

    def list_for_project(self, session, project_id, company_id, *, limit):
        rows = get_list("Project Audit Event", filters=[["project", "=", str(project_id)]],
                        fields=["name", "project", "action", "actor", "before", "after", "creation"],
                        order_by="creation desc", limit=limit)
        return [{"project_id": r["project"], "action": r["action"], "actor_id": r["actor"], "before": r["before"],
                 "after": r["after"], "occurred_at": _plain(r["creation"])} for r in rows]


class VeloraIdempotency:
    """A repeated request with the same key returns the first answer; the same key with other content is refused."""

    def execute(self, session, company, key, request_hash, operation):
        existing = get_list("Project Request Key", filters=[["request_key", "=", key]],
                            fields=["name", "request_hash", "response"], limit=1, ignore_permissions=True)
        if existing:
            if existing[0]["request_hash"] != request_hash:
                raise ValidationError("This request key was already used for a different request.")
            return existing[0]["response"]
        result = operation()
        new_doc("Project Request Key", request_key=key, request_hash=request_hash,
                response=_json_safe(result)).insert(ignore_permissions=True)
        return result


class VeloraSources:
    """Read-only source adapters over the ERP ledgers the signed-in user is allowed to see."""

    def get(self, source_name):
        if source_name == "accounting" and registry.exists("Account Ledger Record"):
            from .host_sources import AccountingSource
            return AccountingSource()
        if source_name == "hrms" and registry.exists("Project Resource Allocation"):
            from .host_sources import HrmsSource
            return HrmsSource()
        lookup = {"procurement": ("Purchase Order", "ProcurementSource"), "sales": ("Sales Order", "SalesSource"),
                  "inventory": ("Stock Entry", "InventorySource"), "fixed_assets": ("Fixed Asset", "FixedAssetSource")}
        if source_name in lookup and registry.exists(lookup[source_name][0]):
            from . import host_sources
            return getattr(host_sources, lookup[source_name][1])()
        return None


class VeloraWorkflow:
    """Hands approvals to the shared Workflow Designer; ProjectOne never decides who approves."""

    def submit(self, actor, doctype, name, action, evidence=None):
        from sqlalchemy import select
        from velora import workflows
        with db.transaction() as conn:
            active = conn.execute(select(workflows.instance.c.id).where(
                workflows.instance.c.doctype == doctype, workflows.instance.c.document_name == name,
                workflows.instance.c.status == "Active")).scalar()
        if active is None:
            definition = next((w for w in workflows.list_definitions() if w["doctype"] == doctype and w["enabled"]), None)
            if definition is None:
                raise ValidationError(f"No approval workflow is set up for {doctype}. Create one in the Workflow Designer.")
            active = workflows.start(definition["name"], doctype, name)["id"]
        return workflows.act(active, action, (evidence or {}).get("comment", ""))

    def list_pending(self, actor, *, company_id, limit):
        from velora import workflows
        return workflows.approval_inbox(limit)


def build_bridge() -> NativeVeloraBridge:
    return NativeVeloraBridge(
        document_engine=VeloraDocuments(), transaction_manager=VeloraTransactions(),
        authorization=VeloraAuthorization(), audit_service=VeloraAudit(), idempotency_store=VeloraIdempotency(),
        source_registry=VeloraSources(), workflow_service=VeloraWorkflow(),
        capability_attestation=NativeIntegrationCapabilities(True, True, True, True, True, True, True))


def current_actor() -> AuthenticatedActor:
    session = get_session()
    return AuthenticatedActor(session.user, SCOPE, frozenset(session.roles),
                              frozenset({"projectone.integration.read_all"}))


_KINDS = ((PermissionError, PermissionDenied), (KeyError, DoesNotExistError), (VersionConflict, ValidationError),
          (ValueError, ValidationError), (TypeError, ValidationError))


def install(run):
    """Wrap the framework's request runner: attach the signed-in actor and turn plain errors into proper HTTP answers."""
    if native_integration_registry.get() is None:
        native_integration_registry.configure(build_bridge())

    def run_with_actor(request, fn):
        def inner():
            request.state.projectone_actor = current_actor()
            request.state.projectone_programme_data_provider = VeloraProgrammeData()
            request.state.projectone_intervention_submitter = submit_intervention
            try:
                return fn()
            except (PermissionDenied, DoesNotExistError, ValidationError):
                raise
            except tuple(k for k, _ in _KINDS) as error:
                kind = next(v for k, v in _KINDS if isinstance(error, k))
                raise kind(str(error).strip("'\"") or kind.__name__) from error
        return run(request, inner)
    return run_with_actor
