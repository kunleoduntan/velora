"""Company-local authorization and field-security enforcement.

Metadata permissions remain the compatibility baseline. Where a company has
configured an RBAC decision for a DocType/operation, the RBAC decision is
 authoritative and explicit deny wins. All policy reads use the active company
site database; nothing is resolved from the control plane.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy import and_, select, String
from .exceptions import PermissionDenied

@dataclass(frozen=True)
class Session:
    user: str = "Administrator"
    roles: frozenset = field(default_factory=frozenset)
    attributes: dict = field(default_factory=dict)

ADMINISTRATOR = Session("Administrator", frozenset({"System Manager"}))
_session: ContextVar[Session] = ContextVar("velora_session", default=ADMINISTRATOR)

@contextmanager
def session_as(session: Session):
    token = _session.set(session)
    try: yield session
    finally: _session.reset(token)

def get_session() -> Session: return _session.get()

def _not_provisioned(exc) -> bool:
    """True only for the cases where authorization data legitimately does not exist yet: the system tables are
    not created (a library session before migrate) or no database is bound. Any OTHER failure while reading
    authorization data (timeout, deadlock, dropped connection) must never be read as "no restriction"."""
    text = str(exc).lower()
    return isinstance(exc, RuntimeError) or "no such table" in text or "does not exist" in text

def _effective_roles(session):
    """Expand active role inheritance in the selected company database."""
    roles = set(session.roles or ())
    if not roles: return roles
    try:
        from . import db
        from .db.system import role_definition, role_inheritance
        with db.transaction() as conn:
            known = set(conn.execute(select(role_definition.c.name)).scalars())
            active = set(conn.execute(select(role_definition.c.name).where(role_definition.c.is_active.is_(True))).scalars())
            graph = {}
            for role, parent in conn.execute(select(role_inheritance.c.role, role_inheritance.c.inherits_role)):
                graph.setdefault(role, set()).add(parent)
        roles.difference_update(known - active)
        pending = list(roles); expanded = set()
        while pending:
            role = pending.pop()
            if role in expanded: continue
            expanded.add(role)
            if role in active: pending.extend(graph.get(role, ()))
        return expanded
    except Exception as exc:
        # Before system tables are installed, legacy metadata authorization remains usable.
        if _not_provisioned(exc):
            return roles
        raise PermissionDenied("Unable to resolve effective roles") from exc

def _policy_decision(doctype, permission, roles):
    """Return True/False for a configured policy, or None if no policy exists."""
    if not roles: return None
    try:
        from . import db
        from .db.system import role_permission
        with db.transaction() as conn:
            rows = conn.execute(select(role_permission.c.allowed).where(and_(
                role_permission.c.role.in_(roles), role_permission.c.doctype == doctype,
                role_permission.c.permission == permission))).scalars().all()
        return (all(bool(v) for v in rows)) if rows else None  # any explicit deny wins
    except Exception as exc:
        if _not_provisioned(exc):
            return None
        # An explicit deny we could not read must not silently turn into the metadata default (allow).
        raise PermissionDenied("Unable to resolve role permissions") from exc

def _assert_no_role_conflicts(roles):
    """Fail closed when effective roles violate a configured SoD conflict."""
    if len(roles) < 2:
        return
    try:
        from . import db
        from .db.system import role_conflict
        with db.transaction() as conn:
            pairs = conn.execute(select(role_conflict.c.role_a, role_conflict.c.role_b)).all()
        for left, right in pairs:
            if left in roles and right in roles:
                raise PermissionDenied(f"Conflicting roles {left!r} and {right!r} are assigned together; access is blocked by segregation of duties")
    except PermissionDenied:
        raise
    except Exception as exc:
        # Do not turn a missing pre-migration table into a broad outage.
        if "no such table" not in str(exc).lower() and "does not exist" not in str(exc).lower():
            raise PermissionDenied("Unable to verify segregation-of-duties role conflicts") from exc

def has_permission(meta, ptype: str, session: Session | None = None) -> bool:
    s = session or get_session()
    if s.user == "Administrator": return True
    roles = _effective_roles(s)
    _assert_no_role_conflicts(roles)
    decision = _policy_decision(meta.name, ptype, roles)
    if decision is not None: return decision
    return any(p.role in roles and p.allows(ptype) for p in meta.permissions)

def check_permission(meta, ptype: str, session: Session | None = None):
    s = session or get_session()
    if not has_permission(meta, ptype, s):
        raise PermissionDenied(f"{s.user} has no {ptype!r} permission on {meta.name}")
    # Governance policies are a restrictive overlay: they cannot grant RBAC access.
    from .policy_governance import evaluate
    if evaluate(meta.name, "action", ptype, {}, {"user": s.user, "roles": list(_effective_roles(s))}):
        raise PermissionDenied(f"{s.user} is blocked by an enterprise policy from {ptype!r} on {meta.name}")

def field_access(doctype: str, fieldname: str, session: Session | None = None) -> str:
    """Return editable/read_only/hidden; the most restrictive inherited rule wins."""
    s = session or get_session()
    if s.user == "Administrator": return "editable"
    roles = _effective_roles(s)
    try:
        from . import db
        from .db.system import role_field_permission
        values = []
        if roles:
            with db.transaction() as conn:
                values = conn.execute(select(role_field_permission.c.access).where(and_(
                    role_field_permission.c.role.in_(roles), role_field_permission.c.doctype == doctype,
                    role_field_permission.c.fieldname == fieldname))).scalars().all()
        rank = {"editable": 0, "read_only": 1, "hidden": 2}
        access = max(values, key=lambda x: rank.get(x, 2)) if values else "editable"
        from .policy_governance import evaluate
        if evaluate(doctype, "field", fieldname, {}, {"user": s.user, "roles": list(roles)}):
            return "hidden"
        return access
    except PermissionDenied:
        raise
    except Exception as exc:
        if _not_provisioned(exc):
            return "editable"
        # A hidden/read-only rule we could not read must not turn into "editable".
        raise PermissionDenied("Unable to resolve field permissions") from exc

def check_field_write(doctype: str, values: dict, session: Session | None = None):
    s = session or get_session()
    for fieldname in values:
        access = field_access(doctype, fieldname, s)
        if access != "editable":
            raise PermissionDenied(f"{s.user} cannot write {doctype}.{fieldname} ({access})")

def filter_dict(doctype: str, values: dict, session: Session | None = None) -> dict:
    s = session or get_session()
    if s.user == "Administrator": return values
    return {k: v for k, v in values.items() if field_access(doctype, k, s) != "hidden"}

def shared_names(doctype: str, ptype: str, session: Session | None = None) -> list[str]:
    from sqlalchemy import select
    from . import db
    from .db.system import doc_share
    s = session or get_session()
    try:
        with db.transaction() as conn:
            stmt = select(doc_share.c.docname).where(doc_share.c.doctype == doctype, doc_share.c.user_email == s.user)
            stmt = stmt.where(doc_share.c.write.is_(True)) if ptype == "write" else stmt.where(doc_share.c.read.is_(True))
            return list(conn.execute(stmt).scalars())
    except Exception: return []

def has_document_permission(meta, ptype: str, name: str, session: Session | None = None) -> bool:
    s = session or get_session()
    if has_permission(meta, ptype, s): return True
    if ptype in ("read", "write"):
        return name in shared_names(meta.name, ptype, s) or (ptype == "read" and name in shared_names(meta.name, "write", s))
    return False

def check_document_permission(meta, ptype: str, name: str, session: Session | None = None):
    if not has_document_permission(meta, ptype, name, session):
        s = session or get_session()
        raise PermissionDenied(f"{s.user} has no {ptype!r} permission on {meta.name} {name}")


# ---- Row-level security (v0.38) ---------------------------------------------
_ROW_OPERATORS = {"eq", "ne", "in", "not_in", "is_set", "is_not_set", "equals_user", "in_user_roles", "in_scope"}

def _row_policy_rows(doctype: str, permission: str, session: Session | None = None):
    """Return active policies for the user's expanded company-local roles."""
    s = session or get_session()
    roles = _effective_roles(s)
    if not roles:
        return []
    try:
        from . import db
        from .db.system import row_policy
        with db.transaction() as conn:
            return [dict(r) for r in conn.execute(select(row_policy).where(and_(
                row_policy.c.role.in_(roles), row_policy.c.doctype == doctype,
                row_policy.c.permission == permission, row_policy.c.is_active.is_(True)
            ))).mappings()]
    except Exception as exc:
        # A configured-but-unreadable policy table must not silently widen access.
        from .exceptions import PermissionDenied
        if "no such table" in str(exc).lower() or "does not exist" in str(exc).lower():
            return []
        raise PermissionDenied("Unable to resolve row-level security policy") from exc

