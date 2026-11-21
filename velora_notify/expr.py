"""A small, SAFE expression language for notification conditions and recipient expressions.

    doc.status == "Approved" and doc.grand_total > 1000000
    changed("status") and old.status == "Draft"
    days_until(doc.due_date) <= 3 and not has_role("Auditor")
    doc.customer in ["Acme", "Bola Stores"]

It is NOT Python `eval`: the text is parsed, every node is checked against a whitelist, and a tiny interpreter evaluates it. There is no way to import, call an
arbitrary function, read a name that starts with an underscore, build a lambda, comprehension or f-string, or run for long (length and node limits).
"""
from __future__ import annotations

import ast
import operator
from datetime import date, datetime
from decimal import Decimal

MAX_LEN, MAX_NODES, MAX_DEPTH = 500, 120, 24


class ExprError(ValueError):
    pass


class DocView:
    """Read-only attribute view of a record (a missing field is None, never an error). Child rows are lists of DocViews."""
    __slots__ = ("_d",)

    def __init__(self, data: dict | None):
        object.__setattr__(self, "_d", dict(data or {}))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        v = self._d.get(name)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return [DocView(x) for x in v]
        return v

    def __setattr__(self, k, v):
        raise AttributeError("read-only")

    def __repr__(self):
        return f"<{self._d.get('doctype', 'record')} {self._d.get('name', '')}>"


def _to_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ExprError(f"{v!r} is not a date") from None


def base_functions(today: date | None = None, now: datetime | None = None) -> dict:
    t = today or date.today()
    return {
        "len": len, "abs": abs, "round": round, "min": min, "max": max, "lower": lambda s: str(s or "").lower(), "upper": lambda s: str(s or "").upper(),
        "contains": lambda a, b: (b in a) if a is not None else False, "startswith": lambda a, b: str(a or "").startswith(str(b)),
        "count": lambda rows: len(rows or []), "sum_of": lambda rows, f: sum((Decimal(str(getattr(r, f) or 0)) for r in (rows or [])), Decimal(0)),
        "today": lambda: t, "now": lambda: now or datetime.now(),
        "days_until": lambda v: ((_to_date(v) - t).days if _to_date(v) else None), "days_since": lambda v: ((t - _to_date(v)).days if _to_date(v) else None),
    }


_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Mod: operator.mod}
_CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
        ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b, ast.Is: operator.is_, ast.IsNot: operator.is_not}
_OK = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Compare,
       ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot, ast.IfExp, ast.Constant, ast.Name, ast.Load, ast.Attribute,
       ast.Subscript, ast.Call, ast.List, ast.Tuple, ast.Set, ast.Slice)


def compile_expr(src: str, functions: set[str] | None = None) -> ast.Expression:
    """Parse and validate. Raises ExprError with a plain-language reason."""
    if not isinstance(src, str) or not src.strip():
        raise ExprError("The expression is empty")
    if len(src) > MAX_LEN:
        raise ExprError(f"The expression is longer than {MAX_LEN} characters")
    try:
        tree = ast.parse(src.strip(), mode="eval")
    except SyntaxError as e:
        raise ExprError(f"Not a valid expression: {e.msg}") from None
    n = 0
    for node in ast.walk(tree):
        n += 1
        if n > MAX_NODES:
            raise ExprError("The expression is too complicated")
        if not isinstance(node, _OK):
            raise ExprError(f"{type(node).__name__} is not allowed in an expression")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExprError(f"'{node.attr}' is not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ExprError(f"'{node.id}' is not allowed")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (str, int, float, bool, type(None))):
            raise ExprError("Only text, numbers, true/false and none are allowed as values")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ExprError("Only plain functions can be called")
            if node.keywords or len(node.args) > 4:
                raise ExprError("Functions take at most 4 plain arguments")
            if functions is not None and node.func.id not in functions:
                raise ExprError(f"'{node.func.id}' is not a function you can use here")
    return tree


def evaluate(tree_or_src, ctx: dict):
    tree = compile_expr(tree_or_src) if isinstance(tree_or_src, str) else tree_or_src

    def ev(node, depth=0):
        if depth > MAX_DEPTH:
            raise ExprError("The expression is nested too deeply")
        d = depth + 1
        if isinstance(node, ast.Expression):
            return ev(node.body, d)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in ctx:
                raise ExprError(f"Unknown name '{node.id}'")
            return ctx[node.id]
        if isinstance(node, ast.BoolOp):
            vals = (ev(v, d) for v in node.values)
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand, d)
            return (not v) if isinstance(node.op, ast.Not) else (-v if isinstance(node.op, ast.USub) else +v)
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left, d), ev(node.right, d)
            if isinstance(node.op, ast.Add) and isinstance(a, str) != isinstance(b, str):
                raise ExprError("Cannot add text and a number")
            try:
                return _BIN[type(node.op)](a, b)
            except ZeroDivisionError:
                raise ExprError("Division by zero") from None
            except TypeError:
                raise ExprError("Those values cannot be combined that way") from None
        if isinstance(node, ast.Compare):
            left = ev(node.left, d)
            for op, comp in zip(node.ops, node.comparators, strict=True):
                right = ev(comp, d)
                try:
                    if not _CMP[type(op)](left, right):
                        return False
                except TypeError:
                    if isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot, ast.In, ast.NotIn)):
                        return isinstance(op, (ast.NotEq, ast.IsNot, ast.NotIn))
                    return False                                           # ordering None with a number etc. is simply "no"
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return ev(node.body, d) if ev(node.test, d) else ev(node.orelse, d)
        if isinstance(node, ast.Attribute):
            base = ev(node.value, d)
            if not isinstance(base, DocView):
                raise ExprError(f"Cannot read '.{node.attr}' here")
            return getattr(base, node.attr)
        if isinstance(node, ast.Subscript):
            base, key = ev(node.value, d), ev(node.slice, d)
            try:
                return base[key]
            except (KeyError, IndexError, TypeError):
                return None
        if isinstance(node, ast.Slice):
            return slice(*(ev(x, d) if x is not None else None for x in (node.lower, node.upper, node.step)))
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(x, d) for x in node.elts]
        if isinstance(node, ast.Set):
            return {ev(x, d) for x in node.elts}
        if isinstance(node, ast.Call):
            fn = ctx.get(node.func.id)
            if not callable(fn):
                raise ExprError(f"'{node.func.id}' is not a function")
            try:
                return fn(*[ev(a, d) for a in node.args])
            except ExprError:
                raise
            except Exception as e:  # noqa: BLE001 - a bad argument is the author's mistake, reported plainly
                raise ExprError(f"{node.func.id}() failed: {e}") from None
        raise ExprError(f"{type(node).__name__} is not allowed")
    return ev(tree)
