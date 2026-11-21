"""Velora Core Rule Engine.

Rules are data, not executable source code. The engine evaluates a bounded JSON
condition language against document and execution context. It never evals Python,
imports user-supplied modules, or executes arbitrary expressions.
"""
from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, insert, select, update, delete

from . import db
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import get_session

md = MetaData()
rules = Table(
    "vl_rule_definition", md,
    Column("name", String(140), primary_key=True),
    Column("title", String(180), nullable=False),
    Column("description", Text),
    Column("scope", String(40), nullable=False, default="global"),
    Column("doctype", String(140), index=True),
    Column("definition", JSON, nullable=False),
    Column("enabled", Integer, nullable=False, default=1),
    Column("version", Integer, nullable=False, default=1),
    Column("created_by", String(254)),
    Column("created_on", DateTime),
    Column("modified_by", String(254)),
    Column("modified_on", DateTime),
)

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{1,139}$")
_FIELD = re.compile(r"^(?:\$[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_.]{0,139})$")
_OPERATORS = {"=", "==", "!=", ">", ">=", "<", "<=", "in", "not in", "contains",
              "not contains", "is_set", "is_not_set", "starts_with", "ends_with"}
_MAX_DEPTH = 12
_MAX_NODES = 250
_MAX_LIST = 500


def ensure():
    from .db.extra_tables import ensure as ensure_tables
    ensure_tables(md)


def _admin():
    session = get_session()
    if session.user != "Administrator" and "System Manager" not in session.roles:
        raise PermissionDenied("Only a System Manager can administer reusable rules")
    return session


def _walk_validate(node, depth=0, counter=None):
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > _MAX_NODES or depth > _MAX_DEPTH:
        raise ValidationError("Rule definition exceeds the complexity limit")
    if not isinstance(node, dict) or len(node) != 1:
        raise ValidationError("Each rule node must contain exactly one logical or comparison operator")
    key, value = next(iter(node.items()))
    if key in ("all", "any"):
        if not isinstance(value, list) or not value or len(value) > _MAX_LIST:
            raise ValidationError(f"Rule '{key}' requires a non-empty list of conditions")
        for child in value:
            _walk_validate(child, depth + 1, counter)
        return
    if key == "not":
        _walk_validate(value, depth + 1, counter)
        return
    if key != "condition" or not isinstance(value, dict):
        raise ValidationError(f"Unsupported rule operator: {key}")
    if set(value) - {"field", "operator", "value"}:
        raise ValidationError("Rule condition contains unsupported properties")
    field, op = value.get("field"), value.get("operator")
    if not isinstance(field, str) or not _FIELD.fullmatch(field) or any(part.startswith("__") for part in field.lstrip("$").split(".")):
        raise ValidationError("Rule condition requires a valid field reference")
    if not isinstance(op, str) or op not in _OPERATORS:
        raise ValidationError(f"Unsupported rule comparison: {op}")
    if op not in ("is_set", "is_not_set") and "value" not in value:
        raise ValidationError("Rule comparison requires a value")
    expected = value.get("value")
    if op in ("in", "not in") and (not isinstance(expected, list) or len(expected) > _MAX_LIST):
        raise ValidationError("Rule membership comparisons require a bounded list")


def validate_definition(definition):
    if not isinstance(definition, dict):
        raise ValidationError("Rule definition must be an object")
    _walk_validate(definition)
    return definition