def _scope_values(name: str, session) -> list:
    """Resolve a named record scope through the installed app that provides it (hook `row_scope_provider`).

    A scope is a rule an app computes at request time, for example "the employees I manage". An unknown scope fails
    closed: a typo in a policy must never widen what someone can see."""
    import importlib
    from .meta.registry import registry as _reg
    for app_name in _reg.apps:
        try: hooks = importlib.import_module(f"{app_name}.hooks")
        except ModuleNotFoundError as exc:
            if exc.name == f"{app_name}.hooks": continue
            raise
        path = getattr(hooks, "row_scope_provider", None)
        if not path: continue
        module = importlib.import_module(path)
        if name in getattr(module, "SCOPES", ()):
            return list(module.resolve_scope(name, session))
    raise PermissionDenied(f"Unknown record scope {name!r}")

def _condition_value(condition, session):
    op = condition["operator"]
    if op == "equals_user": return session.user
    if op == "in_user_roles": return list(_effective_roles(session))
    if op == "in_scope": return _scope_values(condition["value"], session)
    return condition.get("value")

def _validate_row_conditions(conditions):
    if not isinstance(conditions, list) or len(conditions) > 30:
        raise PermissionDenied("Invalid row-level policy conditions")
    for c in conditions:
        if not isinstance(c, dict) or set(c) - {"field", "operator", "value"}:
            raise PermissionDenied("Invalid row-level policy condition")
        if not isinstance(c.get("field"), str) or not c["field"] or len(c["field"]) > 140:
            raise PermissionDenied("Invalid row-level policy field")
        if c.get("operator") not in _ROW_OPERATORS:
            raise PermissionDenied("Unsupported row-level policy operator")
        op = c["operator"]
        if op in ("eq", "ne", "in", "not_in") and "value" not in c:
            raise PermissionDenied("Row-level policy value is required")
        if op in ("in", "not_in") and (not isinstance(c.get("value"), list) or len(c["value"]) > 500):
            raise PermissionDenied("Row-level policy list must contain at most 500 values")
        if op == "in_scope" and (not isinstance(c.get("value"), str) or not c["value"] or len(c["value"]) > 80):
            raise PermissionDenied("A record-scope condition must name its scope")

def _granting_roles(doctype: str, permission: str, roles) -> set:
    """The roles that give the permission on the doctype (a configured role permission replaces the metadata default)."""
    try:
        from . import db
        from .db.system import role_permission
        with db.transaction() as conn:
            rows = conn.execute(select(role_permission.c.role, role_permission.c.allowed).where(and_(
                role_permission.c.role.in_(roles), role_permission.c.doctype == doctype,
                role_permission.c.permission == permission))).all()
        if rows: return {r for r, allowed in rows if allowed}
    except Exception as exc:
        if not _not_provisioned(exc): raise PermissionDenied("Unable to resolve role permissions") from exc
    try:
        from .meta.registry import registry
        meta = registry.get(doctype)
        return {p.role for p in meta.permissions if p.role in roles and p.allows(permission)}
    except Exception:
        return set()

def _has_unscoped_grant(doctype: str, permission: str, policies, session) -> bool:
    """Access is the union of what a user's roles grant: a role that grants the permission and has no row policy
    gives the whole table, whatever another (narrower) role of the same user is limited to."""
    scoped = {p["role"] for p in policies}
    roles = set(_effective_roles(session)) - scoped
    return bool(roles and _granting_roles(doctype, permission, roles))

def row_policy_sql(doctype: str, permission: str, table, session: Session | None = None):
    """Build a bound SQL predicate; None means no row policy is configured."""
    from sqlalchemy import and_, or_
    s = session or get_session()
    policies = _row_policy_rows(doctype, permission, s)
    if not policies or s.user == "Administrator": return None
    if _has_unscoped_grant(doctype, permission, policies, s): return None
    role_clauses = []
    for policy in policies:
        conditions = policy["conditions"] or []
        _validate_row_conditions(conditions)
        parts = []
        for c in conditions:
            field = c["field"]
            if field not in table.c:
                from .exceptions import PermissionDenied
                raise PermissionDenied(f"Invalid row policy field {doctype}.{field}")
            col, op = table.c[field], c["operator"]
            value = _condition_value(c, s)
            if op in ("eq", "equals_user"): parts.append(col.is_(None) if value is None else col == value)
            elif op == "ne": parts.append(col.is_not(None) if value is None else col != value)
            elif op == "in": parts.append(col.in_(value))
            elif op == "not_in": parts.append(col.not_in(value))
            elif op == "is_set": parts.append((col.is_not(None) & (col != "")) if isinstance(col.type, String) else col.is_not(None))
            elif op == "is_not_set": parts.append((col.is_(None) | (col == "")) if isinstance(col.type, String) else col.is_(None))
            elif op in ("in_user_roles", "in_scope"): parts.append(col.in_(value))
        role_clauses.append(and_(*parts) if parts else True)
    return or_(*role_clauses)

