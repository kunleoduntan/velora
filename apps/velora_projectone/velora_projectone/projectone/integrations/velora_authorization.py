"""ProjectOne adapter for the Velora Frappe-style authorization engine.

This adapter delegates role inheritance, DocType permissions, DocField.permlevel,
record shares and configured row policies to Velora. It deliberately does not
implement field-type-specific rules. User Permissions are not claimed here:
the current host source does not expose a User Permission store/API.
"""
from __future__ import annotations

from .native_documents import CORE_DOCUMENTS
from .host_contracts import AuthenticatedActor

# ProjectOne command vocabulary -> host DocType permission action.
_ACTIONS = {
    "create": "create", "read": "read", "get": "read", "list": "read",
    "update": "write", "write": "write", "delete": "delete",
    "submit": "submit", "cancel": "cancel", "amend": "amend",
    "report": "report", "export": "export", "import": "import",
    "print": "print", "email": "email",
}


class VeloraFrappeAuthorizationAdapter:
    """Translate ProjectOne permissions into the host's native permission checks.

    `assert_permission` checks the relevant DocType permission and, when a
    project scope is supplied, the Project record's document and row policies.
    Field visibility/editability is resolved solely from DocField.permlevel and
    the host Role Permission Manager; the field's data type is never inspected.
    """
    def __init__(self, *, doctype_map: dict[str, str] | None = None, custom_permission_checker=None):
        self.doctype_map = dict(doctype_map or {name: name for name in CORE_DOCUMENTS})
        self.custom_permission_checker = custom_permission_checker
        unknown = set(self.doctype_map) - set(CORE_DOCUMENTS)
        if unknown:
            raise ValueError(f"Unsupported ProjectOne DocTypes: {sorted(unknown)}")

    @staticmethod
    def _session(actor: AuthenticatedActor):
        if not isinstance(actor, AuthenticatedActor):
            raise PermissionError("Trusted Velora actor is required.")
        from velora.permissions import Session
        return Session(user=actor.actor_id, roles=frozenset(actor.roles),
                       attributes={"company": actor.company_id})

    @staticmethod
    def _resolve_permission(permission: str):
        if not isinstance(permission, str):
            raise PermissionError("Unsupported ProjectOne permission key.")
        parts = permission.split(".")
        if permission.startswith("projectone."):
            if len(parts) < 3:
                raise PermissionError("ProjectOne permission key must include DocType and action.")
            key = ".".join(parts[1:-1])
        else:
            if len(parts) != 2:
                raise PermissionError("Unsupported ProjectOne workflow permission key.")
            key = parts[0]
        action = parts[-1]
        if key == "project.audit" and action == "read":
            return "Project", "read"
        if key == "workflow.inbox" and action == "read":
            return None, "workflow.inbox.read"
        if action not in _ACTIONS and action not in {"approve", "reject", "suspend", "resume", "complete", "supersede"}:
            raise PermissionError(f"Unsupported host DocType permission action: {action}")
        # Permission slug is resolved against the explicit allowlist, not by
        # guessing arbitrary host DocTypes from caller input.
        for project_doctype, cfg in CORE_DOCUMENTS.items():
            slug = cfg["permission"].removeprefix("projectone.")
            if slug == key:
                return project_doctype, _ACTIONS.get(action, action)
            if project_doctype.lower().replace(" ", "_") == key:
                return project_doctype, _ACTIONS.get(action, action)
        raise PermissionError(f"No ProjectOne DocType mapping for permission {permission!r}.")

    def assert_permission(self, actor: AuthenticatedActor, permission: str, *,
                          company_id: str, project_id: str | None = None) -> None:
        if company_id != actor.company_id:
            raise PermissionError("Company scope must match the authenticated actor.")
        from velora.meta.registry import registry
        from velora.permissions import check_permission, check_document_permission, check_row_policy, session_as
        from velora.exceptions import PermissionDenied
        doctype, action = self._resolve_permission(permission)
        session = self._session(actor)
        try:
            if doctype is None:
                if not callable(self.custom_permission_checker):
                    raise PermissionError(f"Custom permission {action!r} requires a host permission checker.")
                self.custom_permission_checker(actor, action, company_id=company_id, project_id=project_id)
                return
            meta = registry.get(self.doctype_map[doctype])
            check_permission(meta, action, session)
            if project_id:
                project_meta = registry.get(self.doctype_map["Project"])
                # Project record access is an additional restrictive condition,
                # not a replacement for the target DocType permission.
                check_document_permission(project_meta, "write" if action in {"create", "write", "delete", "submit", "cancel", "amend"} else "read", project_id, session)
                with session_as(session):
                    project = self._load_project(project_id, actor.company_id, session)
                if project is not None:
                    check_row_policy(project_meta.name, "write" if action in {"create", "write", "delete", "submit", "cancel", "amend"} else "read", project, session)
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc

    @staticmethod
    def _load_project(project_id: str, company_id: str, session):
        # Avoid a second authorization implementation. The document engine's
        # canonical get path performs tenant filtering and normal document checks.
        from velora.document.document import get_doc
        try:
            doc = get_doc("Project", project_id)
            values = doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)
            if values.get("company") != company_id:
                raise PermissionError("Project is outside the authenticated company.")
            return values
        except PermissionError:
            raise
        except Exception:
            # A missing record is handled by the caller's repository lookup.
            # Do not interpret arbitrary authorization/database errors as access.
            raise

    def get_permitted_fields(self, actor: AuthenticatedActor, doctype: str,
                             action: str, *, company_id: str,
                             project_id: str | None = None) -> set[str]:
        if company_id != actor.company_id:
            raise PermissionError("Company scope must match the authenticated actor.")
        if doctype not in self.doctype_map:
            raise PermissionError(f"Unsupported ProjectOne DocType {doctype!r}.")
        from velora.meta.registry import registry
        from velora.permissions import field_access
        from velora.exceptions import PermissionDenied
        session = self._session(actor)
        meta = registry.get(self.doctype_map[doctype])
        normalized_action = "create" if action == "create" else "write" if action in {"write", "update"} else "read"
        try:
            result = set()
            for field in meta.fields:
                access = field_access(meta.name, field.fieldname, session, action=normalized_action)
                if normalized_action == "read":
                    if access != "hidden":
                        result.add(field.fieldname)
                elif access == "editable":
                    result.add(field.fieldname)
            return result
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc
