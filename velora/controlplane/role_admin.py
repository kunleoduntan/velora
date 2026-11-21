"""Company-local role and permission administration (v0.36).

The service accepts a company database Engine. It intentionally has no API to
write role grants to the central control plane: business authorization remains
inside the selected company's database.
"""
from __future__ import annotations
from datetime import datetime, timezone
import re
from sqlalchemy import and_, delete, insert, select, update
from ..db import system as s
from ..exceptions import PermissionDenied, ValidationError, DoesNotExistError

PERMISSIONS = frozenset({"create", "read", "write", "delete", "submit", "cancel", "amend", "export", "print", "share"})
FIELD_ACCESS = frozenset({"hidden", "read_only", "editable"})
_ROLE = re.compile(r"^[A-Za-z][A-Za-z0-9 _.-]{1,119}$")


def _now():
    return datetime.now(timezone.utc)


class RoleAdministration:
    def __init__(self, engine):
        self.engine = engine
        s.system_metadata.create_all(engine)

    @staticmethod
    def _admin(actor):
        roles = set(getattr(actor, "roles", ()) or ())
        if not (getattr(actor, "is_company_admin", False) or "System Manager" in roles):
            raise PermissionDenied("Company role administration permission is required")

    @staticmethod
    def _role_name(name):
        name = str(name or "").strip()
        if not _ROLE.fullmatch(name):
            raise ValidationError("Role name must be 2-120 characters and contain only letters, numbers, spaces, '.', '_' or '-'")
        return name

    def create_role(self, actor, name, description=""):
        self._admin(actor); name = self._role_name(name)
        description = str(description or "").strip()
        if len(description) > 500: raise ValidationError("Role description cannot exceed 500 characters")
        with self.engine.begin() as c:
            if c.execute(select(s.role_definition.c.name).where(s.role_definition.c.name == name)).first():
                raise ValidationError("Role already exists")
            c.execute(insert(s.role_definition).values(name=name, description=description,
                is_system=False, is_active=True, created_by=getattr(actor, "email", ""), created_on=_now()))
        return self.get_role(actor, name)

    def get_role(self, actor, name):
        self._admin(actor)
        with self.engine.connect() as c:
            row = c.execute(select(s.role_definition).where(s.role_definition.c.name == name)).mappings().first()
        if not row: raise DoesNotExistError("Role not found")
        result = dict(row)
        result["inherits"] = self._inherits(c_engine=self.engine, name=name)
        return result

    @staticmethod
    def _inherits(c_engine, name):
        with c_engine.connect() as c:
            return list(c.execute(select(s.role_inheritance.c.inherits_role).where(s.role_inheritance.c.role == name).order_by(s.role_inheritance.c.inherits_role)).scalars())

    def list_roles(self, actor, include_inactive=False):
        self._admin(actor)
        stmt = select(s.role_definition).order_by(s.role_definition.c.name)
        if not include_inactive: stmt = stmt.where(s.role_definition.c.is_active.is_(True))
        with self.engine.connect() as c: rows = c.execute(stmt).mappings().all()
        return [{**dict(r), "inherits": self._inherits(self.engine, r["name"])} for r in rows]

    def set_role_active(self, actor, name, active):
        self._admin(actor)
        if not isinstance(active, bool): raise ValidationError("active must be a boolean")
        with self.engine.begin() as c:
            row = c.execute(select(s.role_definition.c.is_system).where(s.role_definition.c.name == name)).first()
            if not row: raise DoesNotExistError("Role not found")
            if row.is_system and not active: raise ValidationError("System roles cannot be deactivated")
            c.execute(update(s.role_definition).where(s.role_definition.c.name == name).values(is_active=active))
        return self.get_role(actor, name)

    def set_inheritance(self, actor, role, parents):
        self._admin(actor); role = self._role_name(role)
        if not isinstance(parents, list) or any(not isinstance(p, str) for p in parents):
            raise ValidationError("inherits must be a list of role names")
        parents = sorted(set(self._role_name(p) for p in parents))
        if role in parents: raise ValidationError("A role cannot inherit itself")
        with self.engine.begin() as c:
            names = set(c.execute(select(s.role_definition.c.name).where(s.role_definition.c.is_active.is_(True))).scalars())
            if role not in names or not set(parents).issubset(names): raise ValidationError("Role and inherited roles must exist and be active")
            graph = {n: set(c.execute(select(s.role_inheritance.c.inherits_role).where(s.role_inheritance.c.role == n)).scalars()) for n in names}
            graph[role] = set(parents)
            def reaches(start, target, seen=None):
                seen = seen or set()
                if start == target: return True
                if start in seen: return False
                seen.add(start)
                return any(reaches(x, target, seen) for x in graph.get(start, ()))
            if any(reaches(parent, role) for parent in parents): raise ValidationError("Role inheritance would create a cycle")
            c.execute(delete(s.role_inheritance).where(s.role_inheritance.c.role == role))
            for parent in parents: c.execute(insert(s.role_inheritance).values(role=role, inherits_role=parent))
        return self.get_role(actor, role)

    def set_permission(self, actor, role, doctype, permission, allowed=True):
        self._admin(actor); role = self._role_name(role)
        doctype = str(doctype or "").strip(); permission = str(permission or "").strip().lower()
        if not doctype or len(doctype) > 140: raise ValidationError("A valid DocType is required")
        if permission not in PERMISSIONS: raise ValidationError("Unsupported permission type")
        if not isinstance(allowed, bool): raise ValidationError("allowed must be a boolean")
        with self.engine.begin() as c:
            if not c.execute(select(s.role_definition.c.name).where(and_(s.role_definition.c.name == role, s.role_definition.c.is_active.is_(True)))).first():
                raise DoesNotExistError("Active role not found")
            c.execute(delete(s.role_permission).where(and_(s.role_permission.c.role == role, s.role_permission.c.doctype == doctype, s.role_permission.c.permission == permission)))
            c.execute(insert(s.role_permission).values(role=role, doctype=doctype, permission=permission, allowed=allowed))
        return {"role": role, "doctype": doctype, "permission": permission, "allowed": allowed}

    def set_field_access(self, actor, role, doctype, fieldname, access):
        self._admin(actor); role = self._role_name(role)
        doctype = str(doctype or "").strip(); fieldname = str(fieldname or "").strip(); access = str(access or "").strip()
        if not doctype or not fieldname: raise ValidationError("DocType and fieldname are required")
        if access not in FIELD_ACCESS: raise ValidationError("access must be hidden, read_only or editable")
        with self.engine.begin() as c:
            if not c.execute(select(s.role_definition.c.name).where(and_(s.role_definition.c.name == role, s.role_definition.c.is_active.is_(True)))).first(): raise DoesNotExistError("Active role not found")
            c.execute(delete(s.role_field_permission).where(and_(s.role_field_permission.c.role == role, s.role_field_permission.c.doctype == doctype, s.role_field_permission.c.fieldname == fieldname)))
            c.execute(insert(s.role_field_permission).values(role=role, doctype=doctype, fieldname=fieldname, access=access))
        return {"role": role, "doctype": doctype, "fieldname": fieldname, "access": access}

    def effective_permissions(self, actor, role):
        self._admin(actor)
        with self.engine.connect() as c:
            exists = c.execute(select(s.role_definition.c.name).where(and_(s.role_definition.c.name == role, s.role_definition.c.is_active.is_(True)))).first()
            if not exists: raise DoesNotExistError("Active role not found")
            graph = {}
            for name, parent in c.execute(select(s.role_inheritance.c.role, s.role_inheritance.c.inherits_role)):
                graph.setdefault(name, set()).add(parent)
            roles, pending = set(), [role]
            while pending:
                current = pending.pop()
                if current in roles: continue
                roles.add(current); pending.extend(graph.get(current, ()))
            rows = c.execute(select(s.role_permission).where(s.role_permission.c.role.in_(roles))).mappings().all()
            # Explicit deny wins over inherited allow. This avoids privilege expansion by inheritance.
            effective = {}
            for row in rows:
                key = (row["doctype"], row["permission"])
                effective[key] = effective.get(key, True) and bool(row["allowed"])
            fields = c.execute(select(s.role_field_permission).where(s.role_field_permission.c.role.in_(roles))).mappings().all()
            access_rank = {"editable": 0, "read_only": 1, "hidden": 2}
            field_access = {}
            for row in fields:
                key = (row["doctype"], row["fieldname"]); value = row["access"]
                if key not in field_access or access_rank[value] > access_rank[field_access[key]]: field_access[key] = value
        return {"roles": sorted(roles), "permissions": [{"doctype": d, "permission": p, "allowed": a} for (d,p),a in sorted(effective.items())],
                "fields": [{"doctype": d, "fieldname": f, "access": a} for (d,f),a in sorted(field_access.items())]}


    def set_role_conflict(self, actor, role_a, role_b, reason=""):
        """Declare two roles mutually exclusive for users in this company."""
        self._admin(actor)
        role_a, role_b = self._role_name(role_a), self._role_name(role_b)
        if role_a == role_b:
            raise ValidationError("A role cannot conflict with itself")
        reason = str(reason or "").strip()
        if len(reason) > 500:
            raise ValidationError("Conflict reason cannot exceed 500 characters")
        left, right = sorted((role_a, role_b))
        with self.engine.begin() as c:
            active = set(c.execute(select(s.role_definition.c.name).where(s.role_definition.c.is_active.is_(True))).scalars())
            if left not in active or right not in active:
                raise DoesNotExistError("Both roles must exist and be active")
            c.execute(delete(s.role_conflict).where(and_(s.role_conflict.c.role_a == left, s.role_conflict.c.role_b == right)))
            c.execute(insert(s.role_conflict).values(role_a=left, role_b=right, reason=reason,
                created_by=getattr(actor, "email", ""), created_on=_now()))
        return {"role_a": left, "role_b": right, "reason": reason}

    def clear_role_conflict(self, actor, role_a, role_b):
        self._admin(actor)
        left, right = sorted((self._role_name(role_a), self._role_name(role_b)))
        with self.engine.begin() as c:
            result = c.execute(delete(s.role_conflict).where(and_(s.role_conflict.c.role_a == left, s.role_conflict.c.role_b == right)))
        return {"deleted": result.rowcount or 0}

    def list_role_conflicts(self, actor):
        self._admin(actor)
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(select(s.role_conflict).order_by(s.role_conflict.c.role_a, s.role_conflict.c.role_b)).mappings()]

    def set_row_policy(self, actor, role, doctype, permission, conditions):
        """Replace a role's row scope. Conditions are ANDed; policies across a user's roles are ORed."""
        self._admin(actor); role = self._role_name(role)
        doctype = str(doctype or "").strip(); permission = str(permission or "").strip().lower()
        if not doctype or len(doctype) > 140: raise ValidationError("A valid DocType is required")
        if permission not in PERMISSIONS: raise ValidationError("Unsupported permission type")
        from ..permissions import _validate_row_conditions
        try: _validate_row_conditions(conditions)
        except Exception as exc: raise ValidationError(str(exc)) from exc
        # Validate fields against registered metadata when available.
        try:
            from ..meta.registry import registry
            meta = registry.get(doctype)
            allowed_fields = set(meta.column_names())
            for condition in conditions:
                if condition["field"] not in allowed_fields:
                    raise ValidationError(f"Unknown row policy field {doctype}.{condition['field']}")
        except DoesNotExistError:
            raise ValidationError(f"Unknown DocType {doctype}")
        with self.engine.begin() as c:
            if not c.execute(select(s.role_definition.c.name).where(and_(s.role_definition.c.name == role, s.role_definition.c.is_active.is_(True)))).first():
                raise DoesNotExistError("Active role not found")
            c.execute(delete(s.row_policy).where(and_(s.row_policy.c.role == role, s.row_policy.c.doctype == doctype, s.row_policy.c.permission == permission)))
            c.execute(insert(s.row_policy).values(role=role, doctype=doctype, permission=permission, conditions=conditions, is_active=True, updated_by=getattr(actor, "email", ""), updated_on=_now()))
        return {"role": role, "doctype": doctype, "permission": permission, "conditions": conditions}

    def clear_row_policy(self, actor, role, doctype, permission):
        self._admin(actor); role = self._role_name(role)
        with self.engine.begin() as c:
            result = c.execute(delete(s.row_policy).where(and_(s.row_policy.c.role == role, s.row_policy.c.doctype == doctype, s.row_policy.c.permission == permission)))
        return {"deleted": result.rowcount or 0}