def row_policy_allows(doctype: str, permission: str, values: dict, session: Session | None = None) -> bool:
    """Evaluate the same allow-list DSL for a single document before mutation/read."""
    s = session or get_session()
    policies = _row_policy_rows(doctype, permission, s)
    if not policies or s.user == "Administrator": return True
    if _has_unscoped_grant(doctype, permission, policies, s): return True
    for policy in policies:
        conditions = policy["conditions"] or []
        _validate_row_conditions(conditions)
        ok = True
        for c in conditions:
            field, op = c["field"], c["operator"]
            actual, expected = values.get(field), _condition_value(c, s)
            if op in ("eq", "equals_user"): ok &= actual == expected
            elif op == "ne": ok &= actual != expected
            elif op == "in": ok &= actual in expected
            elif op == "not_in": ok &= actual not in expected
            elif op == "is_set": ok &= actual not in (None, "")
            elif op == "is_not_set": ok &= actual in (None, "")
            elif op in ("in_user_roles", "in_scope"): ok &= actual in expected
        if ok: return True
    return False

def check_row_policy(doctype: str, permission: str, values: dict, session: Session | None = None):
    s = session or get_session()
    if not row_policy_allows(doctype, permission, values, s):
        raise PermissionDenied(f"{s.user} is outside the permitted {doctype} record scope")
    from .policy_governance import evaluate
    context = {"user": s.user, "roles": list(_effective_roles(s))}
    if evaluate(doctype, "record", permission, values, context):
        raise PermissionDenied(f"{s.user} is blocked by an enterprise record policy on {doctype}")
    # At this checkpoint the document values are available, so action rules may
    # combine identity/context predicates with business-field predicates.
    if evaluate(doctype, "action", permission, values, context):
        raise PermissionDenied(f"{s.user} is blocked by an enterprise action policy on {doctype}")
