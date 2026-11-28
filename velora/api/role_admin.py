"""Company-local DocType, permission-level and field-access administration."""
from fastapi import Body, FastAPI, Request

from .. import db
from ..controlplane.role_admin import RoleAdministration
from ..meta.registry import registry
from ..permissions import get_session


def install_role_admin_routes(app: FastAPI, scope, run):
    def service():
        return RoleAdministration(db.get_engine())

    @app.get("/api/role-admin/roles")
    def role_admin_roles(request: Request):
        def fn():
            actor = get_session()
            existing = service().list_roles(actor)
            names = {r["name"] for r in existing}
            known = {"System Manager"}
            for meta in registry.all():
                for permission in meta.permissions:
                    role = getattr(permission, "role", None) or (permission.get("role") if isinstance(permission, dict) else None)
                    if role: known.add(str(role))
            for workflow in __import__("velora.workflows", fromlist=["list_definitions"]).list_definitions():
                for transition in workflow.get("transitions") or []:
                    known.update(str(r) for r in transition.get("roles") or [])
            existing.extend({"name": name, "description": "Role referenced by application metadata", "is_active": True, "is_system": name == "System Manager"}
                            for name in sorted(known - names))
            return existing
        return run(request, fn)

    @app.post("/api/role-admin/roles")
    def role_admin_create_role(request: Request, body: dict = Body(...)):
        return run(request, lambda: service().create_role(get_session(), body.get("name", ""), body.get("description", "")))

    @app.get("/api/role-admin/role/{role}")
    def role_admin_role(role: str, request: Request):
        return run(request, lambda: service().effective_permissions(get_session(), role))

    @app.get("/api/role-admin/doctype/{doctype}")
    def role_admin_doctype(doctype: str, request: Request):
        def fn():
            from ..exceptions import PermissionDenied
            actor = get_session()
            if actor.user != "Administrator" and "System Manager" not in actor.roles:
                raise PermissionDenied("Only a System Manager can administer DocType permissions")
            meta = registry.get(doctype)
            return {"name": meta.name, "module": meta.module, "istable": meta.istable,
                    "fields": [f.to_dict() for f in meta.fields if f.fieldtype not in ("Section Break", "Column Break", "Tab Break")],
                    "permissions": [{**vars(p), "import": bool(getattr(p, "import_", False))} for p in meta.permissions]}
        return run(request, fn)

    def ensure_company_role(actor, role: str):
        current = service().list_roles(actor)
        if not any(item["name"] == role for item in current):
            known = {item["name"] for item in role_admin_roles_for_actor(actor)}
            if role not in known:
                from ..exceptions import ValidationError
                raise ValidationError(f"Role {role!r} is not defined for this company")
            service().create_role(actor, role, "Role permission settings")

    def role_admin_roles_for_actor(actor):
        existing = service().list_roles(actor)
        names = {r["name"] for r in existing}
        known = {"System Manager"}
        for meta in registry.all():
            for permission in meta.permissions:
                role = getattr(permission, "role", None) or (permission.get("role") if isinstance(permission, dict) else None)
                if role: known.add(str(role))
        from .. import workflows
        for workflow in workflows.list_definitions():
            for transition in workflow.get("transitions") or []:
                known.update(str(r) for r in transition.get("roles") or [])
        return existing + [{"name": name} for name in sorted(known - names)]

    @app.post("/api/role-admin/permission")
    def role_admin_set_permission(request: Request, body: dict = Body(...)):
        def fn():
            actor = get_session(); role = str(body.get("role", "")); ensure_company_role(actor, role)
            return service().set_permission(actor, role,
                str(body.get("doctype", "")), str(body.get("permission", "")),
                bool(body.get("allowed", False)), body.get("permlevel", 0))
        return run(request, fn)

    @app.post("/api/role-admin/field-access")
    def role_admin_set_field_access(request: Request, body: dict = Body(...)):
        def fn():
            actor = get_session(); role = str(body.get("role", "")); ensure_company_role(actor, role)
            target = str(body.get("doctype", "")); fieldname = str(body.get("fieldname", ""))
            if registry.get(target).get_field(fieldname) is None:
                from ..exceptions import ValidationError
                raise ValidationError(f"Unknown field {target}.{fieldname}")
            return service().set_field_access(actor, role,
                target, fieldname, str(body.get("access", "hidden")))
        return run(request, fn)

    @app.post("/api/role-admin/field-access/reset")
    def role_admin_clear_field_access(request: Request, body: dict = Body(...)):
        def fn():
            actor = get_session(); role = str(body.get("role", "")); ensure_company_role(actor, role)
            target = str(body.get("doctype", "")); fieldname = str(body.get("fieldname", ""))
            if registry.get(target).get_field(fieldname) is None:
                from ..exceptions import ValidationError
                raise ValidationError(f"Unknown field {target}.{fieldname}")
            return service().clear_field_access(actor, role, target, fieldname)
        return run(request, fn)