def _resolve(path, document, context):
    if path.startswith("$"):
        key = path[1:]
        return context.get(key)
    current = document
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _comparable(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return left, right
    if isinstance(right, (int, float, Decimal)) and isinstance(left, (int, float, Decimal, str)):
        try:
            return Decimal(str(left)), Decimal(str(right))
        except (InvalidOperation, ValueError):
            pass
    return left, right


def _evaluate(node, document, context):
    key, value = next(iter(node.items()))
    if key == "all":
        return all(_evaluate(child, document, context) for child in value)
    if key == "any":
        return any(_evaluate(child, document, context) for child in value)
    if key == "not":
        return not _evaluate(value, document, context)
    actual = _resolve(value["field"], document, context)
    op, expected = value["operator"], value.get("value")
    if op == "is_set":
        return actual not in (None, "")
    if op == "is_not_set":
        return actual in (None, "")
    if op == "in":
        return actual in expected
    if op == "not in":
        return actual not in expected
    if op == "contains":
        try: return expected in actual
        except TypeError: return False
    if op == "not contains":
        try: return expected not in actual
        except TypeError: return True
    if op == "starts_with":
        return isinstance(actual, str) and actual.startswith(str(expected))
    if op == "ends_with":
        return isinstance(actual, str) and actual.endswith(str(expected))
    left, right = _comparable(actual, expected)
    try:
        return {
            "=": lambda: left == right, "==": lambda: left == right,
            "!=": lambda: left != right, ">": lambda: left is not None and right is not None and left > right,
            ">=": lambda: left is not None and right is not None and left >= right,
            "<": lambda: left is not None and right is not None and left < right,
            "<=": lambda: left is not None and right is not None and left <= right,
        }[op]()
    except (TypeError, KeyError):
        return False


def evaluate_definition(definition, document=None, context=None):
    """Evaluate an untrusted JSON rule safely. Invalid rules fail closed."""
    validate_definition(definition)
    return bool(_evaluate(definition, document or {}, context or {}))


def save_rule(payload):
    ensure()
    session = _admin()
    if not isinstance(payload, dict):
        raise ValidationError("Rule payload must be an object")
    name = str(payload.get("name") or "").strip()
    title = str(payload.get("title") or name).strip()
    scope = str(payload.get("scope") or "global").strip()
    doctype = str(payload.get("doctype") or "").strip() or None
    if not _NAME.fullmatch(name) or not title or len(title) > 180:
        raise ValidationError("Rule needs a valid name and title")
    if scope not in ("global", "doctype"):
        raise ValidationError("Rule scope must be global or doctype")
    if scope == "doctype" and not doctype:
        raise ValidationError("DocType-scoped rules require a DocType")
    if scope != "doctype" and doctype:
        raise ValidationError("Only DocType-scoped rules may specify a DocType")
    if doctype:
        from .meta.registry import registry
        registry.get(doctype)
    definition = validate_definition(payload.get("definition"))
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValidationError("Rule enabled must be a boolean")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with db.transaction() as conn:
        existing = conn.execute(select(rules).where(rules.c.name == name)).mappings().first()
        version = int(existing["version"]) + 1 if existing else 1
        values = dict(title=title, description=str(payload.get("description") or "")[:4000],
                      scope=scope, doctype=doctype, definition=definition, enabled=int(enabled),
                      version=version, modified_by=session.user, modified_on=now)
        if existing:
            # Preserve the complete prior definition as an append-only version record.
            from .policy_governance import snapshot_rule
            snapshot_rule(conn, dict(existing), session.user)
            conn.execute(update(rules).where(rules.c.name == name).values(**values))
        else:
            conn.execute(insert(rules).values(name=name, **values, created_by=session.user, created_on=now))
    return get_rule(name)


def get_rule(name, include_definition=True):
    ensure()
    with db.transaction() as conn:
        row = conn.execute(select(rules).where(rules.c.name == name)).mappings().first()
    if not row:
        raise DoesNotExistError(f"Rule {name!r} does not exist")
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    if not include_definition:
        result.pop("definition", None)
    return result


def list_rules(scope=None, doctype=None):
    ensure()
    stmt = select(rules).order_by(rules.c.name)
    if scope: stmt = stmt.where(rules.c.scope == scope)
    if doctype: stmt = stmt.where((rules.c.doctype == doctype) | (rules.c.scope == "global"))
    with db.transaction() as conn:
        rows = [dict(x) for x in conn.execute(stmt).mappings()]
    for row in rows:
        row["enabled"] = bool(row["enabled"])
    return rows


def delete_rule(name):
    ensure()
    _admin()
    with db.transaction() as conn:
        changed = conn.execute(delete(rules).where(rules.c.name == name)).rowcount
    if not changed:
        raise DoesNotExistError(f"Rule {name!r} does not exist")
    return {"deleted": name}


def evaluate_saved_rule(name, document=None, context=None):
    """Run an enabled rule. Scope and DocType are checked when supplied by the caller."""
    row = get_rule(name)
    if not row["enabled"]:
        raise ValidationError(f"Rule {name!r} is disabled")
    if row["scope"] == "doctype":
        actual = document.get("doctype") if isinstance(document, dict) else getattr(document, "doctype", None)
        if actual != row["doctype"]:
            raise PermissionDenied("Rule is not applicable to this DocType")
    return {"name": name, "version": row["version"],
            "matched": evaluate_definition(row["definition"], document, context)}
